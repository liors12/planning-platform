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
import sys


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
