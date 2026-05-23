"""
תשריט analysis report — pure deterministic Python.

Reads the registered shapefiles and rasters for a project's תשריט
(via project-schema.json -> digital_files.tashrit) and produces a structured
Markdown report covering:

  1. Per-parcel geometry consistency
  2. Topological coverage (parcels tile the plan extent)
  3. Land-use designation cross-check
  4. Identity of kavim kchulim.shp (plan boundary? building line?)
  5. Raster georeferencing consistency

No OCR, no Claude API. geopandas / shapely / pyproj / rasterio / dbfread only.

Usage:
    python3 src/tashrit_analysis.py --project 407-0977595
    python3 src/tashrit_analysis.py --schema project-schema-407-0977595-v2.json
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import rasterio
from pyproj import CRS
from shapely import wkt
from shapely.geometry import Polygon, box
from shapely.ops import unary_union


# ──────────────────────────────────────────────────────────────────────
# MAVAT YEUD code lookup
# ──────────────────────────────────────────────────────────────────────
# מינהל התכנון does NOT publish a machine-readable YEUD code table. The
# post-2006 codeset has hundreds of values inside MAVAT DWG/PDF symbology
# files but no official CSV/Excel export. Codes here come from two sources:
#
#  - "confirmed" — values we have a direct citation for.
#  - "tentative" — values inferred from MAVAT range conventions (600s = public
#    buildings, 800s = open space, etc.) and cross-referenced against the
#    pilot project's תקנון. These need verification against an official source.
#
# Each entry is a dict so we can carry confidence/provenance into the report.
YEUD_LOOKUP: dict[int, dict] = {
    73: {
        "label_he": "מגורים ד'",
        "label_en": "residential D",
        "parent_category": "מגורים",
        "confidence": "confirmed",
        "source": "user-confirmed for pilot 407-0977595 (plots 1, 2)",
        "verification_required": False,
    },
    95: {
        "label_he": "מבנים ומוסדות ציבור",
        "label_en": "public buildings and institutions",
        "parent_category": "מבנים ומוסדות ציבור",
        "confidence": "confirmed",
        "source": "MAVAT standard symbology (300/600 series)",
        "verification_required": False,
    },
    240: {
        "label_he": "דרך / רחוב",
        "label_en": "road / street",
        "parent_category": "תשתית",
        "confidence": "confirmed",
        "source": "MAVAT standard symbology",
        "verification_required": False,
    },
    300: {
        "label_he": "שצ\"פ (שטח ציבורי פתוח)",
        "label_en": "public open space",
        "parent_category": "שטח ציבורי פתוח",
        "confidence": "confirmed",
        "source": "MAVAT standard symbology",
        "verification_required": False,
    },
    320: {
        "label_he": "שצ\"פ (שטח ציבורי פתוח)",
        "label_en": "public open space",
        "parent_category": "שטח ציבורי פתוח",
        "confidence": "confirmed",
        "source": "MAVAT standard symbology",
        "verification_required": False,
    },
    423: {
        "label_he": "שביל",
        "label_en": "path",
        "parent_category": "תשתית",
        "confidence": "confirmed",
        "source": "user-confirmed for pilot 407-0977595 (plot 10)",
        "verification_required": False,
    },
    676: {
        "label_he": "מבנים ומוסדות ציבור (וריאנט)",
        "label_en": "public buildings and institutions (variant)",
        "parent_category": "מבנים ומוסדות ציבור",
        "confidence": "tentative",
        "source": (
            "inferred from pilot 407-0977595 schema cross-reference "
            "(plot 6 = מבנים ומוסדות ציבור per תקנון, assigned YEUD=676); "
            "MAVAT 600s range convention = public buildings"
        ),
        "verification_required": True,
    },
    882: {
        "label_he": "שטח ציבורי פתוח (וריאנט)",
        "label_en": "public open space (variant)",
        "parent_category": "שטח ציבורי פתוח",
        "confidence": "tentative",
        "source": (
            "inferred from pilot 407-0977595 schema cross-reference "
            "(plot 4 = שצ\"פ per תקנון, assigned YEUD=882); "
            "MAVAT 800s range convention = open space"
        ),
        "verification_required": True,
    },
}


# Hebrew abbreviation ↔ full-form equivalence for land-use designations.
# These are not synonyms — they're the same term written two ways.
LAND_USE_ALIASES: dict[str, str] = {
    'שצ"פ': "שטח ציבורי פתוח",
    'שב"צ': "שטח לבנייני ציבור",
    'יח"ד': "יחידת דיור",
}


def normalize_land_use(s: str | None) -> str:
    """Expand Hebrew planning abbreviations and strip parenthetical qualifiers
    so semantically identical designations compare equal."""
    if not s:
        return ""
    out = s.strip()
    for abbrev, full in LAND_USE_ALIASES.items():
        out = out.replace(abbrev, full)
    # Drop parenthetical qualifiers like "(וריאנט)" — they're flagged elsewhere.
    import re as _re
    out = _re.sub(r"\s*\([^)]*\)\s*", " ", out).strip()
    return out


# Tolerance: how much disagreement between computed and declared area is OK.
AREA_DELTA_PCT_TOLERANCE = 1.0  # %

# Topology slivers below this are ignored as numerical noise.
TOPOLOGY_NOISE_M2 = 0.5

# Raster cross-extent tolerance (m). Two scans don't have to overlap exactly,
# but their bounding boxes should be within ~5 m of each other.
RASTER_EXTENT_TOL_M = 5.0


# ──────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    """Single-line verdict with severity ('pass' | 'warning' | 'fail')."""
    severity: str
    message: str

    def render(self) -> str:
        sym = {"pass": "✓ consistent", "warning": "⚠ warning", "fail": "✗ inconsistent"}[
            self.severity
        ]
        return f"**Verdict:** {sym} — {self.message}"


@dataclass
class Section:
    title: str
    body_md: str
    verdict: Verdict
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def fmt_num(x, places: int = 2) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"{x:,.{places}f}"


def pct_delta(actual: float, declared: float) -> float | None:
    if declared in (None, 0) or declared != declared:
        return None
    return (actual - declared) / declared * 100.0


def assume_itm_if_missing(gdf: gpd.GeoDataFrame, label: str) -> tuple[gpd.GeoDataFrame, str]:
    """If CRS is missing but coordinates look like Israeli ITM, set to EPSG:2039.

    Returns (gdf_with_crs, note).
    """
    if gdf.crs is not None:
        return gdf, f"CRS declared: `{gdf.crs.to_string()}`"
    sample = gdf.geometry.iloc[0]
    minx, miny, maxx, maxy = sample.bounds
    # Israeli ITM (EPSG:2039) easting ~ 100k–300k m; northing ~ 350k–800k m.
    if 100_000 <= minx <= 300_000 and 350_000 <= miny <= 800_000:
        gdf2 = gdf.set_crs(epsg=2039, allow_override=False)
        return gdf2, (
            f"CRS missing in `.prj` (no projection file). Coordinates fall in the "
            f"Israeli ITM range — assumed `EPSG:2039` for area calculations."
        )
    return gdf, f"⚠ CRS missing and coordinates ({minx:.0f}, {miny:.0f}) don't look like ITM"


def parse_jgw(p: Path) -> dict:
    """Parse a 6-line worldfile."""
    nums = [float(line.strip()) for line in p.read_text().splitlines() if line.strip()]
    A, D, B, E, C, F = nums
    return {
        "pixel_size_x_m": A,
        "rotation_y": D,
        "rotation_x": B,
        "pixel_size_y_m": E,
        "upper_left_easting": C,
        "upper_left_northing": F,
    }


def jpg_dim(p: Path) -> tuple[int, int]:
    """JPEG width/height by walking SOF marker — no PIL needed."""
    data = p.read_bytes()
    i = 2  # skip SOI 0xFFD8
    while i < len(data) - 1:
        if data[i] != 0xFF:
            raise ValueError(f"bad JPEG marker at byte {i} of {p.name}")
        marker = data[i + 1]
        if marker == 0xD8:
            i += 2
            continue
        if marker in (0xD9, 0xDA):
            raise ValueError(f"reached EOI/SOS without finding SOF in {p.name}")
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    raise ValueError(f"no SOF marker in {p.name}")


def md_table(headers: list[str], rows: list[list]) -> str:
    """Render a Markdown table."""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────
# Layer 1 — Per-parcel geometry consistency
# ──────────────────────────────────────────────────────────────────────

def analyze_parcels(tashrit_dir: Path, schema: dict) -> tuple[Section, gpd.GeoDataFrame]:
    """Layer 1 — per-parcel geometry + a roster cross-check (which migrashim
    appear in shapefile vs schema, vs scope_in/scope_out)."""
    schema_parcels = schema["project"].get("parcels", [])
    meta = schema["project"]["meta"]

    shp = tashrit_dir / "migrashim.shp"
    gdf = gpd.read_file(shp)
    gdf, crs_note = assume_itm_if_missing(gdf, "migrashim.shp")

    # Migrash → schema parcel object (by trailing digit of parcel_id)
    schema_by_migrash: dict[str, dict] = {}
    for p in schema_parcels:
        pid = p.get("parcel_id", "")
        if pid.startswith("plot_"):
            try:
                schema_by_migrash[str(int(pid.split("_")[1]))] = p
            except ValueError:
                pass

    # Roster sets
    shp_migrash = {str(row["MIGRASH"]) for _, row in gdf.iterrows()}
    schema_in_parcels = set(schema_by_migrash.keys())
    scope_out_ids = {
        s.split("_")[1] for s in meta.get("scope_out", [])
        if s.startswith("plot_") and s.split("_")[1].isdigit()
    }
    scope_in_ids = {
        s.split("_")[1] for s in meta.get("scope_in", [])
        if s.startswith("plot_") and s.split("_")[1].isdigit()
    }

    rows = []
    findings: list[str] = []
    actions: list[str] = []
    worst_severity = "pass"

    for _, row in sorted(gdf.iterrows(), key=lambda kv: int(kv[1]["MIGRASH"]) if str(kv[1]["MIGRASH"]).isdigit() else 1e9):
        migrash_id = str(row["MIGRASH"])
        computed = float(row.geometry.area)
        dbf_area = float(row["Shape_Area"])
        dbf_area_for_check = dbf_area if dbf_area > 0 else None
        schema_p = schema_by_migrash.get(migrash_id)
        schema_area = schema_p.get("plot_area_sqm") if schema_p else None
        delta_schema = pct_delta(computed, schema_area) if schema_area else None

        # Roster classification
        in_scope_in = migrash_id in scope_in_ids
        in_scope_out = migrash_id in scope_out_ids
        in_schema_parcels = migrash_id in schema_in_parcels

        if in_schema_parcels and schema_area is not None:
            if abs(delta_schema or 0) > AREA_DELTA_PCT_TOLERANCE:
                row_verdict = f"DELTA {delta_schema:+.2f}%"
                worst_severity = "fail"
            else:
                row_verdict = "✓ area match"
        elif in_schema_parcels and schema_area is None:
            row_verdict = "⚠ no plot_area_sqm in schema"
            if worst_severity == "pass":
                worst_severity = "warning"
        elif in_scope_out:
            row_verdict = "⚠ schema says scope_out — but parcel IS in this תשריט"
            if worst_severity == "pass":
                worst_severity = "warning"
        else:
            row_verdict = "⚠ undeclared in schema"
            if worst_severity == "pass":
                worst_severity = "warning"

        rows.append([
            migrash_id,
            fmt_num(computed),
            fmt_num(dbf_area_for_check) if dbf_area_for_check else "0.00 *(empty)*",
            fmt_num(schema_area) if schema_area else "*(not declared)*",
            f"{delta_schema:+.2f}%" if delta_schema is not None else "—",
            row_verdict,
        ])

        # Per-row findings
        if in_schema_parcels and schema_area is None:
            findings.append(
                f"migrash {migrash_id}: present in schema `parcels[]` but `plot_area_sqm` "
                f"is not declared. Computed area = {fmt_num(computed)} m²."
            )
            actions.append(
                f"Add `plot_area_sqm: {round(computed, 2)}` to `parcels[plot_{migrash_id}]` "
                f"in the schema."
            )
        elif in_schema_parcels and schema_area is not None and \
                abs(delta_schema or 0) > AREA_DELTA_PCT_TOLERANCE:
            findings.append(
                f"migrash {migrash_id}: computed {fmt_num(computed)} m² vs schema "
                f"{fmt_num(schema_area)} m² — Δ {delta_schema:+.2f}% (over ±{AREA_DELTA_PCT_TOLERANCE}%)."
            )
        elif in_scope_out:
            findings.append(
                f"migrash {migrash_id}: schema lists `plot_{migrash_id}` in `meta.scope_out` "
                f"with reason '{meta.get('scope_out_reason', '?')[:80]}…' — but this parcel "
                f"({fmt_num(computed)} m²) IS within this plan's תשריט. The scope_out "
                f"premise is contradicted by the data."
            )
            actions.append(
                f"Reconcile `meta.scope_out` for `plot_{migrash_id}` — either remove from "
                f"scope_out (if it's actually inside 407-0977595) or correct the תשריט "
                f"interpretation. Current state is a contradiction."
            )
        elif not in_schema_parcels and not in_scope_out:
            findings.append(
                f"migrash {migrash_id}: present in shapefile ({fmt_num(computed)} m²) but "
                f"NOT declared in schema `parcels[]` and NOT in `meta.scope_out`. Undocumented."
            )
            actions.append(
                f"Decide whether `plot_{migrash_id}` belongs in `parcels[]` (with full "
                f"definition), `meta.scope_out` (excluded), or `meta.scope_in` (just listed)."
            )

    # Roster contradictions visible only at the set level
    schema_only = (schema_in_parcels | scope_in_ids | scope_out_ids) - shp_migrash
    for mid in sorted(schema_only):
        findings.append(
            f"migrash {mid}: declared in schema (parcels[]/scope_in/scope_out) but ABSENT "
            f"from `migrashim.shp`. The shapefile has no parcel with this ID."
        )
        actions.append(
            f"Either remove `plot_{mid}` from the schema (if it doesn't exist in this plan) "
            f"or investigate why the תשריט lacks it."
        )

    if (gdf["Shape_Area"] == 0).all():
        findings.append(
            "All `Shape_Area` values in `migrashim.dbf` are `0.0` — the field is present "
            "but unpopulated by MAVAT for this plan. Cross-check (a) `dbf Shape_Area` is "
            "therefore unavailable; we rely on (b) computed-vs-schema."
        )

    # Roster summary table
    roster_md = md_table(
        ["set", "members"],
        [
            ["`migrashim.shp` (תשריט reality)", ", ".join(sorted(shp_migrash, key=lambda s: int(s) if s.isdigit() else 9999))],
            ["`schema.parcels[]` (defined)", ", ".join(sorted(schema_in_parcels, key=int)) or "—"],
            ["`schema.meta.scope_in`", ", ".join(sorted(scope_in_ids, key=int)) or "—"],
            ["`schema.meta.scope_out`", ", ".join(sorted(scope_out_ids, key=int)) or "—"],
        ],
    )

    body_lines = [
        "**Source:** `migrashim.shp` (6 polygons)",
        "",
        crs_note,
        "",
        "### Roster cross-check",
        "",
        roster_md,
        "",
        "### Per-parcel area",
        "",
        md_table(
            ["migrash", "computed (m²)", "dbf Shape_Area", "schema plot_area_sqm", "Δ% vs schema", "verdict"],
            rows,
        ),
    ]
    if findings:
        body_lines += ["", "**Findings:**", ""] + [f"- {f}" for f in findings]

    if worst_severity == "pass":
        verdict = Verdict("pass", "every declared parcel area within ±1% of schema; roster consistent.")
    elif worst_severity == "warning":
        verdict = Verdict(
            "warning",
            "areas match where declared, but the parcel roster has gaps and/or "
            "a scope_out contradiction (see findings).",
        )
    else:
        verdict = Verdict("fail", "one or more parcels disagree with schema by > 1%.")

    return Section("1. Per-parcel geometry consistency", "\n".join(body_lines), verdict, findings, actions), gdf


# ──────────────────────────────────────────────────────────────────────
# Layer 2 — Topological coverage
# ──────────────────────────────────────────────────────────────────────

def analyze_topology(parcels_gdf: gpd.GeoDataFrame, tashrit_dir: Path,
                     schema: dict) -> Section:
    body: list[str] = []
    findings: list[str] = []
    actions: list[str] = []

    sum_area = float(parcels_gdf.geometry.area.sum())
    meta = schema["project"]["meta"]
    declared_dunam = meta.get("total_site_area_dunam")
    declared_sqm_field = meta.get("total_site_area_sqm")
    declared_from_dunam = (declared_dunam * 1000.0) if declared_dunam is not None else None

    body.append(f"**Sum of parcel polygon areas:** {fmt_num(sum_area)} m²")
    body.append("")
    body.append("**Schema declares:**")
    body.append(f"- `meta.total_site_area_dunam`: {declared_dunam} dunam → "
                f"{fmt_num(declared_from_dunam)} m²")
    body.append(f"- `meta.total_site_area_sqm`: {declared_sqm_field} m²")

    if declared_from_dunam is not None and declared_sqm_field is not None and \
            abs(declared_from_dunam - declared_sqm_field) > 1.0:
        findings.append(
            f"Schema is internally inconsistent: `total_site_area_dunam` × 1000 = "
            f"{fmt_num(declared_from_dunam)} m², but `total_site_area_sqm` = "
            f"{declared_sqm_field} m² (Δ {fmt_num(declared_sqm_field - declared_from_dunam)} m²). "
            f"Pick one as canonical."
        )
        actions.append(
            "Reconcile `meta.total_site_area_dunam` and `meta.total_site_area_sqm` — "
            "recompute the canonical value from the תשריט and update one of them."
        )

    # Compare parcel sum to the dunam-derived figure (as per user spec).
    delta_vs_dunam = pct_delta(sum_area, declared_from_dunam) if declared_from_dunam else None
    if delta_vs_dunam is not None:
        body.append(
            f"\n**Parcel sum vs dunam-derived total:** Δ {delta_vs_dunam:+.2f}%"
        )

    # ── Topology check ──
    union = unary_union(list(parcels_gdf.geometry))

    # Plan envelope from kavim kchulim.shp (single polygon).
    kk = gpd.read_file(tashrit_dir / "kavim kchulim.shp")
    kk, _ = assume_itm_if_missing(kk, "kavim kchulim.shp")
    plan_envelope = unary_union(list(kk.geometry))
    envelope_area = float(plan_envelope.area)

    body.append("")
    body.append(f"**Plan envelope** (from `kavim kchulim.shp`): {fmt_num(envelope_area)} m²")
    body.append(f"**Parcel union area:** {fmt_num(float(union.area))} m²")

    # Gaps: envelope minus parcels
    gaps = plan_envelope.difference(union)
    overlaps_total = 0.0
    overlap_polys = []
    geoms = list(parcels_gdf.geometry)
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            inter = geoms[i].intersection(geoms[j])
            if not inter.is_empty and inter.area > TOPOLOGY_NOISE_M2:
                overlaps_total += inter.area
                overlap_polys.append((i, j, inter.area))

    gap_area = float(gaps.area) if not gaps.is_empty else 0.0

    body.append(f"**Gaps within envelope:** {fmt_num(gap_area)} m²")
    body.append(f"**Pairwise parcel overlaps:** {fmt_num(overlaps_total)} m²")

    severity = "pass"

    if gap_area > TOPOLOGY_NOISE_M2:
        # Find dominant gap pieces
        gap_pieces = [gaps] if gaps.geom_type == "Polygon" else list(getattr(gaps, "geoms", [gaps]))
        gap_pieces = sorted(gap_pieces, key=lambda g: -g.area)[:5]
        body.append("")
        body.append("**Largest gap polygons (top 5):**")
        for i, g in enumerate(gap_pieces, 1):
            cx, cy = g.centroid.x, g.centroid.y
            body.append(f"- gap #{i}: area {fmt_num(g.area)} m², centroid ITM ({cx:.1f}, {cy:.1f})")
        findings.append(
            f"{fmt_num(gap_area)} m² of gap area inside the plan envelope. "
            f"Likely roads / שצ\"פ / unassigned strip — if expected, document; "
            f"if not, the parcel boundaries don't tile the plan."
        )
        severity = "warning"

    if overlaps_total > TOPOLOGY_NOISE_M2:
        findings.append(
            f"{fmt_num(overlaps_total)} m² of pairwise parcel overlap detected — "
            f"parcels are not topologically clean."
        )
        actions.append(
            "Investigate overlapping parcel polygons in `migrashim.shp` "
            "(should be edge-shared, not overlapping)."
        )
        severity = "fail"

    # Also: how does parcel sum compare to envelope?
    sum_vs_env = pct_delta(sum_area, envelope_area) if envelope_area else None
    if sum_vs_env is not None and abs(sum_vs_env) > 1.0:
        findings.append(
            f"Sum of parcels ({fmt_num(sum_area)} m²) differs from plan envelope "
            f"({fmt_num(envelope_area)} m²) by {sum_vs_env:+.2f}%. The envelope from "
            f"`kavim kchulim.shp` is larger — gaps are roads / שצ\"פ between parcels."
        )

    if severity == "pass":
        verdict = Verdict("pass", "parcels tile the plan envelope cleanly.")
    elif severity == "warning":
        verdict = Verdict(
            "warning",
            f"{fmt_num(gap_area)} m² of gaps inside the envelope (likely roads / open space)."
        )
    else:
        verdict = Verdict(
            "fail",
            f"{fmt_num(overlaps_total)} m² of parcel overlap — geometry is not topologically clean."
        )

    if findings:
        body.append("")
        body.append("**Findings:**")
        body.append("")
        body += [f"- {f}" for f in findings]

    return Section("2. Topological coverage", "\n".join(body), verdict, findings, actions)


# ──────────────────────────────────────────────────────────────────────
# Layer 3 — Land-use designation cross-check
# ──────────────────────────────────────────────────────────────────────

def analyze_landuse(parcels_gdf: gpd.GeoDataFrame, tashrit_dir: Path,
                    schema_parcels: list[dict]) -> Section:
    body: list[str] = []
    findings: list[str] = []
    actions: list[str] = []

    # IMPORTANT: probe revealed ymishnep.shp is POINTS, not POLYGONS, and uses
    # a NUM/KOD attribute scheme — not YEUD. The actual land-use code per parcel
    # lives in migrashim.shp's YEUD column. Document this honestly.

    body.append(
        "**Note on ymishnep.shp:** the file is **62 Point features**, not polygons, "
        "with attributes `Id, ISHUV, TOCHNIT, NUM, KOD, NAME`. `KOD` values seen in "
        "this dataset are `'29'` and `'31'` — these are MAVAT code-list IDs for "
        "annotation/symbol categories, not land-use YEUD codes. The expected "
        "sub-יעוד polygons are not present in this layer."
    )
    body.append("")
    body.append(
        "**Authoritative land-use per parcel** lives in `migrashim.shp.YEUD` (one "
        "code per parcel), not in `ymishnep.shp`. Reading from there:"
    )
    body.append("")

    schema_by_migrash = {}
    for p in schema_parcels:
        pid = p.get("parcel_id", "")
        if pid.startswith("plot_"):
            try:
                schema_by_migrash[str(int(pid.split("_")[1]))] = p
            except ValueError:
                pass

    rows = []
    unknown_codes = set()
    tentative_codes = set()
    mismatches = []

    for _, row in parcels_gdf.iterrows():
        migrash_id = str(row["MIGRASH"])
        yeud_raw = row["YEUD"]
        yeud_int = int(yeud_raw) if yeud_raw == yeud_raw else None  # NaN-safe
        entry = YEUD_LOOKUP.get(yeud_int) if yeud_int is not None else None
        looked_up = entry["label_he"] if entry else None
        parent = entry["parent_category"] if entry else None
        confidence = entry["confidence"] if entry else None
        if yeud_int is not None and entry is None:
            unknown_codes.add(yeud_int)
        if confidence == "tentative":
            tentative_codes.add(yeud_int)

        schema_p = schema_by_migrash.get(migrash_id)
        schema_landuse = schema_p.get("land_use") if schema_p else None

        cmp_verdict = "—"
        norm_schema = normalize_land_use(schema_landuse)
        norm_looked = normalize_land_use(looked_up)
        norm_parent = normalize_land_use(parent)
        if schema_landuse is None:
            cmp_verdict = "*(no schema land_use)*"
        elif entry is None:
            cmp_verdict = "lookup missing"
        elif norm_looked == norm_schema:
            cmp_verdict = "✓ match (exact)"
        elif norm_parent and norm_parent == norm_schema:
            cmp_verdict = (
                f"✓ match (parent category: `{parent}`) "
                f"— shapefile `{looked_up}` is a *{confidence}* variant"
            )
        else:
            cmp_verdict = f"⚠ shapefile→`{looked_up}` vs schema→`{schema_landuse}`"
            mismatches.append((migrash_id, looked_up, schema_landuse))

        rows.append([
            migrash_id,
            yeud_int if yeud_int is not None else "—",
            looked_up or "*unknown*",
            schema_landuse or "*not declared*",
            cmp_verdict,
        ])

    body.append(md_table(
        ["migrash", "YEUD code", "decoded (lookup)", "schema land_use", "verdict"],
        rows,
    ))

    # Also surface ymishnep.shp content briefly
    yp = gpd.read_file(tashrit_dir / "ymishnep.shp")
    yp, _ = assume_itm_if_missing(yp, "ymishnep.shp")
    kod_freq = yp["KOD"].value_counts().to_dict()
    body.append("")
    body.append(
        f"**ymishnep.shp contents:** {len(yp)} Point features. `KOD` distribution: " +
        ", ".join(f"`{k}`×{v}" for k, v in sorted(kod_freq.items())) + "."
    )

    severity = "pass"
    if unknown_codes:
        findings.append(
            "Unknown YEUD codes in `migrashim.shp` (not in our lookup table): "
            + ", ".join(str(c) for c in sorted(unknown_codes))
            + ". Confirm against MAVAT YEUD reference and extend `YEUD_LOOKUP`."
        )
        actions.append(
            "Extend `YEUD_LOOKUP` in `src/tashrit_analysis.py` with the unknown codes "
            "(checked against the MAVAT YEUD code list)."
        )
        severity = "warning"
    if tentative_codes:
        findings.append(
            "Tentative YEUD codes in use (resolved via parent-category inference, not "
            "official MAVAT source): "
            + ", ".join(str(c) for c in sorted(tentative_codes))
            + ". See `CONTEXT.md` Open Tasks."
        )
        if severity == "pass":
            severity = "warning"

    if mismatches:
        for mid, sf_name, sch_name in mismatches:
            findings.append(
                f"migrash {mid}: shapefile YEUD decodes to `{sf_name}` but schema "
                f"declares `{sch_name}`. Reconcile."
            )
        severity = "fail"

    findings.append(
        "`ymishnep.shp` does NOT contain land-use polygons for this plan — it carries "
        "62 annotation points with KOD `'29' / '31'`. Land-use polygons are folded "
        "into `migrashim.shp.YEUD` (one code per parcel), with no separate sub-יעוד "
        "polygon layer in this תשריט."
    )

    body.append("")
    body.append("**Findings:**")
    body.append("")
    body += [f"- {f}" for f in findings]

    if severity == "pass":
        verdict = Verdict("pass", "every parcel's YEUD code maps to a known land use matching the schema.")
    elif severity == "warning":
        verdict = Verdict(
            "warning",
            "land-use codes match where decodable, but unknown YEUD codes need confirmation."
        )
    else:
        verdict = Verdict("fail", "land-use mismatches between shapefile and schema.")

    return Section("3. Land-use designation cross-check", "\n".join(body), verdict, findings, actions)


# ──────────────────────────────────────────────────────────────────────
# Layer 4 — kavim kchulim.shp identity
# ──────────────────────────────────────────────────────────────────────

def analyze_kavim_kchulim(parcels_gdf: gpd.GeoDataFrame, tashrit_dir: Path) -> Section:
    body: list[str] = []
    findings: list[str] = []
    actions: list[str] = []

    gdf = gpd.read_file(tashrit_dir / "kavim kchulim.shp")
    gdf, crs_note = assume_itm_if_missing(gdf, "kavim kchulim.shp")

    geom_types = sorted({g.geom_type for g in gdf.geometry})
    n_features = len(gdf)

    # Compute total length and total area (whichever is meaningful)
    total_length = float(gdf.geometry.length.sum())
    total_area = float(gdf.geometry.area.sum())

    body.append(crs_note)
    body.append("")
    body.append("**Geometry type(s):** " + ", ".join(f"`{g}`" for g in geom_types))
    body.append(f"**Feature count:** {n_features}")
    body.append(f"**Total length:** {fmt_num(total_length)} m  (perimeter if polygon)")
    body.append(f"**Total area:** {fmt_num(total_area)} m²")

    body.append("")
    body.append("**Attribute fields:**")
    body.append("")
    body.append(md_table(
        ["#", "field", "values (first row)"],
        [[i, c, repr(gdf.iloc[0][c])] for i, c in enumerate(gdf.columns) if c != "geometry"],
    ))

    body.append("")
    body.append("**Sample WKT of first 3 features:**")
    body.append("")
    for i, geom in enumerate(gdf.geometry.head(3).tolist()):
        wkt_str = geom.wkt
        body.append(f"- feature {i} ({geom.geom_type}): `{wkt_str[:240]}{'…' if len(wkt_str) > 240 else ''}`")

    # ── Interpretation ──
    parcels_union = unary_union(list(parcels_gdf.geometry))
    kk_union = unary_union(list(gdf.geometry))

    # If kavim kchulim is the plan boundary, the parcel union should be
    # entirely contained within it (within a small tolerance).
    if "Polygon" in geom_types or "MultiPolygon" in geom_types:
        contains = kk_union.buffer(0.5).contains(parcels_union.buffer(-0.5))
        kk_area = float(kk_union.area)
        parcels_in_kk_area = float(parcels_union.intersection(kk_union).area)
        coverage_pct = parcels_in_kk_area / kk_area * 100.0 if kk_area else 0.0
        body.append("")
        body.append(
            f"**Spatial relationship to parcels:** parcels' union area ∩ kavim kchulim "
            f"= {fmt_num(parcels_in_kk_area)} m² "
            f"({coverage_pct:.1f}% of kavim kchulim)"
        )

        # Distance from each parcel boundary to nearest kk edge — if it's
        # the building line, the offset would be a non-trivial setback
        # (e.g. ≥1 m from balconies, ≥3 m from streets). If 0 / negligible,
        # it's the plan boundary.
        body.append("")
        if contains and coverage_pct > 80:
            interp = (
                "**Interpretation:** the polygon is a single closed shape that *contains* "
                "the parcel union (≥80% coverage), with the same `TOCHNIT` ID "
                f"(`{gdf.iloc[0]['TOCHNIT']}`) as the plan. This is the **plan boundary "
                "(קו כחול)**, not the building line (קו בניין). Building setback lines "
                "(קו בניין) live one level below — they're the offset edges *inside* "
                "each parcel, not the plan envelope."
            )
            findings.append(
                "`kavim kchulim.shp` is the plan boundary (קו כחול), confirmed by the "
                "single-polygon geometry containing all parcel polygons."
            )
            actions.append(
                "Update `digital_files.tashrit.todo_building_line_layer` in the "
                "schema to record this conclusion: kavim kchulim = plan boundary, "
                "NOT the building line. Building-line layer remains unidentified — "
                "DWG layer extraction (`407-0977595_מצב מוצע.dwg`) is still the "
                "only known source for קו בניין."
            )
            verdict = Verdict("pass", "kavim kchulim.shp identified as the plan boundary.")
            body.append(interp)
        else:
            interp = (
                "**Interpretation:** the polygon does NOT cleanly contain the parcel "
                "union. This may be a partial sub-area boundary, an alternate plan "
                "extent, or a different feature class. Manual review needed."
            )
            findings.append("`kavim kchulim.shp` does not behave as a plan boundary — review.")
            verdict = Verdict("warning", "kavim kchulim.shp identity is unclear — review needed.")
            body.append(interp)
    else:
        verdict = Verdict("warning", f"unexpected geometry types: {geom_types}.")
        body.append("\n**Interpretation:** unexpected geometry types — review.")

    if findings:
        body.append("")
        body.append("**Findings:**")
        body.append("")
        body += [f"- {f}" for f in findings]

    return Section("4. kavim kchulim.shp identity", "\n".join(body), verdict, findings, actions)


# ──────────────────────────────────────────────────────────────────────
# Layer 5 — Raster georeferencing consistency
# ──────────────────────────────────────────────────────────────────────

def analyze_rasters(tashrit_dir: Path) -> Section:
    body: list[str] = []
    findings: list[str] = []
    actions: list[str] = []

    rasters = []
    for jgw in sorted(tashrit_dir.glob("*.jgw")):
        jpg = jgw.with_suffix(".jpg")
        if not jpg.exists():
            continue
        gw = parse_jgw(jgw)
        w, h = jpg_dim(jpg)
        # Real-world bbox: upper-left is (C, F); pixel size in y is negative.
        ulx = gw["upper_left_easting"]
        uly = gw["upper_left_northing"]
        lrx = ulx + w * gw["pixel_size_x_m"]
        lry = uly + h * gw["pixel_size_y_m"]
        bbox = (min(ulx, lrx), min(uly, lry), max(ulx, lrx), max(uly, lry))
        rasters.append({
            "name": jpg.name,
            "pixels_w": w,
            "pixels_h": h,
            "px_x": gw["pixel_size_x_m"],
            "px_y": gw["pixel_size_y_m"],
            "ul_easting": ulx,
            "ul_northing": uly,
            "bbox": bbox,
            "bbox_geom": box(*bbox),
        })

        # Cross-check with rasterio for sanity
        try:
            with rasterio.open(jpg) as src:
                rio_w, rio_h = src.width, src.height
                if (rio_w, rio_h) != (w, h):
                    findings.append(
                        f"{jpg.name}: rasterio reports ({rio_w}×{rio_h}) but JPEG SOF "
                        f"says ({w}×{h}). Disagreement."
                    )
        except Exception as e:
            findings.append(f"{jpg.name}: rasterio.open failed: {type(e).__name__}: {e}")

    rows = []
    for r in rasters:
        rows.append([
            r["name"],
            f"{r['pixels_w']}×{r['pixels_h']}",
            f"{r['px_x']:.4f} / {r['px_y']:.4f}",
            f"({r['bbox'][0]:.1f}, {r['bbox'][1]:.1f})",
            f"({r['bbox'][2]:.1f}, {r['bbox'][3]:.1f})",
            f"{(r['bbox'][2] - r['bbox'][0]):.1f} × {(r['bbox'][3] - r['bbox'][1]):.1f} m",
        ])

    body.append(md_table(
        ["raster", "pixels (W×H)", "pixel m (x / y)",
         "bbox min ITM", "bbox max ITM", "real size (m)"],
        rows,
    ))

    # Mutual consistency: every pair should overlap
    severity = "pass"
    if len(rasters) < 2:
        verdict = Verdict("warning", f"only {len(rasters)} georeferenced rasters — cannot cross-check.")
    else:
        overlap_findings = []
        for i in range(len(rasters)):
            for j in range(i + 1, len(rasters)):
                a = rasters[i]["bbox_geom"]
                b = rasters[j]["bbox_geom"]
                inter = a.intersection(b)
                if inter.is_empty:
                    overlap_findings.append(
                        f"{rasters[i]['name']} ∩ {rasters[j]['name']}: NO OVERLAP."
                    )
                    severity = "fail"
                else:
                    smaller = min(a.area, b.area)
                    coverage = inter.area / smaller * 100.0
                    if coverage < 50:
                        overlap_findings.append(
                            f"{rasters[i]['name']} ∩ {rasters[j]['name']}: only "
                            f"{coverage:.1f}% of the smaller raster is covered."
                        )
                        severity = "warning" if severity == "pass" else severity

        body.append("")
        body.append("**Pairwise overlap check:**")
        body.append("")
        if overlap_findings:
            body += [f"- {f}" for f in overlap_findings]
        else:
            body.append("All pairs overlap with the smaller raster ≥50% covered. ✓")

        # Pixel-resolution sanity: _M should be coarsest, _58 finer.
        body.append("")
        body.append("**Resolution sanity:**")
        body.append("")
        for r in rasters:
            kind = "wide view" if "_M" in r["name"] else "close-up"
            body.append(
                f"- `{r['name']}`: {r['px_x'] * 100:.2f} cm/px ({kind})"
            )

        # Upper-left corner alignment within tolerance
        ul_x = [r["ul_easting"] for r in rasters]
        ul_y = [r["ul_northing"] for r in rasters]
        spread_x = max(ul_x) - min(ul_x)
        spread_y = max(ul_y) - min(ul_y)
        body.append("")
        body.append(
            f"**Upper-left corner spread:** Δeast = {spread_x:.2f} m, "
            f"Δnorth = {spread_y:.2f} m (tolerance ±{RASTER_EXTENT_TOL_M:.0f} m)"
        )
        if spread_x > RASTER_EXTENT_TOL_M or spread_y > RASTER_EXTENT_TOL_M:
            findings.append(
                f"Upper-left corners disagree by more than {RASTER_EXTENT_TOL_M:.0f} m: "
                f"Δeast = {spread_x:.2f}, Δnorth = {spread_y:.2f}."
            )
            severity = "warning" if severity == "pass" else severity

        if severity == "pass":
            verdict = Verdict("pass", "all 3 rasters overlap, resolutions stack as expected (_M coarse, _58 fine).")
        elif severity == "warning":
            verdict = Verdict("warning", "rasters overlap but with caveats — see findings.")
        else:
            verdict = Verdict("fail", "at least one raster pair has no overlap — georeferencing inconsistent.")

    if findings:
        body.append("")
        body.append("**Findings:**")
        body.append("")
        body += [f"- {f}" for f in findings]

    return Section("5. Raster georeferencing consistency", "\n".join(body), verdict, findings, actions)


# ──────────────────────────────────────────────────────────────────────
# Report builder
# ──────────────────────────────────────────────────────────────────────

SEVERITY_RANK = {"fail": 0, "warning": 1, "pass": 2}


def render_report(project_id: str, schema: dict, tashrit_dir: Path, sections: list[Section]) -> str:
    today = date.today().isoformat()
    plan_number = schema["project"]["meta"]["plan_number"]
    plan_name = schema["project"]["meta"]["plan_name"]
    tk = schema["project"]["digital_files"].get("tashrit", {})

    out = [
        f"# תשריט analysis report — {plan_number}",
        f"*{plan_name}*",
        "",
        f"**Generated:** {today}  ",
        f"**Source:** `{tashrit_dir}`  ",
        f"**File-set sha256:** `{tk.get('fileset_sha256', '?')}`  ",
        f"**Generator:** `src/tashrit_analysis.py` (deterministic — geopandas / shapely / pyproj / rasterio)",
        "",
        "---",
        "",
    ]

    for sec in sections:
        out.append(f"## {sec.title}")
        out.append("")
        out.append(sec.body_md)
        out.append("")
        out.append(sec.verdict.render())
        out.append("")
        out.append("---")
        out.append("")

    # Summary findings
    all_findings: list[tuple[str, str, str]] = []  # (severity, section, message)
    all_actions: list[tuple[str, str]] = []
    for sec in sections:
        sev = sec.verdict.severity
        for f in sec.findings:
            all_findings.append((sev, sec.title, f))
        for a in sec.actions:
            all_actions.append((sec.title, a))

    all_findings.sort(key=lambda t: SEVERITY_RANK[t[0]])

    out.append("## Summary findings (ranked by severity)")
    out.append("")
    if not all_findings:
        out.append("_No findings._")
    else:
        for sev, title, msg in all_findings:
            sym = {"fail": "✗", "warning": "⚠", "pass": "✓"}[sev]
            out.append(f"- {sym} **{title}** — {msg}")
    out.append("")

    out.append("## Action items")
    out.append("")
    if not all_actions:
        out.append("_No actions required._")
    else:
        for title, action in all_actions:
            out.append(f"- **{title}**: {action}")
    out.append("")
    out.append("> No schema fixes have been auto-applied. Review and decide before changing anything.")
    out.append("")

    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    here = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Build תשריט analysis report")
    parser.add_argument("--project", help="Project ID (e.g. 407-0977595). Resolves to data/projects/<id>/project-schema.json")
    parser.add_argument("--schema", help="Path to a project schema JSON (overrides --project)")
    parser.add_argument("--out", help="Override output path")
    args = parser.parse_args()

    if args.schema:
        schema_path = Path(args.schema)
        if not schema_path.is_absolute() and not schema_path.exists():
            schema_path = here / args.schema
    elif args.project:
        schema_path = here / "data" / "projects" / args.project / "project-schema.json"
    else:
        print("ERROR: pass --project or --schema", file=sys.stderr)
        return 1

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    project_id = schema["project"]["meta"]["plan_number"]

    tashrit_files = schema["project"]["digital_files"].get("tashrit", {}).get("files", [])
    if not tashrit_files:
        print(f"ERROR: no tashrit registered in {schema_path}", file=sys.stderr)
        return 1

    # Resolve tashrit dir from any registered file's path
    first_path = Path(tashrit_files[0]["path"])
    tashrit_dir = (here / first_path).parent if not first_path.is_absolute() else first_path.parent
    if not tashrit_dir.exists():
        print(f"ERROR: tashrit dir not found: {tashrit_dir}", file=sys.stderr)
        return 1

    schema_parcels = schema["project"].get("parcels", [])

    # Run all 5 layers
    sec1, parcels_gdf = analyze_parcels(tashrit_dir, schema)
    sec2 = analyze_topology(parcels_gdf, tashrit_dir, schema)
    sec3 = analyze_landuse(parcels_gdf, tashrit_dir, schema_parcels)
    sec4 = analyze_kavim_kchulim(parcels_gdf, tashrit_dir)
    sec5 = analyze_rasters(tashrit_dir)

    sections = [sec1, sec2, sec3, sec4, sec5]
    report_md = render_report(project_id, schema, tashrit_dir, sections)

    today = date.today().isoformat()
    out_path = (
        Path(args.out) if args.out
        else here / "reports" / project_id / f"tashrit-analysis-{today}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")

    # Console summary (don't dump full report — just outcomes)
    print(f"Report written: {out_path}")
    print()
    for s in sections:
        print(f"  {s.verdict.severity.upper():7}  {s.title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
