"""Subprocess wrapper around ODA File Converter.

Smoke-test learnings (Phase 7.0):
- CLI path on macOS: /Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter
- Args (positional): <input_dir> <output_dir> <output_version> <output_format> <recurse> <audit> <input_filter>
- The CLI is directory-based — single-file conversion requires a temp input dir.
- DO NOT pass QT_QPA_PLATFORM=offscreen — Qt6 macOS build doesn't ship the offscreen
  plugin and aborts. Conversion mode runs silently without a GUI.
- DO NOT pass --help or run with no args — those launch the GUI and block.
- Wall time on small files (~100 KB DWG): <1 sec.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


ODA_CLI = Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")


class OdaConversionError(RuntimeError):
    """Raised when ODA File Converter fails on a DWG."""


def convert_dwg_to_dxf(
    dwg_path: Path,
    output_dir: Path,
    *,
    output_version: str = "ACAD2018",
    audit: bool = True,
    oda_cli: Optional[Path] = None,
) -> Path:
    """Convert a single DWG to DXF using ODA File Converter.

    Sets up a single-file temp input directory (the CLI is dir-based), runs the
    converter, and returns the path to the resulting DXF.

    Raises OdaConversionError on non-zero exit or if the expected DXF is absent.
    """
    cli = Path(oda_cli) if oda_cli is not None else ODA_CLI
    if not cli.exists():
        raise OdaConversionError(
            f"ODA File Converter not found at {cli}. "
            f"Install from https://www.opendesign.com/guestfiles/oda_file_converter"
        )

    dwg_path = Path(dwg_path).resolve()
    if not dwg_path.exists():
        raise OdaConversionError(f"DWG not found: {dwg_path}")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ODA CLI is dir-based — copy the single DWG into an isolated temp input dir
    # so we don't accidentally convert any siblings.
    temp_in = output_dir / "_oda_in"
    temp_in.mkdir(parents=True, exist_ok=True)
    # Clean any stale files from prior runs
    for stale in temp_in.glob("*"):
        stale.unlink()
    shutil.copy2(dwg_path, temp_in / dwg_path.name)

    audit_flag = "1" if audit else "0"
    cmd = [
        str(cli),
        str(temp_in),
        str(output_dir),
        output_version,
        "DXF",
        "0",          # recurse
        audit_flag,
        "*.DWG",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OdaConversionError(
            f"ODA conversion timed out after 120s on {dwg_path.name}"
        ) from exc

    # Clean up the input copy regardless of outcome
    try:
        for f in temp_in.glob("*"):
            f.unlink()
        temp_in.rmdir()
    except OSError:
        pass

    if result.returncode != 0:
        raise OdaConversionError(
            f"ODA File Converter failed (exit={result.returncode}) on "
            f"{dwg_path.name}\nstderr: {result.stderr or '(empty)'}"
        )

    # Output filename is the input name with .dxf extension
    expected_dxf = output_dir / (dwg_path.stem + ".dxf")
    if not expected_dxf.exists():
        # ODA sometimes preserves case differently — search fallback
        candidates = list(output_dir.glob(f"{dwg_path.stem}.dxf")) + list(
            output_dir.glob(f"{dwg_path.stem}.DXF")
        )
        if candidates:
            expected_dxf = candidates[0]
        else:
            raise OdaConversionError(
                f"ODA reported success but no DXF found for {dwg_path.name} "
                f"in {output_dir}"
            )

    return expected_dxf
