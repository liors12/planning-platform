# National Regulatory Baseline — Israeli Planning Regulations
## Verified Reference Document for Ness Ziona Compliance Platform

**Last verified:** May 2026
**Maintained by:** Lior, Ellen
**Verification method:** Cross-referenced against primary sources at gov.il, nevo.co.il, and wikisource. All citations checked against actual regulation text.

---

## Purpose of this document

This document is the **single source of truth** for Israeli planning regulations as they apply to the compliance platform. It exists because:

1. LLM-generated regulatory analysis is **systematically wrong** on several key points (see Section 7 below)
2. Regulations have been amended multiple times in 2023-2025 — training data is stale
3. Section numbers and case citations must be verifiable, not trusted from memory
4. Future Claude instances must consult this document before citing any Israeli planning regulation

When this document conflicts with Claude's training data or another LLM's claim, **this document wins** (because it has been verified against primary sources). When this document is silent, the answer is unknown — do not invent.

---

## 1. Master statute: חוק התכנון והבניה, התשכ"ה-1965

**Authoritative text:** https://www.nevo.co.il/law_html/law01/044_001.htm
**Wikisource (consolidated):** https://he.wikisource.org/wiki/חוק_התכנון_והבניה

### Verified definitions (from §1, definitions section)

**"שטח כולל המותר לבניה"** — *"סך כל השטח המותר לבניה, הכולל הן שטחים למטרות עיקריות והן שטחים למטרות שירות"*

(Translation: total area permitted for construction, including both areas for primary purposes and service purposes)

**"מגרש"** — yields a parcel (cadastral or planning unit), including תלת-ממדי (3D) parcels.

### Key sections

**§62א(א)(6)** — Local Committee authority to approve plans that redistribute building areas:

> *"שינוי חלוקת שטחי הבניה המותרים בתכנית אחת, מבלי לשנות את סך כל השטח הכולל המותר לבניה בתכנית ובתנאי שהשטח הכולל המותר לבניה, בכל יעוד קרקע, לא יגדל ביותר מ-50%"*

**Important caveat**: This is an authority section — it does NOT specify how transfers are measured. Specific rules (e.g., "10% between plots") are written into individual תקנונים.

**§145(ז)** — Statutory matters that must be in a תב"ע (and therefore CANNOT be in a תכנית בינוי):
- Land use designations
- Number of housing units
- Building areas
- Height limits
- Building lines

(Per the מינהל התכנון guide of 10.11.2024 — תכנית בינוי may NOT modify any of these.)

**§151** — Variances and minor deviations from a plan.

---

## 2. תקנות חישוב שטחים, התשנ"ב-1992 (with major תיקון תשפ"ה-2025)

**Authoritative text (current):** https://www.nevo.co.il/law_html/law00/74663.htm
**Wikisource:** https://he.wikisource.org/wiki/תקנות_התכנון_והבניה_(חישוב_שטחים_ואחוזי_בניה_בתכניות_ובהיתרים)
**Government FAQ:** https://www.gov.il/he/pages/faq_calc_area
**Total area route guide:** https://www.gov.il/he/pages/guidelines_determining_total_area

### תקנה 1 — Definitions (verified)

**"כניסה קובעת לבנין"**:
> *"הכניסה הראשית לגזרת הבנין שבה היא נמצאת, אשר מפלס רצפתה אינו עולה על 1.20 מטר מעל פני הקרקע והגישה אליה היא באמצעות מדרגות או גשר כניסה ישיר ממפלס הרחוב, בהתאם לתקן ישראלי ת"י 166"*

**"מסד"** — chamber below the entry level, between rows of columns or surrounded by walls. Counted in total area only if its height exceeds 1.80m.

**"תוכנית בשטח כולל"** (added in תיקון תשפ"ה-2025): a plan in which building areas are defined without splitting between עיקרי and שירות.

**"היתר בשטח כולל"** (added in תיקון תשפ"ה-2025): a permit in which building areas are calculated without splitting.

### תקנה 2א — Dual-mode framework (added in תיקון תשפ"ה-2025)

A permit issued from each of the following situations is a "היתר בשטח כולל":

(a) Permit from a plan approved AFTER 3 December 2023 that is itself a "תוכנית בשטח כולל" or specifies that permits will be in total-area mode

(b) Permit from a plan approved UP TO 3 December 2023 that defined areas with split between עיקרי and שירות, BUT subject to additional conditions in תקנה 2א(2)

(c) Permit from a plan approved AFTER 3 December 2023 that defined areas with split, IF additional conditions are met (the approval was no later than 1 January 2026, etc.)

### תקנה 9 — Distinction between עיקרי and שירות (the core rule)

**תקנה 9(ב)** defines "מטרות עיקריות" — the purposes of the building (residential, commercial, industrial, etc.) as listed for each land use category.

**תקנה 9(ג)** establishes that everything not in service is automatically primary.

**תקנה 9(ד)** defines "מטרות שירות" — service purposes:
- Bomb shelter (ממ"ד)
- Mechanical/equipment rooms
- Storage
- Parking and parking-related areas
- Open columns floor (קומה מפולשת)
- Shared circulation: stairs, corridors in shared use
- Mechanical/utility shafts

### Operational rules (FAQ verified)

From the official Government FAQ for the area calculation tool:
- Code 101 (ממ"ד): 9 m² counted as service, remainder as primary
- Code 102 (wall area): 100% service
- Code 103 (ממ"ק/ממ"ס): 100% service
- Wall portions over 25cm thick: NOT counted in areas
- Wall portions over 50cm thick: marked code 113

Source: https://www.gov.il/he/pages/faq_calc_area

---

## 3. תקנות בקשה להיתר, התש"ל-1970

**Authoritative text:** https://www.nevo.co.il/law_html/law01/044_046.htm

### Verified building height categories (תקנה 1)

Height is measured from "the entry level of the building" to "the entry level of the highest floor designated for occupation, accessed via a shared staircase":

| Building category | Threshold |
|---|---|
| **בנין רגיל** | ≤ 13m |
| **בנין גבוה** | > 13m and ≤ 29m |
| **בנין רב-קומות** | > 29m |

### "כניסה קובעת לבניין" (alternate phrasing — same meaning)

> *"הכניסה הראשית לבניין או לגזרת הבניין שבה היא נמצאת, אשר פני מפלס רצפתה אינם גבוהים מ-1.20 מטרים מעל פני הקרקע המתוכננים או מפני הרחוב או המדרכה הסמוכים לה, ושהגישה אליה היא באמצעות שביל, מדרגות או גשר כניסה, ישירות ממפלס הרחוב; אם קיימת יותר מכניסה אחת, הכניסה הקובעת היא הכניסה שנקבעה כזו בהיתר הבניה"*

**Operational consequence**: When a building has multiple entrances at different elevations, the determining entry level is whichever one is specified in the building permit. There is **no automatic rule** — it requires permit-level decision.

### "קומה תחתית" (verified)

> *"קומה שמפלס רצפתה נמוך ממפלס הכניסה הקובעת לבניין; בין אם כל קירותיה של הקומה נמצאים מתחת לפני הקרקע המתוכננים ובין אם כל קירותיה או חלקם פונים לאוויר החוץ"*

**Critical**: This is the technical regulatory term. "מרתף" is colloquial usage. When the תקנון says "מרתף", it refers to קומה תחתית.

---

## 4. תיקון 117 (2017) and תיקון 155 (2024) — Common LLM error

**These tikunim deal SPECIFICALLY with splitting ground-floor houses (פיצול בתים צמודי קרקע). They DO NOT define "small apartment" generally.**

### תיקון 117 (2017)

- Temporary provision (5-year horizon)
- Allowed local committee to grant variance for splitting an existing single-family house into two units
- Required: existing house ≥120 m², new unit ≥45 m²
- Applied only to urban (not rural) ground-floor homes
- Applied only to plans approved before 01.01.2011
- Implementation was minimal (only 71 permits in first 15 months per State Comptroller)

### תיקון 155 (2024)

- Renewal of תיקון 117 with same intent
- Published 7.8.2024
- Adds option for additional 45 m² for the new unit (including ממ"ד) plus other incentives
- Same scope: only ground-floor houses
- Excludes metro influence zones (גוש דן)

### What these tikunim are NOT

- **NOT** the general definition of "דירה קטנה"
- **NOT** the source of the 75 m² or 80 m² thresholds in residential plans
- **NOT** applicable to apartment buildings or new construction in פינוי-בינוי projects

### What "דירה קטנה" actually is

There is **no single statutory definition**. Different thresholds appear in different contexts:

| Context | Threshold | Source |
|---|---|---|
| Variance for adding 2+ units to a building | ≤75 m² (incl. service areas) | תקנות הקלות תשפ"ג-2023 |
| Parking regulations | ≤80 m² | תקנות חניה תשמ"ג-1983 |
| Specific government policy | 80 m² (incl. ממ"ד) | חוזר מנכ"ל 3/2011, מסמך מדיניות מינהל התכנון |
| Specific plan | Whatever the תקנון specifies | Per project |

**For the platform**: The threshold defined in each תקנון is what governs. There is no national fallback.

---

## 5. תקנות הקלות, שימוש חורג וסטיה מתכנית, התשפ"ג-2023

**Replaced**: תקנות סטיה ניכרת תשס"ב-2002

This is where most "minor deviation" rules live. Important for understanding the difference between an acceptable variance and a "סטייה ניכרת" requiring full plan amendment.

---

## 6. תמ"א 15 — Aviation height limits

**Status**: National outline plan (תכנית מתאר ארצית) for airports
**Note**: Plan has been "in preparation for ~25 years" per State Comptroller and is still not fully approved as of latest verification

For project 407-0977595, the 91m above sea level limit derives from תמ"א 15 supplementary materials, specifically the section dealing with proximity to **תל נוף military airbase** (south of Nes Ziona). Specific aviation approval is from **רשות התעופה האזרחית (רת"א)**.

For aviation-related rules, primary authority is:
- **תקנות הטיס (הפעלת כלי טיס וכללי טיסה), תשמ"ב-1981**
- **תקנות הטיס (שדות תעופה — מידע תעופתי), תשע"ט-2018**
- AIP (Aeronautical Information Publication) of רת"א

The "40m above ground requires רת"א approval" rule, while standard, is **not a national uniform threshold** — it is set per location based on aeronautical surveys. It is correctly applied in the Hetzeisim תקנון for that specific site.

---

## 7. Common LLM Errors (DO NOT REPLICATE)

This section documents specific false claims that appeared in AI-generated regulatory analyses. They were verified to be wrong against primary sources.

### Error 1: "תיקון 117 defines 'small apartment'"
**Status**: FALSE
**Reality**: תיקון 117 deals with splitting ground-floor houses only.
**Often paired with**: Citation to "Section 147(י)(1)" — also unverified.

### Error 2: "תיקון 155 (2024) redefines the small apartment threshold"
**Status**: FALSE
**Reality**: תיקון 155 is the renewal of תיקון 117. It deals with split-housing, not general definitions.

### Error 3: "Court case עע"מ 2605/18 establishes height conflict resolution"
**Status**: UNVERIFIED — likely fabricated
**Reality**: Could not be located in court records via search. Multiple AI engines cited this case for the principle that "the more restrictive rule wins." That principle is correct as a general engineering interpretation, but the case citation should not be trusted.

### Error 4: "Government Decision 768 (2013) is the source for roof agreements"
**Status**: PARTIALLY VERIFIED
**Reality**: Government Decision 768 from 2013 does establish the policy framework for roof agreements, BUT individual roof agreements have their own specific terms not derivable from the decision alone. Each roof agreement is a separate document.

### Error 5: "Section 147(י) of the Planning and Building Law defines 'small apartment'"
**Status**: UNVERIFIED — likely confused with תקנות הקלות
**Reality**: §147 of the law deals with variances. The 75 m² threshold for adding multiple units appears in תקנות הקלות תשפ"ג-2023, not in the law itself.

### Error 6: "The תיקון תשפ"ה-2025 to תקנות חישוב שטחים doesn't exist yet"
**Status**: FALSE — it is published and in effect
**Reality**: Published 30.9.2025 as ק"ת 12056. Created the dual-mode framework for area calculations. Several AI engines were unaware of this regulation entirely.

### Error 7: "Building height is measured from sidewalk level"
**Status**: PARTIAL ERROR
**Reality**: Height is measured from "מפלס הכניסה הקובעת" (entry level). Entry level may be the sidewalk if the entrance is at sidewalk level, but it's more precisely defined as the floor level of the main entrance, which may be up to 1.20m above ground. Saying "from sidewalk" is approximate but the regulatory term is more specific.

---

## 8. Source verification log

Each of the following primary sources was consulted directly during the verification of this document.

| Document | URL | Last verified |
|---|---|---|
| חוק התכנון והבניה | https://www.nevo.co.il/law_html/law01/044_001.htm | May 2026 |
| תקנות חישוב שטחים | https://www.nevo.co.il/law_html/law00/74663.htm | May 2026 |
| תקנות בקשה להיתר | https://www.nevo.co.il/law_html/law01/044_046.htm | May 2026 |
| Total area route guide | https://www.gov.il/he/pages/guidelines_determining_total_area | May 2026 |
| Area calculation FAQ | https://www.gov.il/he/pages/faq_calc_area | May 2026 |
| Roof agreements policy | https://www.gov.il/he/departments/policies/2013_dec768 | May 2026 |
| Plan 407-0977595 official text | https://apps.land.gov.il/IturTabotData/takanonim/merkaz/4053239.pdf | March 2026 (via prior knowledge) |

---

## 9. Update protocol

This document should be updated whenever:

1. A new regulation is published that affects compliance checks
2. An AI engine is found to make a new error not yet documented in §7
3. A primary source cited here is moved or updated
4. A court ruling clarifies a previously ambiguous regulatory question

When updating, increment the date at the top of the document and add a note in a `CHANGELOG.md` adjacent to this file.

---

## 10. What this document does NOT contain

- Project-specific rules (those live in `project-schema-{plan_number}.json`)
- Engineer's case-by-case interpretations (those live in `project_rule_exceptions` table)
- Variance/approval workflows (those are part of the application logic, not the regulatory baseline)
- DWG file format details (those are in the `tech_stack` section of `SKILL.md`)
