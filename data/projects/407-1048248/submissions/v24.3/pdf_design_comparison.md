# PDF Design Comparison — v6 reference vs newly-generated audit_report_24.3.pdf

**Date:** 2026-05-24
**Investigator:** Claude Code (visual diff via 150 DPI rasters)
**Reference PDF:** `/Users/liorlevin/Downloads/v6_design_reference.pdf` (55 KB, 6 pages, dated 2026-05-17 08:35)
**New PDF:** `/Users/liorlevin/Desktop/planning-platform/audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf` (272 KB, 35 pages, generated 2026-05-24 06:52)
**Engine baseline:** byte-identical to `tests/regression/v8j_baseline_v24.3.json` ⇒ regression is in the **PDF generator**, not the engine.

---

## Headline finding

**RTL is NOT regressed.** Hebrew body text, table cells, headings, and footers all read right-to-left correctly in both PDFs. The complaint "not right-aligned" appears to point at something visually different — and what's actually different is a **complete design divergence** between the inline CSS in `report_generator.py` and the v6 reference Lior is comparing against. The code was lifted from a **later iteration** of the v6 design (`v6_design_reference (2).html`, 2026-05-17 13:49) that has a heavier, darker visual treatment, while Lior's "reference" is the **first iteration** (`v6_design_reference.html`, 2026-05-17 08:35) with a minimalist white treatment.

---

## Sample image references

All rasters at 150 DPI in `/tmp/pdf_compare/`:

| Page concept | v6 reference | New PDF |
|---|---|---|
| Cover | `v6_ref_p01.png` | `new_p01.png` |
| TOC | `v6_ref_p02.png` | `new_p02.png` |
| Section 2 opener (verdict counts) | `v6_ref_p03.png` (top half) | `new_p05.png` |
| תא שטח 1 table | `v6_ref_p03.png` (bottom) | `new_p06.png` |
| Section 1 intro + Summary | `v6_ref_p05.png` | `new_p29.png` |
| Appendix A | `v6_ref_p06.png` | `new_p35.png` (table only — no divider) |

---

## RTL+Design checkpoint comparison (10 rows)

| # | Checkpoint | v6 reference | New PDF | Verdict |
|---|---|---|---|---|
| RTL | Text right-aligned, table column flow R→L, margins from correct side | ✓ Hebrew flows R→L; tables: rightmost = first column | ✓ Hebrew flows R→L; tables: rightmost = first column | ✓ **MATCHES** (not regressed) |
| 1 | Cover — NZC branding, plan #/version, draft watermark | White background, centered title, eyebrow "המינהלת להתחדשות עירונית — עיריית נס ציונה", subtitle "מתחם הטייסים-ההסתדרות", small inline-text watermark | **Dark green** full-bleed background, title positioned mid-right, eyebrow text partially **clipped behind absolute-positioned logo**, watermark as **pill-styled button**, NZC/מינהלת label split across two text lines | ✗ **REGRESSED** (visual theme + clipping) |
| 2 | TOC — table format with section + sub numbering | Compact 1-page table, number column "1./2./3./4." styled as bullets, page #'s left, all on one page | Wide spaced rows with dotted separators, numbers inline with title not in a column, runs across 2 pages | ⚠ **DIFFERENT** (structurally similar, denser spacing in new) |
| 3 | 4-section structure (Urban / Content / Multidisciplinary / Summary) | ✓ Sec 1 (p5), 2 (p3), 3 (p4), 4 (p5) | ✓ Sec 1 (p4), 2 (p5), 3 (p18), 4 (p29) | ✓ **MATCHES** |
| 4 | Appendix A — Format issues section | ✓ Separate divider page "נספח א" with letter-spaced characters + intro line; format issues follow | ✗ **No divider page**. Format-issues content appears as numbered sub-sections (e.g. "סעיף 6.10 (4 ליקויים)") embedded in the body; appendix concept lost | ✗ **REGRESSED** (missing divider) |
| 5 | Verdict counts at section openers — תקינים / ליקויים / דורשים בירור | 5 cards: 0 תקינים / 39 ליקויים / 11 דורשים בירור / 0 לא ניתנים / 29 לא רלוונטיים | 5 cards on §2 (15/27/11/0/26), 4 cards on §3 (9/8/16/0 — missing "לא רלוונטיים"), 3 cards on §4 (24/35/27) | ⚠ **INCONSISTENT** (card count varies by section) |
| 6 | Per-תא-שטח tables — columns: נושא בדיקה / ממצא / בהגשה / בתב"ע / הערה | 5 columns: **נושא בדיקה / ממצא / בהגשה / בתב"ע / הערה** | 5 columns: **נושא בדיקה / ממצא / בתוכנית עיצוב / בתב"ע / הערה** — column #3 renamed "בהגשה" → "בתוכנית עיצוב" | ⚠ **DIFFERENT** (column 3 label changed) |
| 7 | Action items — numbered list with grouped cross-תא-שטח actions in summary | ✓ Numbered "1./2./3." with bold lead-in + plot list (e.g. "**כמות יח"ד — תא שטח 1, 2, 3, 4, 5.**") | ✓ Same pattern: numbered 1-5, bold lead, cross-plot grouping ("**שטח עיקרי (מ"ר) — תא שטח 1, תא שטח 2, ...**") | ✓ **MATCHES** |
| 8 | Footer — "מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב N/M" | "6 / 2 ... מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב · עמ' 2" | "35 / 2 ... מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב" (**no "· עמ' N" suffix**) | ⚠ **DIFFERENT** (lost "עמ'" prefix) |
| 9 | Brand color — NZC green (#005030 primary, #007840) | Used as accent for titles, banner borders, status badges; on **white background** | Same hex tokens applied; cover uses **#005030 as full background** (white text on green) | ⚠ **DIFFERENT** (color tokens same, application changed) |

**Aggregate:** 1 ✓ RTL + 2 ✓ matches + 5 ⚠ different + 2 ✗ regressed.

---

## Git archaeology

- **Only commit touching `compliance_engine/`:** `f50765e` ("Phase 1 + 2a + 2b baseline (2026-05-19, pre-versioning)") — a single bulk commit. No incremental history of RTL fixes; the entire engine + report generator landed as one tree.
- **RTL declarations in current code:**
  - `compliance_engine/report_generator.py:91` — `html { direction: rtl; }`
  - `compliance_engine/report_generator.py:93` — `body { direction: rtl; ... }`
  - `compliance_engine/report_generator.py:392` — `table { direction: rtl; ... }`
  - `compliance_engine/report_generator.py:571` — `<html lang="he" dir="rtl">`
- **Dead code paths discovered:** `compliance_engine/templates/audit_report.css` and `compliance_engine/templates/audit_report.html.jinja` exist but are **never imported or used**. The generator builds HTML by string concatenation inside `_render_*` functions and uses a Python-inline `_CSS` constant (line 80). The templates directory is leftover scaffolding.
- **Source-of-truth for the CSS:** `report_generator.py:3` says CSS was "**lifted verbatim from `v6_design_reference (2).html`**". That file is the 13:49 iteration (dark-green cover). Lior's reference PDF is from the 8:35 iteration (white cover). The code matches a different snapshot than the reference.

---

## Root cause diagnosis

1. **No RTL regression exists.** `direction: rtl` is declared at `<html>`, `body`, and `table` level; `dir="rtl"` is set on `<html>`; Hebrew text reads R→L correctly in every page sampled. The reported "not right-aligned" complaint is **really a complaint about visual difference from the v6 reference**, not an RTL CSS bug.

2. **Design version mismatch.** The inline CSS in `report_generator.py` was copied from `v6_design_reference (2).html` (2nd iteration of the design), but Lior is comparing against `v6_design_reference.pdf` (1st iteration). The 2nd iteration's design choices that diverge from the 1st:
   - Full-bleed dark green cover (`background: #005030` on `.cover`, line 162) instead of white
   - `min-width: 36mm` on `.cover .data-block .label` (line 216) causing labels and values to spread wide instead of clustering centered
   - Absolute-positioned logo at `right: 22mm` (line 173) that overlaps the start of the brand-eyebrow text in RTL
   - Larger title (`42pt`, line 194) vs the more restrained reference

3. **Structural regression: Appendix A divider missing.** v6 had a dedicated divider page with letter-spaced "נ ס פ ח א" + intro. New PDF jumps straight into numbered format-issue tables ("סעיף 6.10") with no visual break. This breaks checkpoint #4.

4. **Inconsistencies:** Verdict-card count varies by section (5/4/3); column label "בהגשה" → "בתוכנית עיצוב"; footer dropped "עמ' N" suffix. None of these are RTL.

---

## Proposed fixes (NOT applied — awaiting Lior's approval)

These are the targeted changes that would restore the v6 reference look while keeping the engine output byte-identical. **All changes are in `compliance_engine/report_generator.py` — no template/CSS file edits needed (those files are dead code).**

### Fix A — Restore minimalist white cover (highest priority, what Lior actually sees)

`report_generator.py:160-235` — `.cover` and `.cover .*` rules:
- Remove `background: #005030;` from `.cover` (line 162) → white background
- Recolor all `.cover` text from `#fff` / `rgba(255,255,255,*)` back to `#005030` for titles and dark grays for body
- Remove `min-width: 36mm` from `.cover .data-block .label` (line 216) → labels cluster with values
- Reposition `.cover .logo` from absolute-top-right to inline above title (avoids text-overlap clipping)
- Change `.title` from `42pt` to ~`30pt` and center it
- Remove the green-pill watermark; restore inline text watermark "טיוטה לסקירה — לא לחתימה"

### Fix B — Add Appendix A divider page

`report_generator.py:566` already calls `_render_appendix_divider()` and `_render_appendix_detail()` separately. Check `_render_appendix_divider` body — it likely exists but produces empty/invisible output or got stubbed. Restore the letter-spaced "נ ס פ ח א" page styled per `@page appendix-divider` (line 128, currently only strips footer).

### Fix C — Verdict-card consistency

`_render_section_2`, `_render_section_3`, `_render_section_4` each compute card sets differently. Standardize on 5-card layout (תקינים / ליקויים / דורשים בירור / לא ניתנים / לא רלוונטיים) and pass 0 when a bucket doesn't apply.

### Fix D — Restore "עמ'" prefix in footer

`@bottom-left` declaration in `@page` rule (probably around lines 95-122). Change current `counter(page) " / " counter(pages)` to include "· עמ' " segment.

### Fix E — Verify column label "בהגשה" vs "בתוכנית עיצוב"

This may be intentional — confirm with Lior which terminology is preferred. If "בהגשה", change in `_content_table_html` (line ~858).

### Fix F — Clean up dead template files

After fixes land, delete `compliance_engine/templates/audit_report.css` and `compliance_engine/templates/audit_report.html.jinja` (unused). Or, alternatively, refactor the inline `_CSS` + `_render_*` back to those template files so future edits live in CSS/Jinja instead of Python string concatenation. Bigger change, recommended only as a follow-up after the visual fix lands.

---

## Recommendation

The user perceives "RTL is broken" but the actual issue is a **theme/design mismatch** with the v6 reference PDF. Recommend applying **Fix A + Fix B** as the highest-value pair (restores the cover Lior expects + fixes the appendix structural regression). Fixes C/D/E are polish. Fix F is post-launch hygiene.

Estimated effort: A + B together ≈ 30-45 min of CSS editing + visual verification cycle (render → rasterize → compare to v6_ref_p01.png/p06.png → iterate).

**Awaiting Lior's go before touching `report_generator.py`.**
