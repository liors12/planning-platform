#!/usr/bin/env python3
"""List the DLLs a Windows .exe imports, and fail if it needs the VC++ runtime.

    python3 scripts/pe_imports.py planning-platform.exe            # list
    python3 scripts/pe_imports.py --forbid-vcruntime planning-platform.exe

v0.2.4: planning-platform.exe up to 0.2.3 imported VCRUNTIME140.dll and
VCRUNTIME140_1.dll, which a Windows install without the Visual C++
redistributable does not have - the app died on launch with "VCRUNTIME140.dll
was not found" (VM test, 2026-10-26). STATIC_VCRUNTIME=true links it in. This
script is the proof on the binary itself, run in CI after the build and
usable on the Mac against an unpacked installer. Standard library only, so it
needs nothing installed on either side.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

# The redistributable's DLLs. ucrtbase / api-ms-win-crt-* are the Universal
# CRT, part of Windows 10 and 11 itself, and stay dynamic by design.
VCRUNTIME = re.compile(r"^(vcruntime140(_1)?|msvcp140(_\d+)?)\.dll$", re.I)


def imports(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise ValueError(f"{path}: not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{path}: bad PE signature")
    n_sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)          # PE32+ / PE32
    import_rva = struct.unpack_from("<I", data, dd + 8)[0]   # entry 1: imports
    sections = []
    for i in range(n_sections):
        s = opt + opt_size + 40 * i
        vsize, va, rsize, raw = struct.unpack_from("<IIII", data, s + 8)
        sections.append((va, max(vsize, rsize), raw))

    def off(rva: int) -> int:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError(f"RVA {rva:#x} outside every section")

    names, d = [], off(import_rva)
    while True:
        name_rva = struct.unpack_from("<I", data, d + 12)[0]
        if name_rva == 0:
            break
        o = off(name_rva)
        names.append(data[o:data.index(b"\0", o)].decode("ascii"))
        d += 20
    return sorted(set(names), key=str.lower)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exe", type=Path)
    ap.add_argument("--forbid-vcruntime", action="store_true",
                    help="exit 1 if the exe imports any VC++ redistributable DLL")
    a = ap.parse_args()
    names = imports(a.exe)
    for n in names:
        print(n)
    bad = [n for n in names if VCRUNTIME.match(n)]
    if a.forbid_vcruntime and bad:
        print(f"FAIL: {a.exe.name} imports {', '.join(bad)} - the VC++ runtime "
              "is not linked statically (STATIC_VCRUNTIME)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
