# Claude Code — Start Here
## Planning Compliance Platform for Ness Ziona Urban Renewal Authority

---

## Your First Task

Read these four files before writing a single line of code:

1. `SKILL.md` — domain knowledge, Hebrew terms, what the system does
2. `CONTEXT.md` — all architectural decisions (DB schema, versioning, evidence model)
3. `project-schema-407-0977595-v2.json` — the pilot project's full data (rules, plots, geometry)
4. `project-template-blank.json` — blank template for future projects

Then build Phase 0 and Phase 1 as described below.

---

## What to Build First

### Phase 0 — Project Loader (1 day)

Build a script that loads `project-schema-407-0977595-v2.json` into a SQLite database.

```
python load_project.py --schema project-schema-407-0977595-v2.json
```

This should:
1. Create the SQLite database using the schema in `CONTEXT.md` (all tables)
2. Insert one row into `projects` for plan 407-0977595
3. Insert one row into `takanon_versions` (version: 'approved_2024-01-23')
4. Insert all 31 rules from the JSON into the `rules` table
5. Print a summary: "Loaded project 407-0977595: 4 plots, 31 rules"

**Definition of done:** Running `python load_project.py` produces a `planning.db` SQLite file with all data correctly loaded and queryable.

---

### Phase 1 — PDF Parser (2–3 days)

Build a script that extracts compliance data from the Kika Braz תכנית עיצוב PDF.

```
python parse_pdf.py --pdf "תכנית_עיצוב_הטייסים_23_3.pdf" --project 407-0977595
```

**What to extract:**

1. **Parking table** (page 29 of the PDF):
   - Use PyMuPDF to find the page containing both 'מרתף עליון' and 'מרתף טיפוסי'
   - Use pdfplumber to extract the table with `vertical_strategy="lines"`, `horizontal_strategy="lines"`
   - Forward-fill vertically merged cells (plot ID column)
   - Extract per plot: residential_parking, visitor_parking, accessible_parking, motorcycles, levels, total

2. **Plan scale** (from title block):
   - Search all site plan pages for scale text: '1:250', '1:500', '1:750'
   - Return the detected scale

3. **Unit mix** (from קומה טיפוסית pages):
   - Extract total unit count per תא שטח

4. **Document presence** (scan all pages):
   - Is there a page with 'רת"א' or 'רשות התעופה'? → rta_approval: true/false
   - Is there a stormwater/hydraulics report attached? → stormwater_report: true/false

**Output format — store in `extracts` table and also print as JSON:**

```json
{
  "engine_run_id": "...",
  "extracts": [
    {
      "rule_code": "SCALE_REQUIRED_1250",
      "plot": "all",
      "extracted_value": null,
      "extracted_text": "1:500",
      "confidence": 0.95,
      "evidence": {
        "source_file": "תכנית_עיצוב_הטייסים.pdf",
        "page": 10,
        "region": "title_block",
        "bbox": [120.5, 340.2, 480.8, 380.1],
        "excerpt": "קנ\"מ 1:500",
        "method": "pdfplumber",
        "confidence": 0.95,
        "reviewed_by": null
      },
      "review_required": false,
      "review_reason": null
    }
  ]
}
```

**Definition of done:**
- Parking table extracted correctly: plot_1 = 232 residential, 23 visitor, 2 accessible, 4 levels
- Scale detected as "1:500" (this IS a violation — that's correct, the reference submission fails this rule)
- rta_approval: false (correct — letter not attached)
- stormwater_report: false (correct — not attached)
- All extracts stored in SQLite `extracts` table

---

## After Phase 0 and Phase 1 Are Done

**Phase 2 — Rules Engine:** Load rules from DB, load extracts from DB, compare, generate violations list.

**Phase 3 — חוות דעת Generator:** Take violations list, generate Hebrew RTL PDF using WeasyPrint. Use the brand colors: primary=#005030, green=#007840.

**Phase 4 — ממ"ג Package Reader:** Read the standard מנהל התכנון ZIP package (ממ"ג). Each package contains ESRI shapefiles (`.shp`/`.dbf`/`.shx`) with parcel polygons in **ITM (EPSG:2039)** coordinates, plus georeferenced JPGs accompanied by `.jgw` worldfiles. The ממ"ג is the **authoritative source for parcel boundaries** — use it in preference to DWG layer extraction. Use `geopandas` for the shapefile reads (reproject ITM → WGS84 for cross-checking against KML / scope geometry) and `rasterio` for the worldfile-georeferenced JPGs. Persist parcel polygons to the project's geometry store, tagged with provenance `source = 'mamag'` so the engine can prefer ממ"ג polygons over DWG-derived ones.

**Do not start Phase 2 until Phase 1 output is validated against the known values above.**

---

## Project Structure to Create

```
/planning-platform/
  ├── data/
  │   ├── projects/
  │   │   └── 407-0977595/
  │   │       ├── project-schema.json      (copy of the schema)
  │   │       └── submissions/             (PDFs/DWGs go here)
  │   └── planning.db                      (SQLite database)
  ├── src/
  │   ├── load_project.py                  (Phase 0)
  │   ├── parse_pdf.py                     (Phase 1)
  │   ├── compliance_engine.py             (Phase 2)
  │   └── generate_chavat_daat.py          (Phase 3)
  ├── templates/
  │   └── chavat_daat.html                 (WeasyPrint template)
  ├── tests/
  │   └── test_phase1.py                   (known values as assertions)
  ├── CONTEXT.md
  ├── SKILL.md
  └── README.md
```

---

## Key Rules While Building

1. **Never hard-code rules** — always load from `rules` table filtered by `project_id`
2. **Every extract needs an evidence bundle** — `bbox`, `page`, `excerpt`, `method`, `confidence`
3. **Confidence < 0.80 → set `review_required = true`**
4. **Use the 7 verdict states** — not binary pass/fail. See CONTEXT.md for the full list.
5. **Do not call Claude API** for Phase 0, 1, or 2. Pure Python only.
6. **Hebrew text direction** — all generated documents are RTL. WeasyPrint handles this with `direction: rtl` in CSS.
7. **The 6 known violations** — your Phase 2 output must detect all 6 listed in the schema `notes.known_violations_in_reference_submission`
8. **Rule baseline** — Phase 2 evaluates against all 31 rules from `compliance_rules[]` in the v2 schema (17 numeric, 5 geometric, 5 document_presence, 4 procedural)

---

## Install These First

```bash
pip install fastapi uvicorn pymupdf pdfplumber shapely geopandas ezdxf weasyprint python-dotenv
```

**Phase 4 adds (ממ"ג packages):**

```bash
pip install rasterio
```

`geopandas` is already in the base install — Phase 4 will use it to read the ESRI shapefiles in the ממ"ג ZIP (parcel polygons in ITM / EPSG:2039) and `rasterio` to read the worldfile-georeferenced JPGs (`.jgw`). Reproject ITM → WGS84 when cross-checking against the KML boundary.

For SQLite in Python — use the built-in `sqlite3` module. No extra install needed.

---

## Questions? Ask Before Coding

If anything in the schema or CONTEXT.md is unclear — ask. Do not guess at rule interpretation. These rules have legal weight.
