# PyInstaller bundling notes

Running log of issues + fixes encountered building `--onedir` bundles of the
sidecar and its forward-compat dependency stack. Update as new pain points
surface.

## Two specs, two purposes

| Spec | Output | Purpose |
|---|---|---|
| `backend.spec` | `dist/sidecar/` (44 MB) | The Phase 1+ shipped bundle. Just sidecar deps (FastAPI, SQLCipher, SQLAlchemy, Pydantic, uvicorn). Excludes WeasyPrint / PyMuPDF / ezdxf — those belong in per-worker bundles. |
| `backend_full.spec` | `dist/sidecar_full/` (187 MB) | Forward-compat **probe only**. Bundles the heavy worker deps too, so we can verify NOW that Phase 4 worker bundling won't surprise us. Not shipped. |

Build either:

```bash
cd app/sidecar
/opt/homebrew/bin/python3.13 -m PyInstaller backend.spec      --noconfirm   # production
/opt/homebrew/bin/python3.13 -m PyInstaller backend_full.spec --noconfirm   # probe
```

Probe WeasyPrint inside the bundle:

```bash
./dist/sidecar_full/sidecar_full --probe weasyprint
# expected: {"ok": true, "pdf_bytes": <N>, "magic": "%PDF"}
```

## Pain point log

### #1 — Relative imports in the entry script

**Symptom:** `ImportError: attempted relative import with no known parent package` when launching the bundle.

**Cause:** PyInstaller loads the entry script as `__main__`. `sidecar/main.py` does `from .config import load`, which only works when `main.py` is loaded as a *submodule of* `sidecar`.

**Fix:** Created `run_sidecar.py` — a top-level launcher that does `from sidecar.main import main; main()`. Spec references `run_sidecar.py` as the Analysis input. Package structure stays clean.

**Cost:** 1 new file, no source changes to `sidecar/`.

### #2 — WeasyPrint's ctypes-loaded native deps (Pango / Cairo / GObject / …)

**Symptom (anticipated, not encountered with the fix below):** `OSError: dlopen(libpango-1.0.0.dylib, 6): image not found` from the bundle.

**Cause:** WeasyPrint loads its native rendering stack via `ctypes.CDLL` at runtime. PyInstaller can't introspect ctypes calls, so it doesn't know to collect those dylibs automatically.

**Fix:** Explicit glob in `backend_full.spec` over `/opt/homebrew/lib/lib{pango,cairo,gobject,gio,glib,gdk_pixbuf,fontconfig,freetype,harfbuzz,…}*.dylib`, placed at the bundle root (`(path, ".")`) so the system loader finds them next to the executable.

**Cost:** ~30 lines in the spec; bundle size +110 MB (most of `sidecar_full`'s 187 MB is native libs).

**Note for Windows port:** The dylib glob will need a Windows equivalent (.dll, from MSYS2 or GTK runtime installer). That work lands in Phase 4 with the cross-platform packaging.

### #3 — SQLCipher native lib bundling

**Symptom:** none — `sqlcipher3`'s wheel ships a self-contained extension that PyInstaller's `collect_dynamic_libs("sqlcipher3")` picks up cleanly.

**Why this is worth recording:** common assumption is SQLCipher will be hard to bundle. On macOS arm64 with the `sqlcipher3` wheel installed from a Homebrew-linked source build, it Just Works. Re-verify on Windows; expectation is that the Windows wheel is similarly self-contained.

## What works without fuss (worth noting because it usually doesn't)

- **`uvicorn[standard]`** — explicit hidden imports for `uvicorn.loops.*`, `uvicorn.protocols.*`, `uvicorn.lifespan.*` cover it. No watchfiles tooling issues since we don't run with reload in production.
- **SQLAlchemy 2.x dialects** — `collect_submodules("sqlalchemy.dialects.sqlite")` is sufficient.
- **Pydantic v2** — `pydantic_core` (the Rust compiled module) bundles via the standard hidden-import path. No issues.
- **macOS code signing** — PyInstaller auto-signs the executable with an ad-hoc identity. Production code-signing (per spec § 8) lands in Phase 4 with a real Apple Developer cert.

## Open items for Phase 4

1. **Worker subprocess bundling.** Right now `dispatch.py` spawns `python -m sidecar.jobs.echo_worker` — there's no Python in the production bundle. Options:
   - One PyInstaller binary per worker (cleanest separation, larger total bundle).
   - Multi-mode binary: same bundle runs as sidecar by default, as a worker when invoked with `--worker MODULE --job-dir DIR`. Reuses the `--probe` CLI pattern.
   - Recommendation: multi-mode, because the heavy native deps (Pango/Cairo) would otherwise be duplicated across 4-6 worker bundles.
2. **Tauri `externalBin` wiring.** Tauri v2 expects platform-suffixed binary names (`sidecar-aarch64-apple-darwin`, `sidecar-x86_64-pc-windows-msvc.exe`). Need a tiny rename step in the build pipeline. Trivial.
3. **Windows GTK runtime.** The macOS dylib glob has no Windows equivalent yet. Bundle the [GTK3 for Windows runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer) DLLs or include them as a prerequisite in the NSIS installer.
4. **Bundle size optimization.** 187 MB is large for what's ultimately a CLI tool. Phase 4 can `excludes=[...]` more aggressively (Python's `test` packages, unused stdlib modules) — easy 30-50 MB savings.

## Verification summary (Phase 1)

| Bundle | Status | Verification |
|---|---|---|
| `dist/sidecar/sidecar` (44 MB, sidecar deps only) | ✅ ships clean | `./sidecar` launches, `/health` returns 200 with `cipher_version: 4.12.0 community` + `journal_mode: wal` |
| `dist/sidecar_full/sidecar_full` (187 MB, forward-compat probe) | ✅ all deps load | `--probe weasyprint` emits `{"ok": true, "pdf_bytes": 2831, "magic": "%PDF"}` |
