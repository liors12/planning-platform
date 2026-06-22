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

import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# Repo root — needed in pathex so PyInstaller's Analysis pass can resolve
# `compliance_engine.*` imports that originate from inside the sidecar
# package (queue_worker → compliance_engine.render). SPECPATH = the
# directory containing this spec file = app/sidecar/.
ROOT_FROM_SPEC = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

block_cipher = None

hidden_imports = [
    # SQLAlchemy needs explicit dialect imports under PyInstaller because the
    # entry-point introspection doesn't carry through.
    *collect_submodules("sqlalchemy.dialects.sqlite"),
    # ── compliance_engine: render + Excel-export + full-audit path ───────
    # Listed by name (rather than collect_submodules("compliance_engine"))
    # to keep the import list explicit and reviewable.
    # This list covers: render-only, Excel-export, the V0.2 in-process
    # full-audit path (run_full_audit → audit submodule chain), AND the
    # Phase 1 CAD geometric checks (cad_compliance_checker + dxf_geometry).
    "compliance_engine",
    "compliance_engine.render",
    "compliance_engine.report_generator",
    "compliance_engine.report_surgery",
    "compliance_engine.excel_export",
    # Full-audit chain (V0.2 in-process path)
    "compliance_engine.audit",
    "compliance_engine.constants",
    "compliance_engine.content_compliance_checker",
    "compliance_engine.discipline_findings",
    "compliance_engine.discipline_policy_checker",
    "compliance_engine.extraction_cache",
    "compliance_engine.feedback_store",
    "compliance_engine.format_rules_checker",
    "compliance_engine.submission_data_extractor",
    "compliance_engine.submission_extracts",
    # fitz (PyMuPDF) — used by format_rules_checker, discipline_policy_checker,
    # and submission_data_extractor. Previously excluded; needed for full audit.
    "fitz",
    # pdfplumber — used by format_rules_checker and submission_data_extractor.
    *collect_submodules("pdfplumber"),
    # openpyxl is excel_export's hard dependency. Lazy-imported inside
    # excel_export's body — PyInstaller's static analysis doesn't follow
    # transitively into deferred imports, so make it explicit.
    *collect_submodules("openpyxl"),
    # ── CAD geometric analysis (Phase 1) ─────────────────────────────────
    # ezdxf: DXF reader for layer discovery and geometry extraction.
    # shapely: geometric calculations (distance, area, intersection).
    # Both are lazy-imported inside vision_scanner.cad_ingest.dxf_geometry
    # and compliance_engine.cad_compliance_checker, so PyInstaller's static
    # analysis won't pick them up without explicit entries here.
    *collect_submodules("ezdxf"),
    *collect_submodules("shapely"),
    "vision_scanner",
    "vision_scanner.cad_ingest",
    "vision_scanner.cad_ingest.dxf_geometry",
    "compliance_engine.cad_compliance_checker",
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
]

# SQLCipher is optional — only collect it if installed (macOS dev build has
# it; Windows pilot build falls back to stdlib sqlite3 via db.py's
# try/except import). Conditional avoids "package not found" errors at
# PyInstaller analysis time on Windows.
binaries = [*collect_dynamic_libs("shapely")]

try:
    import sqlcipher3  # noqa: F401  # presence-only test
    hidden_imports.append("sqlcipher3")
    binaries += collect_dynamic_libs("sqlcipher3")
except ImportError:
    pass

a = Analysis(
    # Use the launcher shim (run_sidecar.py) so `sidecar.main` is imported as
    # a package member; otherwise its relative imports break (see pain point
    # #1 in app/sidecar/PYINSTALLER_NOTES.md).
    ["run_sidecar.py"],
    # Repo root on pathex so `compliance_engine.*` imports resolve from
    # inside the sidecar package's queue_worker module. Without this,
    # PyInstaller's import-graph walker can't see compliance_engine and
    # the frozen bundle crashes with ModuleNotFoundError at render time.
    pathex=[ROOT_FROM_SPEC],
    binaries=binaries,
    # Stage the static assets + first-run seed inside the bundle.
    # All source paths are relative to this spec file: app/sidecar/backend.spec.
    #
    # The render pipeline + main.py resolve these via sys._MEIPASS at runtime:
    #   compliance_engine._resolve_font_dir            → assets/fonts/
    #   compliance_engine._resolve_logo_path           → assets/nessziona_logo.png
    #   compliance_engine._resolve_format_rules_path   → submission_format_rules.json
    #   sidecar.main._seed_data_dir                    → seed/  (~370 KB pilot data)
    datas=[
        ("../../assets/fonts", "assets/fonts"),
        ("../../assets/nessziona_logo.png", "assets"),
        ("../../submission_format_rules.json", "."),
        # Rules JSONs needed by the V0.2 in-process full-audit path:
        #   audit.py resolves content_rules.json via PROJECT_ROOT (= _MEIPASS in frozen)
        #   discipline_policy_checker.py resolves discipline_rules.json the same way
        ("../../content_rules.json", "."),
        ("../../discipline_rules.json", "."),
        ("seed", "seed"),
    ],
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
