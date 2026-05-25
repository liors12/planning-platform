"""Build the canonical takanon CAD dataset for a project.

This module is the entry point — it locates the DWGs under
`data/projects/<plan>/takanon_cad/`, runs ODA File Converter to produce DXFs,
parses them with ezdxf, and writes a single JSON artifact at
`data/projects/<plan>/takanon_cad_dataset.json`.

The artifact is the authoritative source for the plot completeness finding
(Phase 7.1) and any downstream geometric audit (Phase 7.2+).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dxf_reader import read_blue_line_polygon, read_plot_polygons
from .oda_wrapper import convert_dwg_to_dxf


# CODE → Hebrew description.
# Mapping derived empirically by cross-referencing CAD CODE values against the
# planning schema's `land_use` field for plots where both exist (smoke test on
# 407-1048248). Confirmed:
#   CODE 140 → מגורים ד' (residential) on plots 1, 2, 3, 4, 5
#   CODE 670 → שצ"פ (public open space) on plots 6, 7, 8
#   CODE 400 → מבני ציבור (public buildings; mixed with commercial on plot 9)
#   CODE 830 → דרך (road) on plot 10
#   CODE 860 → שביל (path) on plot 20
LAND_USE_CODE_HE: Dict[str, str] = {
    "140": "מגורים ד'",
    "670": 'שצ"פ',
    "400": "מבני ציבור",
    "830": "דרך",
    "860": "שביל",
}


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_data_dir(project_id: str) -> Path:
    return PROJECT_ROOT / "data" / "projects" / project_id


def _takanon_cad_dir(project_id: str) -> Path:
    return _project_data_dir(project_id) / "takanon_cad"


def _dxf_output_dir(project_id: str) -> Path:
    out = _takanon_cad_dir(project_id) / "_dxf"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _heuristic_classify_file(path: Path) -> str:
    """Decide whether a DWG holds the blue-line boundary or the plot polygons.

    Filename convention seen in 407-1048248:
      *תאי שטח*   → plots
      *קו כחול*   → blue line boundary
    """
    name = path.name
    if "תאי שטח" in name or "tashetach" in name.lower() or "plots" in name.lower():
        return "plots"
    if "קו כחול" in name or "blue" in name.lower() or "boundary" in name.lower():
        return "blue_line"
    return "unknown"


def build_takanon_plot_dataset(
    project_id: str,
    *,
    cad_dir: Optional[Path] = None,
    write_artifacts: bool = True,
) -> Dict[str, Any]:
    """Run the ingest pipeline on the takanon DWGs for a project.

    Args:
      project_id: e.g. '407-1048248'.
      cad_dir: override the default takanon_cad/ location. Defaults to
        data/projects/<plan>/takanon_cad/.
      write_artifacts: if True, persist:
          - data/projects/<plan>/takanon_cad_dataset.json
          - data/projects/<plan>/cad_attribute_discrepancies.json (only if any)

    Returns the in-memory dataset dict.
    """
    src_dir = Path(cad_dir) if cad_dir is not None else _takanon_cad_dir(project_id)
    if not src_dir.exists():
        raise FileNotFoundError(
            f"Takanon CAD directory missing: {src_dir}. "
            f"Place the DWGs (קו כחול + תאי שטח) here first."
        )

    dwgs = sorted(src_dir.glob("*.dwg")) + sorted(src_dir.glob("*.DWG"))
    if not dwgs:
        raise FileNotFoundError(f"No DWG files in {src_dir}")

    out_dxf_dir = _dxf_output_dir(project_id)
    source_dwg_paths: List[str] = []
    source_dxf_paths: List[str] = []

    blue_line_polygon = None
    plots: List[Dict[str, Any]] = []
    discrepancies: List[Dict[str, Any]] = []

    for dwg in dwgs:
        source_dwg_paths.append(str(dwg))
        dxf_path = convert_dwg_to_dxf(dwg, out_dxf_dir)
        source_dxf_paths.append(str(dxf_path))
        kind = _heuristic_classify_file(dwg)
        if kind == "blue_line":
            bl = read_blue_line_polygon(dxf_path)
            if bl is not None:
                # Keep the largest blue line if multiple files contribute one
                if blue_line_polygon is None or bl.area > blue_line_polygon.area:
                    blue_line_polygon = bl
        elif kind == "plots":
            file_plots, file_discrepancies = read_plot_polygons(dxf_path)
            plots.extend(file_plots)
            discrepancies.extend(file_discrepancies)
        else:
            # unknown layout — try both
            bl = read_blue_line_polygon(dxf_path)
            if bl is not None and (blue_line_polygon is None or bl.area > blue_line_polygon.area):
                blue_line_polygon = bl
            file_plots, file_discrepancies = read_plot_polygons(dxf_path)
            if file_plots:
                plots.extend(file_plots)
                discrepancies.extend(file_discrepancies)

    # Deduplicate plots by cellno (keep first occurrence — should be unique in practice)
    seen: set[int] = set()
    deduped: List[Dict[str, Any]] = []
    for p in plots:
        if p["cellno"] in seen:
            continue
        seen.add(p["cellno"])
        deduped.append(p)
    plots = sorted(deduped, key=lambda p: p["cellno"])

    # Add human descriptions
    for p in plots:
        p["code_description_he"] = LAND_USE_CODE_HE.get(p["code"], f"קוד {p['code']}")

    dataset = {
        "project_id": project_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "crs": "EPSG:2039",  # Israeli ITM, confirmed in Phase 7.0 smoke test
        "blue_line_wkt": blue_line_polygon.wkt if blue_line_polygon is not None else None,
        "blue_line_area_m2": round(blue_line_polygon.area, 2) if blue_line_polygon is not None else None,
        "plots": [
            {
                "cellno": p["cellno"],
                "code": p["code"],
                "code_description_he": p["code_description_he"],
                "area_m2": p["area_m2"],
                "area_attr_m2": p["area_attr_m2"],
                "polygon_wkt": p["polygon_wkt"],
                "insert_point": list(p["insert_point"]),
            }
            for p in plots
        ],
        "source_dwg_paths": source_dwg_paths,
        "source_dxf_paths": source_dxf_paths,
        "notes": {
            "area_authority": (
                "area_m2 is polygon-derived via shapely (AUTHORITATIVE). "
                "area_attr_m2 is the AREA ATTRIB from the CAD INSERT block "
                "(METADATA ONLY — known to be corrupted on some plots; "
                "see cad_attribute_discrepancies.json)."
            ),
        },
    }

    if write_artifacts:
        out_dataset = _project_data_dir(project_id) / "takanon_cad_dataset.json"
        out_dataset.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        if discrepancies:
            out_discrepancies = _project_data_dir(project_id) / "cad_attribute_discrepancies.json"
            out_discrepancies.write_text(
                json.dumps(discrepancies, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    return dataset


def _main_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the takanon CAD dataset for a project.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--cad-dir", type=Path, default=None,
                        help="Override the default data/projects/<plan>/takanon_cad/ location.")
    args = parser.parse_args(argv)

    dataset = build_takanon_plot_dataset(args.project_id, cad_dir=args.cad_dir)
    print(f"Built takanon CAD dataset for {args.project_id}")
    print(f"  CRS: {dataset['crs']}")
    if dataset["blue_line_area_m2"]:
        print(f"  Blue line area: {dataset['blue_line_area_m2']} m²")
    print(f"  Plots: {len(dataset['plots'])}")
    for p in dataset["plots"]:
        print(
            f"    plot {p['cellno']:>3}  code={p['code']:>4}  "
            f"area={p['area_m2']:>9.2f} m²  ({p['code_description_he']})"
        )

    discr_path = _project_data_dir(args.project_id) / "cad_attribute_discrepancies.json"
    if discr_path.exists():
        d = json.loads(discr_path.read_text(encoding="utf-8"))
        print(f"  ⚠ AREA-attribute discrepancies logged: {len(d)} (see {discr_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main_cli())
