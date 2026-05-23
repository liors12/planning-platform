# PyInstaller spec for the FastAPI sidecar. Produces `dist/sidecar/sidecar` (a
# directory bundle in --onedir mode).
#
# Build:
#   cd app/sidecar && /opt/homebrew/bin/python3.13 -m PyInstaller backend.spec --noconfirm
#
# Architecture decisions:
#   - --onedir (not --onefile): WeasyPrint historically had extraction-overhead
#     issues with onefile mode on first launch (spec § 6).
#   - Hidden imports: SQLAlchemy dialects + uvicorn workers aren't auto-detected.
#   - The sqlcipher3 native shared object lives next to its Python wrapper; we
#     let PyInstaller's binary-collection pick it up via collect_dynamic_libs.
#
# Phase 1 scope:
#   - Bundles the sidecar entry only (uvicorn + FastAPI + SQLCipher).
#   - Does NOT yet bundle worker scripts (echo_worker etc.) — the dev-mode
#     dispatch uses `python -m sidecar.jobs.echo_worker`, which obviously
#     doesn't work for a frozen build. Phase 4 will produce per-worker binaries
#     OR a multi-mode binary that dispatches by --worker-name CLI arg.

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

block_cipher = None

hidden_imports = [
    # SQLAlchemy needs explicit dialect imports under PyInstaller because the
    # entry-point introspection doesn't carry through.
    *collect_submodules("sqlalchemy.dialects.sqlite"),
    # uvicorn's [standard] extras: httptools, websockets, watchfiles, etc.
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI internals
    "fastapi",
    "pydantic",
    "pydantic_core",
    # SQLCipher native + binding
    "sqlcipher3",
]

binaries = []
# Collect the libsqlcipher dylib that sqlcipher3 links against. On macOS this
# resolves the /opt/homebrew/opt/sqlcipher/lib reference at runtime.
binaries += collect_dynamic_libs("sqlcipher3")

a = Analysis(
    # Use the launcher shim (run_sidecar.py) so `sidecar.main` is imported as
    # a package member; otherwise its relative imports break (see pain point
    # #1 in app/sidecar/PYINSTALLER_NOTES.md).
    ["run_sidecar.py"],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we don't ship in the sidecar (Phase 1 forward-compat probe is a
        # separate spec; keeping this lean to surface only sidecar-level issues).
        "tkinter",
        "matplotlib",
        "PIL",
        "weasyprint",
        "fitz",
        "ezdxf",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="sidecar",
)
