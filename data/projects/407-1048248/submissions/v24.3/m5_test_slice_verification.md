# M5 Test Slice Verification — v24.3

**Milestone:** M5 (polish + transparency)
**Project:** 407-1048248 (תוכנית עיצוב הטייסים-ההסתדרות)
**Submission:** v24.3
**Date:** 2026-05-24
**Status:** Awaiting Lior's PDF review before lock

---

## Scope

Four-component M5 pass on top of locked M4:

| Comp | Description |
|------|-------------|
| A | Flash-driven English→Hebrew translation for M2/M3 reasoning |
| B | New PDF Section 5 — "היקף הבדיקה האוטומטית" coverage transparency |
| C | TOC update — adds section 2א + Section 5 entries |
| D | Task #32 fix — hedged-pass verdict escalation to `requires_review` |
| E | Re-run M4 → regenerate PDF |
| F | Self-verify (this doc) |
| G | Report + STOP — Lior reviews before lock |

---

## Component A — Hebrew Translation Pass

**Module:** `vision_scanner/m4/translator_hebrew.py` (NEW, 220 LOC)

- Detects English-predominant snippets (≥30% Latin chars among alphabetic + ≥4 Latin chars)
- Batches via Gemini 2.5 Flash with planning-Hebrew system prompt
- Resilient: on `DeadlineExceeded` (504), splits batch in half (up to 2 recursive splits), then falls back to `[translation_failed]` marker
- Deduplicates identical English strings before calling Flash
- Originals preserved on the finding under `_original_notes_en` / `_original_reasoning_en` so the audit trail stays inspectable

**Wiring:** `vision_scanner/m4/processor.py::_apply_hebrew_translation()` runs at the tail of `build_m4_document`, traversing in-engine `notes_he` (paragraph-split on `\n\n`) and sidecar `reasoning`. Toggleable via `build_m4_document(..., translate_hebrew=True)` and `--no-translate` CLI flag.

**Actual translation work on v24.3:**

- In-engine `notes_he`: **0 English-predominant paragraphs** (M2 already emits Hebrew in this codepath)
- Sidecar reasoning: **6 English snippets → 6 unique Flash translations**
- Leftover English-dominant paragraphs in final document: **0** ✓

**Sample translations** (English original → planning-Hebrew output):

| Clause | English (original) | Hebrew (Flash) |
|--------|--------------------|----------------|
| 6.5.1 | "The clause explicitly states that a 'Mature Trees Appendix' (נספח עצים בוגרים) is attached to the plan. A review of the 63-page submission, including the table of contents on page 2, confirms that this appendix is missing." | "הסעיף קובע במפורש כי 'נספח עצים בוגרים' מצורף לתכנית. בבדיקת התכנית שהוגשה, הכוללת 63 עמודים, וכן בבחינת תוכן העניינים בעמ' 2, עולה כי נספח זה חסר." |
| 6.6.4 | "The clause specifically requires an underground easement for vehicle passage from plot 2 to the adjacent plot 12. The basement plan for plot 2 (page 37) and the corresponding site plan (page 34) do not show any ramp, tunnel, or other provision for such a connection." | "הסעיף דורש במפורש זיקת הנאה תת-קרקעית למעבר רכב מתא שטח 2 לתא שטח 12 הסמוך. בתשריט המרתף עבור תא שטח 2 (עמ' 37) ובתשריט הבינוי המקביל (עמ' 34) לא מוצגים רמפה, מנהרה או כל הוראה אחרת לחיבור כאמור." |
| 7.1.1 | "The submission is a design plan and does not include a construction phasing plan as described in the takanon. While pages 12 and 14 mention phasing for the public open space (שצ\"פ), it does not cover the full scope of the takanon's phasing requirements for all plots." | "ההגשה הינה תכנית בינוי ופיתוח ואינה כוללת תכנית שלביות ביצוע כנדרש בתקנון. אף שעמודים 12 ו-14 מתייחסים לשלביות עבור השצ\"פ, אין בכך כדי לכסות את מלוא היקף דרישות השלביות של התקנון עבור כלל תאי השטח." |
| 6.4.2 | "The takanon requires a total retention volume of 450 m³. The 63-page submission does not include a drainage appendix, calculations, or summary table to verify this requirement." | "התקנון דורש נפח השהיה כולל של 450 מ\"ק. ההגשה בת 63 העמודים אינה כוללת נספח ניקוז, חישובים או טבלת סיכום לאימות דרישה זו." |
| 4.2.2.4 | "The clause pertains to a pedestrian passage in Takanon plot 9. The submission documents do not contain any plans or information for plot 9." | "הסעיף מתייחס למעבר הולכי רגל בתא שטח 9 על פי התקנון. מסמכי ההגשה אינם כוללים תשריטים או מידע כלשהו עבור תא שטח 9." |

**Quality notes:** Flash output uses professional planning vocabulary throughout — `זיקת הנאה`, `תשריט המרתף`, `תכנית שלביות ביצוע`, `נפח השהיה`, `שצ"פ`, `התקנון` are all used correctly without literal-translation tells. No `[translation_failed]` markers present. **Approved for visual review.**

**Cost:** Single Flash call (one batch of 6 unique snippets) — well below the $0.05-0.10 budget estimate.

---

## Component B — Section 5 Coverage Transparency

**Modules:**
- `vision_scanner/m5/coverage_assembler.py` (NEW, ~290 LOC) — emits `coverage_report.json`
- `compliance_engine/report_generator.py` (MODIFIED) — renders Section 5 between Section 4 and the appendix

**Subsections rendered** (verified visually on pages 34–44 of the new PDF):

| § | Title | What it shows |
|---|-------|---------------|
| 5.1 | קטגוריות בכיסוי מלא | 7 categories — green-header table |
| 5.2 | קטגוריות בכיסוי חלקי | 4 categories — green-header table |
| 5.3 | קטגוריות שלא נבדקו אוטומטית — דורש בדיקה ידנית | 2 explicit categories + **6 amber gap-cards** (מעונות יום, זיקות הנאה, שלביות ביצוע, שטחי בנייה לפי שימוש, תאי שטח 6-10/20, פירוט תמהיל דירות) |
| 5.4 | פירוט כיסוי לפי עמוד | 63-row per-page table (page → page type → coverage tier FULL/PARTIAL/UNADDRESSED) |
| 5.5 | הסתייגות מקצועית | Disclaimer paragraph clarifying that automation covers the *checkable* parts; categories outside scope require Ellen's manual review |

**Data source:** `data/projects/407-1048248/submissions/v24.3/coverage_report.json` (19 KB) generated by the new CLI:
```
python3 -m vision_scanner.m5.coverage_assembler \
    --project-id 407-1048248 --submission-id v24.3 \
    --output data/projects/407-1048248/submissions/v24.3/coverage_report.json
```

**Renderer detection:** `_load_coverage_report(pdf_output_path)` walks up from the PDF target to find the matching `coverage_report.json` in the project data directory. Falls back gracefully if missing — section 5 simply omitted.

---

## Component C — TOC Update

`_render_toc()` now accepts `has_sidecar` and `has_section_5` kwargs.

**Verified on PDF page 2:**
- ✓ `2א. ממצאי בדיקה ויזואלית נוספים` → page 18
- ✓ `5. היקף הבדיקה האוטומטית` → page 34 (with 5.1–5.5 sub-entries)

---

## Component D — Task #32 Hedged-Pass Escalation

**Problem:** Engine emitted `verdict=pass, confidence=MEDIUM` for `CONTENT_PARKING_RATIO` on plots 1-5, but the underlying `notes_he` openly admitted partial verification (e.g., *"תקין על בדיקה ראשונית"*, *"לא ניתן לאמת ללא טבלת חניות פר תא שטח"*). Marking those rows "תקין" was misleading.

**Fix:** New override source `hedged_reasoning_escalation` in `vision_scanner/m4/schema.py`.

**Logic** (`processor.py::escalate_hedged_pass_verdicts`):
- Runs **before** any M2/M3 overrides
- If verdict in `{pass, pass_with_note}` AND notes match any of `HEDGED_REASONING_MARKERS` (`ראשונית`, `לא ניתן לאמת`, `דורש טבלת`, `אינו כולל`, `נדרשת השלמה`, `לא קיימת בהגשה`, `preliminary`, `cannot be verified`) → flip to `requires_review` with prefix `[הסלמה אוטומטית — Task #32]`
- **Sticky:** once escalated, downstream M2 overrides can only *annotate*, never flip the verdict back to pass (preserves Task #32 intent)
- Validator check #9 enforces no `hedged_reasoning_escalation` row shows verdict `pass`

**Result on v24.3:**
- **5 findings escalated**: `CONTENT_PARKING_RATIO` on plot_1 / plot_2 / plot_3 / plot_4 / plot_5
- All show "דורש בירור" (requires_review) in the per-plot tables on PDF pages 7, 9, 11, 13, 15
- Plots 6, 7, 8, 10 (which already had M2 `not_submitted` overrides for "missing per-plot parking table") were NOT touched by the escalation — their override semantics are different
- `m4_summary.by_override_source.hedged_reasoning_escalation = 5` ✓

---

## Component E — Re-run M4 + Regenerate PDF

**Engine baseline (architecture B+ invariant):**
- `audit_results.json` sha256: `8c5627f9b52a66d531b1661b6f419e55ee56e115028faa1fa36bf309e8b2fef8`
- ✓ Byte-identical to M4 lock baseline (engine never ran)

**M4 overlay:**
- `audit_results.m4.json` size: 291,805 bytes
- Total engine findings: 79
- Overridden: 33 (26 m2_finding + 2 m3_critic_disagreement + 5 hedged_reasoning_escalation)
- Sidecar-only findings: 6
- All 9 validator checks: **PASS**

**Verdict distribution shift:**

| Verdict | Before (engine) | After (M4+M5) | Δ |
|---------|-----------------|----------------|----|
| pass | 15 | 17 | +2 (M2 fills) |
| requires_review | 11 | 17 | +6 (M2 + M3 + **5 hedged escalations**) |
| not_submitted | 27 | 20 | −7 |
| not_applicable | 26 | 25 | −1 |

**Final PDF:**
- Path: `audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf`
- Size: **342,485 bytes** (≈ 334 KB)
- Page count: **44 pages**
- sha256: `3cc38b8a99f4202e4a6808c18cc7fc1346a12e69c0572a7d918dd85bd96beb78`
- Copy at: `/Users/liorlevin/Downloads/דוח סקירה M5 v24.3 - מתחם הטייסים-ההסתדרות.pdf`

---

## Component F — Self-Verification (Visual)

| Page | What was checked | Result |
|------|------------------|--------|
| 2 | TOC includes 2א and 5 | ✓ both present |
| 7 | תא שטח 1 — CONTENT_PARKING_RATIO row | ✓ "דורש בירור" (orange chip) — Task #32 fix visible |
| 9, 11, 13, 15 | תאי שטח 2-5 — same parking row | ✓ all four show "דורש בירור" |
| 18-19 | Section 2א sidecar cards | ✓ All 3 cards in clean planning Hebrew (6.5.1, 6.6.4, 7.1.1) — no English residue |
| 31 | Section 4 headline counts | ✓ 33 תקינים / 28 נדרשים תיקונים / 26 דורשים בירור (was 31/28/28 in M4 → +2/0/-2 shift consistent with escalation + sidecar inclusion) |
| 34 | Section 5.1 + 5.2 | ✓ green-header tables, alternating rows, RTL clean |
| 35 | Section 5.3 + 6 gap cards | ✓ red warning header + amber gap cards render correctly |
| 36-43 | Section 5.4 per-page table | ✓ 63 rows, no overflow, page-type Hebrew labels correct |
| 44 | Section 5.5 disclaimer | ✓ professional tone, references Ellen review correctly |

**Rendering bugs detected:** None.

---

## Files Touched (M5)

**New:**
- `vision_scanner/m4/translator_hebrew.py` (220 LOC)
- `vision_scanner/m5/__init__.py`
- `vision_scanner/m5/coverage_assembler.py` (~290 LOC)
- `data/projects/407-1048248/submissions/v24.3/coverage_report.json` (19 KB)

**Modified:**
- `vision_scanner/m4/schema.py` — `hedged_reasoning_escalation` enum value
- `vision_scanner/m4/processor.py` — escalation + sticky-escalation guard + translation hook
- `vision_scanner/m4/validate.py` — check #9 (no hedged→pass), skip orphan check for hedged source
- `vision_scanner/m4/run.py` — `--no-translate` CLI flag
- `compliance_engine/report_generator.py` — Section 5 rendering, TOC kwargs, coverage loader

**Regenerated outputs:**
- `audit_outputs/407-1048248/v24.3/audit_results.m4.json`
- `audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf`
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.json`
- `data/projects/407-1048248/submissions/v24.3/audit_results.m4.run_log.jsonl`

**NOT touched (per architecture B+):**
- `audit_outputs/407-1048248/v24.3/audit_results.json` (engine baseline) ✓
- Any file under `compliance_engine/` other than `report_generator.py`

---

## Round 2 — Post-review polish (Lior PDF review feedback)

Lior reviewed the M5-phase-1 PDF and surfaced two issues. Both fixed before lock.

### Issue 1 — Strip internal `Task #N` IDs from user-facing PDF text

Three leak sites, all patched:

| ID | Location | Before | After |
|----|----------|--------|-------|
| 1a | `vision_scanner/m4/processor.py::escalate_hedged_pass_verdicts` (line 137) | `[הסלמה אוטומטית — Task #32]: …` | `[הסלמה אוטומטית]: …` |
| 1b | `compliance_engine/report_generator.py` Section 5.3 gap-card render | Rendered `<div class="cov-gap-task">Task #N · …</div>` per card | Removed div; cards now show title + detail only. `task_ref` preserved in `coverage_report.json` data |
| 1c | Section 4 action item 8 (parking note) | Inherited Task #32 from fix-1a source | Auto-resolved via 1a (Section 4 reads `notes_he`) |

**Verification (full PDF text grep):** `0` occurrences of `Task #` in any rendered page. All remaining `Task #` strings in the repo are in code comments, docstrings, or internal data fields (audited and reported).

### Issue 2 — Coverage classifier softened for cadastral-only pages

`vision_scanner/m5/coverage_assembler.py::_classify_page` initially flagged 3 pages as UNADDRESSED (12, 13, 14). Pages 13 and 14 use cadastral plot refs `[52, 54]` that don't reconcile to takanon plots `{1-10, 20}` (Task #27 root cause), but the pages DO contain reviewed structural content (path widths, cross-sections).

**Patch:** new branch inserted before the strict `unmapped and not takanon_refs` UNADDRESSED rule:

```python
# Cadastral-only pages (Task #27 unreconciled labels) — page has content,
# just couldn't be linked to takanon plots. Treat as PARTIAL, not UNADDRESSED.
if pt in {"public_open_space", "site_plan_per_ta_shetach"} and unmapped:
    return "PARTIAL"
```

**Result:** `{'FULL': 55, 'PARTIAL': 7, 'UNADDRESSED': 1}` (was 55/5/3). Page 12 (`page_type="other"`, the שצ"פ phasing diagram) stays UNADDRESSED — genuinely uncovered. Pages 13/14 reclassified to PARTIAL.

### Final M5 PDF after Round 2

- Path: `audit_outputs/407-1048248/v24.3/audit_report_24.3.pdf`
- Page count: **46**
- Size: 342,572 bytes (~334 KB)
- sha256: `d16d46979ebd98bae12bec23619fefb161ac2833aa16d090c51bc9e56c6b8e55`
- Engine baseline `audit_results.json` sha unchanged: `8c5627f9b5...` ✓
- M4 validator: all 9 checks pass
- Catbox: https://files.catbox.moe/piqfpt.pdf (M5-final pre-Issue-2)

### Lock Status

**LOCKED** — Lior approved Issue 1 verification + Issue 2 softening; commit + push to `phase-3-vision`.
