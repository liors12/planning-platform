"""PyInstaller entry point.

Top-level shim that lets PyInstaller use the `sidecar` package without
breaking its relative imports. `from .config import ...` in `sidecar/main.py`
only works when main.py is loaded as a submodule of `sidecar`, not as
__main__ (which is what PyInstaller does to an entry script).

Also handles the `--probe MODE` CLI used by the Phase 1 forward-compat tests
(see PYINSTALLER_NOTES.md): runs a quick sanity check that a heavy dep was
bundled correctly, then exits without starting uvicorn.
"""
import json
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path


# Force stdout/stderr to UTF-8 so Hebrew filenames + glyphs in engine
# log output don't crash the sidecar on Windows.
#
# Frozen Python on Windows (PyInstaller --onedir) defaults stdout to the
# console code page (commonly cp1252) which can't encode `הערות_סקירה_…`
# in compliance_engine/render.py's `print(f"Excel export: {xlsx_path}")`.
# That kills the in-process Excel-export job mid-run with
# UnicodeEncodeError. Set encoding at startup so every print() across
# the sidecar — including engine modules running in-process — uses UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


# ── Persistent error log ────────────────────────────────────────────────
# Today's primary debug failure mode: the sidecar's only error trail was
# the black console window Tauri opened; close the window and the trace
# is gone forever. Wire a rotating file handler to the root logger
# BEFORE any submodule imports, so every WARNING/ERROR from sidecar.*,
# compliance_engine.*, uvicorn, AND unhandled exceptions land in a file
# that survives the window closing.
#
# Cap: 5 files × 1 MB = 5 MB total — protects against an infinite loop
# filling the disk.
def _install_error_log() -> Path | None:
    try:
        # config.load() resolves data_dir from $PLATFORM_DATA_DIR or
        # %LOCALAPPDATA%\Planning Platform\ on Windows (see config.py).
        # Imported here, not at module top, so cfg.data_dir creation
        # happens AFTER stdout reconfigure above — keeps the boot order
        # the same as before in case anything inside config goes wrong.
        from sidecar.config import load
        cfg = load()
        log_dir = cfg.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "errors.log"
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1_048_576,   # 1 MB per file
            backupCount=4,        # plus current = 5 files total
            encoding="utf-8",
        )
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root = logging.getLogger()
        if root.level == logging.NOTSET or root.level > logging.WARNING:
            root.setLevel(logging.WARNING)
        root.addHandler(handler)
        return log_path
    except Exception as exc:
        # Don't crash the sidecar over a logging setup glitch — the
        # console handler still works.
        print(f"[run_sidecar] could not attach error-log handler: {exc!r}",
              file=sys.stderr)
        return None


_ERROR_LOG_PATH = _install_error_log()


def _excepthook(exc_type, exc_value, exc_tb):
    """Catch unhandled exceptions from threads other than the main
    asyncio loop and write the full traceback to the rotating log."""
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.getLogger("sidecar.unhandled").error(
        "uncaught exception:\n%s", tb,
    )
    # Preserve default behaviour (print to stderr too).
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook


def _probe_weasyprint() -> int:
    """Render a minimal HTML to PDF inside the bundle. Verifies that Pango,
    Cairo, GObject, etc. were collected correctly by PyInstaller AND that
    WeasyPrint can locate them at runtime via ctypes."""
    try:
        from weasyprint import HTML
        pdf = HTML(string="<html><body><h1>probe</h1></body></html>").write_pdf()
        magic = pdf[:4].decode("latin-1") if pdf else ""
        report = {
            "ok": True,
            "pdf_bytes": len(pdf or b""),
            "magic": magic,  # should be "%PDF"
        }
    except Exception as exc:
        report = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    print(json.dumps(report))
    return 0 if report.get("ok") else 2


_PROBES = {
    "weasyprint": _probe_weasyprint,
}


def _maybe_probe(argv: list[str]) -> int | None:
    if "--probe" not in argv:
        return None
    idx = argv.index("--probe")
    if idx + 1 >= len(argv):
        print("usage: sidecar --probe MODE", file=sys.stderr)
        return 2
    mode = argv[idx + 1]
    fn = _PROBES.get(mode)
    if not fn:
        print(f"unknown probe mode: {mode}; available: {list(_PROBES)}", file=sys.stderr)
        return 2
    return fn()


if __name__ == "__main__":
    probe_exit = _maybe_probe(sys.argv)
    if probe_exit is not None:
        sys.exit(probe_exit)
    from sidecar.main import main
    sys.exit(main() or 0)
