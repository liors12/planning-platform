# PyInstaller spec — FORWARD-COMPAT probe: sidecar + the heavy deps the real
# workers will need (WeasyPrint, PyMuPDF, ezdxf). Purpose is to surface
# bundling pain points NOW, not in Phase 4.
#
# Build:
#   cd app/sidecar && /opt/homebrew/bin/python3.13 -m PyInstaller backend_full.spec --noconfirm
#
# This bundle is NOT shipped to users. It exists to test that the dependency
# stack survives --onedir packaging. See PYINSTALLER_NOTES.md for the running
# log of issues + fixes.

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None


hidden_imports = [
    *collect_submodules("sqlalchemy.dialects.sqlite"),
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "fastapi", "pydantic", "pydantic_core",
    "sqlcipher3",
    # The forward-compat deps:
    "weasyprint",
    "fontTools",
    "tinycss2",
    "cssselect2",
    "html5lib",
    "Pyphen",
    "fitz",   # PyMuPDF
]

binaries = []
binaries += collect_dynamic_libs("sqlcipher3")

# WeasyPrint loads its native deps (Pango, Cairo, GdkPixbuf, GObject, etc.) via
# ctypes at runtime. PyInstaller can't introspect ctypes; we have to collect
# the dylibs explicitly from the Homebrew prefix.
import os, glob
HOMEBREW_LIB = "/opt/homebrew/lib"
WEASYPRINT_DYLIBS = []
for pattern in [
    "libpango-1.0*.dylib",
    "libpangoft2-1.0*.dylib",
    "libpangocairo-1.0*.dylib",
    "libcairo*.dylib",
    "libgdk_pixbuf-2.0*.dylib",
    "libgobject-2.0*.dylib",
    "libgio-2.0*.dylib",
    "libglib-2.0*.dylib",
    "libgmodule-2.0*.dylib",
    "libgthread-2.0*.dylib",
    "libffi*.dylib",
    "libfontconfig*.dylib",
    "libfreetype*.dylib",
    "libharfbuzz*.dylib",
    "libpixman-1*.dylib",
    "libpng16*.dylib",
    "libintl*.dylib",
    "libpcre2-8*.dylib",
]:
    for path in glob.glob(os.path.join(HOMEBREW_LIB, pattern)):
        # Place at bundle root so WeasyPrint's ctypes.CDLL finds them.
        WEASYPRINT_DYLIBS.append((path, "."))

binaries += WEASYPRINT_DYLIBS


datas = []
datas += collect_data_files("weasyprint")


a = Analysis(
    ["run_sidecar.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL.ImageTk"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="sidecar_full",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name="sidecar_full",
)
