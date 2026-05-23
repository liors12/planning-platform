"""Loader for hand-extracted (or vision-extracted) submission values.

The architect's PDF for v24.3 is rasterized, so automatic extraction yields
mostly nulls. A hand-extracted JSON (`extracts.json`) sitting next to the
PDF in the submission directory is the temporary source of truth until
v8a-2 ships the vision-LLM extractor.

Schema is documented at the top of the JSON file itself. Per-plot fields:
  units_proposed, height_m, floors_above_ground, floors_technical_roof,
  primary_area_sqm, service_area_above_sqm, service_area_below_sqm,
  parking: {private, motorcycle, accessible, bicycle},
  unit_mix: {count_le_55sqm, count_56_to_75sqm, count_76_to_99sqm,
             count_ge_100sqm, average_sqm}
  _status (optional): "NOT_IN_SUBMISSION" → plot expected in תב"ע but absent.

Plan-wide fields:
  total_units_proposed, small_apartments_count, small_apartments_percent_calculated,
  infiltration_area_total_sqm, infiltration_area_percent, stormwater_retention_cubic_m

Returns {} when no extracts.json exists — engine falls back to whatever the
automated extractor produced (typically nulls → "לא הוגש").
"""
from __future__ import annotations

import json
from pathlib import Path


def load_extracts(submission_dir: Path | str) -> dict:
    extracts_path = Path(submission_dir) / "extracts.json"
    if not extracts_path.exists():
        return {}
    with extracts_path.open("r", encoding="utf-8") as f:
        return json.load(f)
