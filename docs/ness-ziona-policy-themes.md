---
file: ness-ziona-policy-themes
purpose: |
  Knowledge base of recurring patterns in Ness Ziona local committee
  decisions AND the city's stated positions at district committee
  hearings. Used by compliance code as ADVISORY context — when
  analyzing a submitted document, the script can surface relevant
  past committee positions for the human reviewer to consider.
  NOT used for automated enforcement.
status: fifth_pass_draft
confidence_global: medium
sample_size: |
  Section I (P-001 to P-020): 36 local committee protocols, April 2025
  to April 2026.
  Section II (P-021 to P-036): 16 Central District Committee meetings,
  October 2014 to March 2026 — extracting only what Ness Ziona
  officials said about plans affecting Ness Ziona. Two source
  documents:
  (a) ועדת משנה להתחדשות עירונית 2023-2026 (468pp)
  (b) ועדת משנה להתנגדויות 2014-2022 (195pp)
sample_period: 2014-10 to 2026-04
created: 2026-05-01
last_updated: 2026-05-01
verification_status: not_yet_reviewed_by_ellen

usage_for_code: |
  When analyzing a submitted document, code can:
  1. Parse this file as YAML-frontmatter + Markdown.
  2. Extract entries by topic_keywords matching the document content.
  3. Surface matching entries to the reviewer as "relevant past committee
     positions to consider" — never as automatic violations or rules.
  4. Each entry includes evidence with protocol/case identifiers so the
     reviewer can verify the original decision.

caveat: |
  Patterns derived from past decisions describe what the committee HAS
  done, not what it MUST do. The committee retains full discretion to
  evolve its positions. This file informs the reviewer; it does not
  constrain the committee.

verified_committee_resolutions: |
  Four explicit committee resolutions identified in the corpus that
  represent codified policy (not just patterns):
  - Resolution 202203 from 17.05.2022 — pool setback policy (1.0m)
  - Resolution from 30.11.2020 — balcony expansion 30% + 6% area
    (per Section 147), via plan 407-0867242 / ס/מק/13/1
  - Resolution 202508 from 30.07.2025 — supersedes the 2020 resolution;
    deposits plan 407-1459544 regulating concessions for low-rise
    construction including Section 147 concessions
  - Plenary resolution 202101 — TMA-38 local extension to 18.05.2025
---

# Ness Ziona Committee Policy Knowledge Base

## How to read this file

Each policy entry below is structured with YAML metadata followed by prose.
The metadata is for code; the prose is for human reviewers verifying the
pattern. Every entry includes:

- **topic_keywords**: Hebrew terms that, if present in a submitted document,
  suggest this entry may be relevant.
- **request_types_affected**: Types of building applications this pattern
  applies to (e.g., `רישוי מקוצר`, `ועדת משנה`, `היתר חדש`).
- **status**: One of:
  - `observed_pattern` — Recurs across multiple decisions; reasonably solid.
  - `single_observation` — Seen once; flagged for further verification.
  - `verified_policy` — Explicitly cited as policy by the committee or by
    a written committee resolution.
- **confidence**: `low | medium | high | very_high`. Reflects sample size
  and ambiguity.
- **evidence_count**: Number of distinct cases supporting this pattern in
  current sample.

The entries below are derived from the **full corpus** of 36 protocols
spanning April 2025 – April 2026.

---

---

# Section I: Local Committee Decisions

The entries below (P-001 through P-020) are derived from local
committee protocols (רשות רישוי + ועדת משנה לתכנון ולבניה +
מליאת הועדה המקומית) covering April 2025 to April 2026. These
describe what the committee actually decides — recurring patterns
in approvals, conditions, dissents, and rejections.

---

## P-001: Wall and fence height notation in submitted plans

**topic_keywords:** [גדרות, קירות, גובה, מדידה, מפלס]
**request_types_affected:** [רישוי מקוצר, היתר בנייה]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 2
**first_observed:** 2025-08-07
**last_observed:** 2025-08-07

**Pattern:**
The committee requires submitted plans to explicitly mark wall and fence
elevation/height, not just their existence. Omission causes rejection or
return for correction.

**Evidence:**
- Protocol 202511 (2025-08-07), case 20250727\3: Garden of Remembrance,
  גני איריס. Rejected. Quote: "נדרש לבקש מהמודד להוסיף גובה גדרות
  קיימות במדידה / נדרש בתכניות הפיתוח גובה גדרות בהתאם למדידה / יש
  לרשום מפלס של הקירות ושל הגדרות"

**Implication for new submissions:**
If a submitted document includes fence/wall designs without elevation
data, flag this as a likely committee concern.

**Open questions for Ellen:**
- Is this a written guideline, or pattern of practice?

---

## P-002: Fence height increase to 2m for privacy and security

**topic_keywords:** [הגבהת גדר, גובה גדר, פרטיות, ביטחון, 2 מטר, 1.50 מטר]
**request_types_affected:** [ועדת משנה, היתר חדש, הקלה]
**status:** observed_pattern
**confidence:** very_high
**evidence_count:** ~50 (most common pattern in subcommittee corpus)
**first_observed:** 2025-04
**last_observed:** 2026-04

**Pattern:**
The committee consistently approves requests to raise fence heights from
the regulatory 1.50m to 2m, citing "privacy and security" and "in
accordance with regional guidelines (הנחיות מרחביות)". This is the
single most common concession pattern in the corpus. Standardized
phrasing: "הועדה מחליטה לאשר ברוב קולות לצורך פרטיות וביטחון ובהתאם
להנחיות מרחביות".

Note: Pattern occurs predominantly in subcommittee protocols (ועדת
משנה). Licensing authority protocols (רשות רישוי) rarely contain
fence-height concessions because those don't fall in licensing
authority's scope.

**Evidence (selected — pattern is pervasive):**
- Protocol 202506 (2025-05-25): Multiple cases.
- Protocol on 2025-08-03 (819511): 18 occurrences in single protocol.
- Protocol 202512 (2025-11-26): Same pattern, multiple cases.
- Protocol from 2026-01 (839413): 16 occurrences.

**Note on dissent (sub-pattern — see P-010):**
Committee member Gil Anukov consistently objects when fence-height
increase relates to a fence facing the street.

**Implication for new submissions:**
Fence-height requests up to 2m are highly likely to be approved. If
the fence faces the street, expect Anukov dissent but committee
approval by majority.

**Open questions for Ellen:**
- Is the 2m limit a hard cap or discretionary?
- What is Anukov's stated objection?

---

## P-003: Generic justification "לצורך תכנון מיטבי"

**topic_keywords:** [תכנון מיטבי, מיטבי, ניוד שטחים, קו בניין, הקלה]
**request_types_affected:** [ועדת משנה, הקלה]
**status:** observed_pattern
**confidence:** very_high
**evidence_count:** 30+
**first_observed:** 2025-05
**last_observed:** 2026-04

**Pattern:**
"לצורך תכנון מיטבי" (for optimal planning) is the committee's default
justification when approving discretionary concessions, including:
- Moving floor area between floors (ניוד שטחים)
- Reducing front/rear/side setbacks (הקטנת קו בניין)
- Increasing ground-floor coverage percentage
- Modifying the ±0.00 elevation level
- Extending below-grade English yards (חצר אנגלית)
- Balcony protrusion (הבלטת גזוזטרה / מרפסת)

**Sub-pattern: combined justifications**
"לטובת אפשרות ניצול זכויות בניה מירבי ותכנון מיטבי של המגרש" — when
committee approves both 6% area increase AND area movement, they cite
"maximum building rights" alongside "optimal planning".

**Implication for new submissions:**
Concessions fitting "minor design optimization" pattern likely approved
with this generic justification.

**Open questions for Ellen:**
- What concrete factors push a concession from approve to reject?

---

## P-004: Pool setback policy — committee resolution 202203 (17.05.2022)

**topic_keywords:** [בריכה, בריכת שחיה, קו בניין, הקלה לבריכה]
**request_types_affected:** [ועדת משנה, הקלה]
**status:** verified_policy
**confidence:** very_high
**evidence_count:** 3 explicit citations
**resolution_date:** 2022-05-17
**resolution_number:** 202203

**Pattern:**
Plenary resolution from 17.05.2022 (decision 202203) established a
policy allowing pool setback reduction down to 1.0m from property line.
Cited when approving new concessions AND when rejecting objections.

**Sub-pattern: chlorine smell objections**
"מדובר בבריכה לשימוש פרטי ולא בריכה ציבורית בהתאם לתכנית החלה, ולכן
שימוש בכלור נעשה בהתאם לשטח בריכה קטן ולכן זניח".

**Implication for new submissions:**
Pool setback up to 1.0m governed by explicit prior resolution.

**Open questions for Ellen:**
- Is the full text of resolution 202203 available?

---

## P-005: Rejection for "after-the-fact" construction (בנייה בדיעבד)

**topic_keywords:** [בנייה בדיעבד, צו הריסה, צו מינהלי, הליך אכיפה, הטעיית הועדה]
**request_types_affected:** [רישוי מקוצר, ועדת משנה, היתר בנייה]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 2
**first_observed:** 2025-08
**last_observed:** 2025-08

**Pattern:**
Building applications seeking to legitimize unpermitted construction
already performed are rejected with detailed multi-point reasoning that
often includes "הטעיית הועדה" (misleading the committee), inconsistency
between plans and engineering documents, and inadequate constructional
reference to existing conditions.

**Evidence:**
- Protocol 832565 (2025-08): Pool built adjacent to retaining wall with
  2.75m height differential. Rejected for 5 specific reasons.

**Open questions for Ellen:**
- What is the committee's policy on legitimizing minor as-built
  deviations vs. significant ones?

---

## P-006: Short licensing track auto-rejection on missed deadline

**topic_keywords:** [רישוי מקוצר, הערות בדיקה, לוחות זמנים, תקנות רישוי]
**request_types_affected:** [רישוי מקוצר]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 1
**first_observed:** 2025-08-07

**Pattern:**
In short licensing track, when applicant fails to correct review comments
within timeframes set by regulations "(רישוי בנייה), תשע"ו-2016", the
application is auto-rejected.

**Open questions for Ellen:**
- What are the actual deadlines in days?
- Can extensions be requested?

---

## P-007: 6% + 30% balcony policy — superseded resolutions

**topic_keywords:** [תוספת 6%, סגירת מרפסות, גזוזטראות, סעיף 147, ניצול זכויות בניה]
**request_types_affected:** [ועדת משנה, הקלה]
**status:** verified_policy
**confidence:** very_high
**evidence_count:** 2 distinct citations from 2 resolutions

**Two resolutions identified:**
1. **30.11.2020** — Plan 407-0867242, ס/מק/13/1, "הרחבת גזוזטראות
   והסדרת הקלות לפי סעיף 147". Cited in protocols 819511 and earlier.
2. **30.07.2025 (resolution 202508)** — Plan 407-1459544, "הסדרת הקלות
   שבוטלו בנייה צמודת קרקע בנס ציונה לרבות הקלות לפי סעיף 147".
   Cited in protocol 834665 (Nov 2025).

The second appears to supersede the first.

**Standard approval phrasing:**
"הועדה מחליטה לאשר את ההקלות לטובת אפשרות ניצול זכויות בניה מירבי
ותכנון מיטבי של המגרש, תואם למדיניות התכנונית כפי שבאה לידי ביטוי
בהחלטת ועדת משנה מתאריך [DATE] שהחליטה לאשר הפקדת תוכנית מספר
[PLAN_ID], בנושא [TOPIC], הכוללת את ההקלה/ות הנוכחיות"

**Open questions for Ellen:**
- Is plan 407-1459544 currently approved or still in deposit?

---

## P-008: Apartment unit splitting per Amendments 117/155

**topic_keywords:** [פיצול יח"ד, פיצול יחידת דיור, תיקון 155, תיקון 117, הוראת שעה]
**request_types_affected:** [ועדת משנה, הקלה]
**status:** verified_policy (statutory)
**confidence:** high
**evidence_count:** 4 cases

**Pattern:**
Apartment unit splitting governed by national temporary orders:
- Amendment 117 — original temporary order, expired
- Amendment 155 — current temporary order, expired June 2025
- Planning Administration directive 1.5.2023 — allows transitional
  cases (filed under 117 but undecided when 155 came in) to be heard
  under 155 without re-filing

**Standard splitting criteria observed:**
- Existing house >120m²
- Split unit >60m² (triggers parking requirement)
- Additional parking space required if split unit >60m²

**Standard conditions imposed on splits:**
- Registry warning per Land Regulations Article 27
- Restriction: split unit cannot be further split or rented separately

**Open questions for Ellen:**
- Is Amendment 155 still in effect, or has it been further amended?

---

## P-009: TMA-38 local extension by Ness Ziona

**topic_keywords:** [תמ"א 38, תמ"א 38/2, חיזוק, עיבוי בניין]
**request_types_affected:** [ועדת משנה, היתר חדש]
**status:** verified_policy
**confidence:** high
**evidence_count:** 1 explicit
**resolution_date:** plenary 202101
**extension_until:** 2025-05-18

**Pattern:**
Ness Ziona local committee, via plenary, extended TMA-38 applicability
beyond national expiration date until 18.05.2025 (via plenary
resolution 202101).

**Open questions for Ellen:**
- What replaced TMA-38 after 18.05.2025?

---

## P-010: Member dissent — Gil Anukov on street-facing fence/room heights

**topic_keywords:** [גיל אנוקוב, מסתייג, חזית הרחוב, גובה הגדרות, חדר לחזית הרחוב]
**request_types_affected:** [ועדת משנה]
**status:** observed_pattern (procedural)
**confidence:** high
**evidence_count:** 6+

**Pattern:**
Subcommittee member Gil Anukov consistently objects (מסתייג) when:
- Fence-height increases approved on street-facing facades
- Room heights exceed regulations on street-facing facades

Standard formulation: "גיל אנוקוב - בעד למעט ההקלה מס' [N] לעניין
[גובה הגדרות בחזית לכביש / הגבהת חדר לחזית הרחוב מעבר למותר בתקנות]".

**Variant: full abstention**
In rare cases (subcommittee plan-deposit decisions), Anukov fully
abstains: "נמנע: גיל אנוקוב". Different vote pattern from his usual
partial dissent.

**Implication for new submissions:**
Fence/height concessions on street-facing facades likely to pass with
documented dissent. Procedural fact only — does not affect outcome.

**Open questions for Ellen:**
- What is Anukov's underlying objection?

---

## P-011: Committee will not address property-value disputes

**topic_keywords:** [שינוי ערך הנכס, ערך הנכס, ירידת ערך]
**request_types_affected:** [ועדת משנה (objection rejection)]
**status:** verified_policy (procedural)
**confidence:** medium
**evidence_count:** 1 explicit
**first_observed:** 2025-05

**Pattern:**
When neighbor objections include property-value impact claims, the
committee explicitly states this is outside its purview: "בהתייחס
לשינוי ערך הנכס הוועדה לא עוסקת בנושא זה".

**Open questions for Ellen:**
- Where do property-value disputes actually go?

---

## P-012: Standard registry warning on basement units (split-prevention)

**topic_keywords:** [מרתף, פיצול יח"ד, הערת אזהרה, תקנה 27, תקנה 27(א)]
**request_types_affected:** [ועדת משנה, הקלה, רשות רישוי (newer cases)]
**status:** observed_pattern (consistent)
**confidence:** very_high
**evidence_count:** 8+
**first_observed:** 2025-05
**last_observed:** 2026-03

**Pattern:**
When approving designs with basements that have potential separate
access, the committee imposes a standard registry warning preventing
the basement from becoming an independent dwelling unit. Standard
wording: "תנאי להיתר - רישום הערת אזהרה - עפ"י תקנות המקרקעין (ניהול
ורישום) תקנה 27 שלפיה ייעוד המרתף, הינו למגורי בעלי הנכס בלבד ואסורה
להשכרה או לפיצול, פתיחת הדלת במרתף - לא תיצור יחידת דיור נוספת
במגרש".

In newer protocols (2026), the licensing authority also imposes the
warning, citing Article 27(a) specifically: "תנאי להיתר בניה - רישום
הערת אזהרה בהתאם לתקנה 27(א) לתקנות המקרקעין... פתיחת הדלת במרתף - לא
תיצור יחידת דיור נוספת במגרש".

**Implication for new submissions:**
Basement designs with separate entrances should anticipate this
condition.

**Open questions for Ellen:**
- Are these warnings actually enforced over time?

---

## P-013: Hydrology requirement when site infiltration < 15%

**topic_keywords:** [תכסית, חוו"ד הידרולוג, חילחול, פתרונות חילחול, שטחים חדירי מים]
**request_types_affected:** [ועדת משנה, רשות רישוי, הקלה]
**status:** observed_pattern
**confidence:** high
**evidence_count:** 2 with quantitative threshold
**first_observed:** 2025-11
**last_observed:** 2026-03

**Pattern:**
The Ness Ziona local committee requires that submitted plans demonstrate
**at least 15% of site area as water-permeable surfaces** (שטחים חדירי
מים). When designs fall below this threshold, the committee requires
either:
- Infiltration installations on-site (בורות חלחול / קידוח החדרה), or
- A hydrologist's opinion (חוו"ד הידרולוג) on alternative infiltration
  solutions

When approving requests to increase site coverage (תכסית), the committee
adds a hydrology condition: "בכפוף לקבלת חוו"ד הידרולוג לנושא פתרונות
חילחול".

**Evidence:**
- Protocol 834665 (Nov 2025): Coverage increase approved with hydrology
  condition.
- Protocol 202605 (March 2026): MDA station case explicitly states
  "ניתן יהיה להותיר פחות מ-15% שטחים חדירי מים משטח המגרש, אם יותקנו
  בתחומי המגרש מתקני החדרה כגון בורות חלחול". The submitted plan had
  10.5% infiltration, requiring hydrologist approval.

**Implication for new submissions:**
Plans with site coverage that reduces infiltration below 15% must
include either physical infiltration installations or a hydrologist's
opinion.

**Open questions for Ellen:**
- Is 15% a written threshold or pattern of practice?
- Are there approved hydrologists?

---

## P-014: Easement registration as condition for development plan permits

**topic_keywords:** [זיקת הנאה, רישום זיקת הנאה, זכות מעבר, רשם המקרקעין]
**request_types_affected:** [ועדת משנה (תכנית בינוי)]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 1 case
**first_observed:** 2026-02-25

**Pattern:**
When approving development plans (תכנית בינוי) that involve passage
rights between properties, the committee requires:
1. Submission of easement diagram matching the development plan
2. Registration of easement at the Land Registry **before permit
   issuance**
3. Signature of all property owners on the development plan and
   easement diagram

**Evidence:**
- Protocol 202602 (2026-02-25): Development plan ס/בינוי נס/4/46/
  approved with these three explicit conditions.

**Sub-pattern: Committee will not enforce private easement claims**
When neighbors claim a public passage right based on convention or
historical use, the committee rejects: "התכנית החלה על המגרשים הינה
נס/4/46/, התכנית אינה כוללת שטח ציבורי שיכול לשמש כמעבר לציבור הולכי
הרגל... מדובר במגרש בבעלות פרטית עם זכויות מוקנות ואין הסכמה של
הבעלים לאפשר את זכות המעבר".

**Implication for new submissions:**
Development plans involving easements must include the easement diagram
and obtain owner signatures.

---

## P-015: Committee will not adjudicate inter-owner financial disputes

**topic_keywords:** [מחלוקת כספים, החזר תשלום, הוצאות פיתוח, סלילת כביש]
**request_types_affected:** [ועדת משנה (objection rejection)]
**status:** verified_policy (procedural)
**confidence:** medium
**evidence_count:** 1 explicit

**Pattern:**
When objections include claims about financial disputes between owners
(e.g., reimbursement for shared development expenses), the committee
explicitly states this is outside its purview: "אין זה מסמכותה של
הועדה להחליט בין בעלים בנושא מחלוקת כספים פנימית".

**Evidence:**
- Protocol 202602 (2026-02-25): Objection raised about road-paving
  cost reimbursement rejected with this phrasing.

**Implication for new submissions:**
Similar to P-011 (property values), financial disputes between owners
go elsewhere — not to the committee.

---

## P-016: Multi-stage construction permits with extended validity

**topic_keywords:** [תוקף היתר, היתר בשלבים, תעודת גמר בשלבים, פרויקט מורכב]
**request_types_affected:** [רשות רישוי, היתר בנייה]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 1 detailed case
**first_observed:** 2026-04

**Pattern:**
For large public projects (e.g., schools, complex public buildings),
the committee can grant extended permit validity (up to 9 years) and
allow staged completion certificates.

**Evidence:**
- Protocol 202609 (2026-04-20): Public school project. Standard
  conditions:
  1. "תוקף היתר 9 שנים, מהנימוק שהמדובר בבקשה לבניית בית ספר בשלבים
     לאור מורכבת הפרויקט ביצועו ותיקצובו"
  2. "תותר קבלת תעודת גמר בשלבים ולא יותר מהתקופה המקסימלית 9 שנים,
     ובכפוף לקבלת תכנית התארגנות וסקר סיכונים מאושרים ע"י מהנדס
     בטיחות ומהנדס מבנים"

**Implication for new submissions:**
Complex public projects may qualify for extended validity. Reviewer
should verify safety plan and risk survey if staging is requested.

**Open questions for Ellen:**
- Are there criteria for "complexity" that justify extended validity?
- Is 9 years the maximum, or can it be shorter?

---

## P-017: Aesthetic conditions on public-facing fences (kurkar stone cladding)

**topic_keywords:** [גדרות בנויות, אבן כורכרית, חזית הרחוב, גדר מוסדית, חיפוי]
**request_types_affected:** [רשות רישוי (institutional buildings)]
**status:** single_observation
**confidence:** low
**evidence_count:** 1
**first_observed:** 2026-04

**Pattern:**
For institutional buildings, the committee imposes aesthetic conditions
on built fences:
- "גדר מוסדית על גבי מסד או גדר בנויה, דלתות לפירים, שערים, פחי
  אשפה - יהיו מפח מגולוון וצבוע בתנור"
- "גדרות בנויות - יחופו אבן כורכרית בגוון התואם לחזית הרחוב"

**Evidence:**
- Protocol 202609 (2026-04-20): Public school project.

**Implication for new submissions:**
Institutional building fences should anticipate kurkar stone cladding
requirement. Single observation — verify before relying.

**Open questions for Ellen:**
- Does this apply to residential street-facing fences too?
- Are there specific kurkar suppliers or color specifications?

---

## P-018: Permit extension limit — 6 years total

**topic_keywords:** [הארכת תוקף, חידוש היתר, תוקף היתר]
**request_types_affected:** [רשות רישוי]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 1 explicit case
**first_observed:** 2026-03

**Pattern:**
Permit extensions are capped at a cumulative 6 years. After this,
further extensions cannot be approved: "סה"כ הארכת תוקף היתר כולל
הארכה נוכחית הינה 6 שנים. לא ניתן לאשר הארכות נוספות".

**Evidence:**
- Protocol 202605 (March 2026): Permit extension granted to August 2027
  with explicit notice that this is the final extension permitted.

**Implication for new submissions:**
If a permit has been extended multiple times, check cumulative extension
period. Beyond 6 years, the file requires a new permit application.

**Open questions for Ellen:**
- Is 6 years a national rule or a Ness Ziona-specific limit?
- Does the cumulative cap restart with a new permit, or only with
  certain permit types?

---

## P-019: Existing-building violations not legitimized by current permit

**topic_keywords:** [חריגות בנייה, פלישות, הפקעות, תקנה 29(א)]
**request_types_affected:** [רשות רישוי, היתר בנייה]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 1 explicit
**first_observed:** 2026-03

**Pattern:**
When granting a permit for changes/additions to an existing building,
the committee adds a standard disclaimer protecting itself: "אין בבקשה
להיתר בכדי להכשיר חריגות בנייה, הפקעות, פלישות וכדומה" (this permit
does not legitimize existing building violations, expropriations,
encroachments, etc.).

A registry warning per Reg. 29(a) is also imposed for existing
violations: "נדרש לרשום הערת אזהרה לפי תקנה 29(א) לתקנות המקרקעין
ניהול ורישום, לגבי חריגות בנייה".

This is **distinct from the basement Reg. 27 warning (P-012)**.

**Evidence:**
- Protocol 202605 (March 2026): Existing building case with these two
  conditions.

**Implication for new submissions:**
Permits on existing buildings always include this disclaimer. Reviewer
should verify if Reg. 29(a) warning is needed for documented existing
violations.

---

## P-020: Accessible parking designation as shared property

**topic_keywords:** [חניות נכים, רכוש משותף, שימוש לא ייחודי, תקנה 27]
**request_types_affected:** [ועדת משנה, רשות רישוי, היתר חדש]
**status:** observed_pattern
**confidence:** medium
**evidence_count:** 3+
**first_observed:** 2025-08
**last_observed:** 2026-02

**Pattern:**
When residential building designs include accessible parking spaces
(חניות נכים), the committee imposes a registry warning per Land
Regulations Article 27 designating the accessible parking as **shared
property** (רכוש משותף) for non-exclusive use:

"רישום הערת אזהרה לפי תקנה 27 לתקנות המקרקעין (ניהול ורישום) תשע"ב
2011, בדבר ייעוד חניות נכים כרכוש משותף, לשימוש לא ייחודי".

**Evidence:**
- Protocol 819511 (Aug 2025): Multiple cases.
- Protocol 810894 (May 2025): Multiple cases.
- Protocol 820697 (plenary, July 2025): Reference.

**Implication for new submissions:**
Multi-unit residential designs with accessible parking should
anticipate this registry warning condition.

**Open questions for Ellen:**
- Does this apply to single-family homes with accessible parking?
- What's the practical effect — can disabled residents still use the
  spaces?

---
---

# Section II: City Positions Voiced at District Committee

The entries below (P-021 through P-036) are derived from a different
source: protocols of the Central District Committee for Planning and
Building (הועדה המחוזית לתכנון ובניה מחוז מרכז), spanning October
2014 to March 2026 across two subcommittees (התחדשות עירונית and
התנגדויות). The district committee handles statutory plans (תב"ע)
that exceed local committee authority — typically larger urban
renewal projects, building-rights amendments, and plans with
significant public impact.

These entries capture **what Ness Ziona officials said at district
committee hearings** about plans affecting Ness Ziona. They are NOT
local committee policy — but they reveal the city's strategic
priorities, negotiating positions, and red lines on major projects.
This is forward-looking policy: what Ness Ziona will likely advocate
for or oppose in future plans of similar character.

**Speakers identified across sources:**
- **ראש העיר** Shmuel Bukser (Mayor, current)
- **מהנדס העיר** Boaz Gamliel (City Engineer, current)
- **מהנדס העיר** Kiril Koziol (City Engineer, 2014-2016)
- **גב' סמדר ירון** (planning department, both periods)
- **מנהלת/סגנית מנהלת אגף תכנון בעירייה** (current period)
- **נציגת הוועדה המקומית** (local committee representative at district hearings)
- **יועץ תנועה מטעם עיריית נס ציונה** (Ness Ziona traffic consultant)
- **מנהל מח' תשתיות עיריית נס ציונה** (Ness Ziona infrastructure department head)
- **תאגיד המים נס ציונה / מי ציונה** (Ness Ziona water utility)

**Plans referenced (eight Ness Ziona plans at district level):**
- 407-0121749 — מבואה צפונית נס ציונה (Northern Approach, 2014, 491 units)
- 407-0139295 — כפר אהרון נס/155 (Kfar Aharon, 2016, 220 units)
- נס/130/ב — North-West Ness Ziona (2015-16, 582 units)
- 407-0730606 — נס ציונה צפון מזרח (Northeast NZ, 2021-22, 2,783 units)
  — **the statutory plan whose תקנון we already have in the corpus**
- 407-0871731 — מתחם נחמיה (Nehemia compound, urban renewal)
- 407-0850719 — פינוי בינוי נס ציונה העצמאות 17-25
- 407-1087006 — התחדשות עירונית מרגולין (Margolin)
- 407-1157635 — מתחם ירושלים (Yerushalayim Compound)
- 407-1048248 — התחדשות עירונית במתחם ההסתדרות-הטייסים (**our pilot's adjacent plan**)
- 407-0372334 — (referenced but not detailed)

---

## P-021: Aviation height limit (~91m) is hard, regardless of statutory plan

**topic_keywords:** [מגבלות גובה, רת"א, סקר תעופתי, משרד הביטחון, גובה מבנה]
**request_types_affected:** [תב"ע, היתר חדש in tall buildings]
**status:** verified_policy (city's stated position)
**confidence:** high
**evidence_count:** 3+ statements
**first_observed:** 2024-12-16
**last_observed:** 2025-06-03

**Pattern:**
Ness Ziona is subject to aviation height restrictions enforced by the
Israeli Air Force (רת"א) and Ministry of Defense, due to its proximity
to military aviation corridors. The City Engineer treats **91m as the
binding cap**; **97m has been allowed only exceptionally for 3 specific
buildings** in the Nehemia compound. The Ministry of Defense approves
heights by **building-specific coordinates**, not flight-corridor
zones, so the cap cannot simply be "lifted citywide".

The Mayor confirmed he will **not advocate for breaking the height
cap** even when developers and owners argue economic infeasibility:
"מקבלים את ההצעה לציפוף ללא העלאת גובה" (accept density addition
without raising height).

The cap is currently **under reconsideration** by the Ministry of
Defense, but no timeline.

**Direct quotes:**
- City Engineer: "מגבלת הגובה היא 91 מ' ולא 97 מ', הגובה המרבי הותר
  ל-3 מבנים בלבד" (Plenary 2024041, 16.12.2024)
- City Engineer: "משרד הביטחון מאשר לפי קואורדינטות של בניין ולא לפי
  נתיבים, אין לפרוץ את מגבלות הגובה"
- Mayor: "מקבלים את ההצעה לציפוף ללא העלאת גובה" (16.12.2024)

**Implication for our compliance platform:**
For plans involving Ness Ziona buildings near aviation corridors,
height proposals exceeding 91m must include explicit per-building
coordinate-level approval from Ministry of Defense. Generic "up to
97m" allowances should trigger reviewer attention.

**Open questions for Ellen:**
- Is there a public document specifying the height cap by zone?
- Is the cap project-specific (Nehemia) or citywide?

---

## P-022: Average apartment size cap ~95-105m² in urban renewal

**topic_keywords:** [גודל דירה ממוצע, תמהיל יח"ד, התחדשות עירונית, מ"ר ממוצע]
**request_types_affected:** [תב"ע פינוי-בינוי, התחדשות עירונית]
**status:** observed_pattern (city's stated negotiating position)
**confidence:** medium
**evidence_count:** 2 detailed cases
**first_observed:** 2025-06-25

**Pattern:**
The City Engineer treats **95-105m² average apartment size as the
norm** for urban renewal in Ness Ziona, and pushes back against
larger averages even when developers argue the "owner reward" (תמורה)
calculations require larger units. **115m² average is considered too
large.** The argument is two-fold:
1. Quality: "פוגע באיכות התכנון, מגדיל את נפח המבנים ומקטין מרחק בין
   בניינים" (harms planning quality, increases building volume,
   reduces distance between buildings)
2. Precedent: "אין שום תכנית דומה לזה בעיר" (no comparable plan
   exists in the city)

The committee suggests alternative routes for closing economic gaps:
reducing visitor parking, allowing micro-units (דיוריות).

**Direct quote:**
- City Engineer (Yerushalayim Compound, 25.06.2025): "הגענו להסכמה
  לעלות את מס' יח"ד מ-270 ל-299 יח"ד כאשר הגודל הממוצע הכולל ליח"ד
  הוא 104.8 מ"ר. בהגדלת השטח כפי שמוצע, מתקבלות דירות של 115 מ"ר
  השטח ממוצע, אין שום תכנית דומה לזה בעיר"
- District Committee chair confirmed norm: "בדרך כלל הגודל הממוצע
  המקובל הוא סביב 95-100 מ"ר"

**Implication for our compliance platform:**
For urban renewal plans (פינוי-בינוי, התחדשות עירונית) in Ness Ziona,
average apartment size proposals exceeding ~105m² should be flagged
as inconsistent with the city's stated negotiating position.

**Open questions for Ellen:**
- Is there a written city policy on apartment-size mix?
- Does this apply to non-renewal plans?

---

## P-023: Land value parity with Lod is rejected

**topic_keywords:** [ערך הקרקע, יחס המרה, תמורות, כדאיות כלכלית]
**request_types_affected:** [תב"ע פינוי-בינוי, התחדשות עירונית]
**status:** observed_pattern (city's stated position)
**confidence:** medium
**evidence_count:** 2 statements
**first_observed:** 2025-06-25

**Pattern:**
The Mayor explicitly rejects developer arguments that compare
Ness Ziona's land economics to lower-value cities (Lod was named
specifically). Conversion ratios (יחס המרה) of 1:5 are characterized
as unworkable: "לא נוכל לקדם פרויקטים בעיר" (we cannot advance
projects in the city). The mayor's stated comfort zone: 1:3 to ~1:3.9.

**Direct quotes:**
- Mayor (Yerushalayim Compound, 25.06.2025): "ערך הקרקע בנס ציונה לא
  דומה לערך בלוד"
- Mayor: "מתנגדים. יגיעו ליחס המרה של 1:5, לא נוכל לקדם פרויקטים
  בעיר"

**Implication for our compliance platform:**
For urban renewal plans, owner-reward conversion ratios exceeding
~1:4 should be flagged. Plans that benchmark Ness Ziona land values
to lower-cost cities should be flagged for reviewer attention.

**Open questions for Ellen:**
- What conversion ratio does the city consider standard?
- How is land value formally documented for these comparisons?

---

## P-024: Wait-for-policy doctrine on individual urban renewal projects

**topic_keywords:** [מדיניות שכונתית, תכנון נקודתי, תכנון מתחמי, מדיניות]
**request_types_affected:** [תב"ע, התחדשות עירונית]
**status:** observed_pattern (active dispute with district committee)
**confidence:** high
**evidence_count:** 5+ statements
**first_observed:** 2025-06-25

**Pattern:**
The City Engineer publicly disagrees with the district committee's
willingness to advance individual urban renewal plans before
neighborhood-wide policy is in place. The city argues:

1. Approving individual projects with high density multipliers
   (1:5+) creates uncorrectable precedents.
2. The city is preparing neighborhood policies (תקצוב התקבל לאחרונה)
   and asks for delay until policies are finalized.
3. The Urban Renewal Authority (הרשות להתחדשות) has budgeted
   policy preparation.
4. Estimated timeline: "תוך חצי שנה יהיו חלופות, שנה למדיניות
   סופית".

The district committee's response: "אי אפשר לחכות למסמך מדיניות"
(cannot wait for policy document) and "התחייבנו לדון בתכנית
נקודתית שהוגשה" (committed to discuss individual plans submitted).

**Direct quotes:**
- City Engineer: "בכל מקום שחרגנו הבאנו זאת לידיעתכם והסברנו למה
  רצוי לחרוג באותו מקום. הכל בשיתוף פעולה מלא עם המחוז. כאן לא
  מצאנו סיבה לחריגה"
- City Engineer: "האם כל מה שלא עומד בכלכליות נאשר בחריגה בניגוד
  לכל המדיניות בעיר?"
- City Engineer: "אנחנו באים לתכנן, לא לתת מענה כלכלי ליזם"

**Implication for our compliance platform:**
For urban renewal plans in Ness Ziona, the city's stated preference
is **not** to approve plans that exceed citywide multiplier norms,
even on economic-feasibility grounds. Reviewer should confirm
whether neighborhood-policy is in place before relying on permissive
multipliers.

**Open questions for Ellen:**
- Has the neighborhood-level policy for any neighborhood been
  finalized since June 2025?
- Are there written neighborhood-level policy documents we should
  add to the corpus?

---

## P-025: Roof agreement (הסכם גג) with ILA is foundational to NZ urban renewal

**topic_keywords:** [הסכם גג, רמ"י, רשות מקרקעי ישראל, קרקע משלימה]
**request_types_affected:** [תב"ע פינוי-בינוי, התחדשות עירונית]
**status:** verified_policy
**confidence:** high
**evidence_count:** 3+ statements
**first_observed:** 2024-12-16
**last_observed:** 2025-06-03

**Pattern:**
The Mayor frequently invokes the **roof agreement** (הסכם גג) signed
between Ness Ziona and the Israel Land Authority (רמ"י). Its function
in urban renewal: enables ILA to allocate **supplementary land**
(קרקע משלימה) to make individual urban renewal plans economically
feasible. The agreement allows higher unit-percentage allocations
than would otherwise be possible.

The Mayor explicitly **traded off** supplementary land between plans:
"ויתרתי על קרקע משלימה בתכניות אחרות כדי שלתכנית הזו תהיה
התכנות" (I gave up supplementary land in other plans so this plan
would be feasible).

**Direct quotes:**
- Mayor (Nehemia, 03.06.2025): "העירייה חתמה על הסכם גג עם רמ"י"
- Mayor: "ויתרתי על קרקע משלימה בתכניות אחרות כדי שלתכנית הזו
  תהיה התכנות"
- City Engineer (16.12.2024): "אם אין קרקע משלימה לא תהייה תכנית
  בגלל כל המגבלות בשטח"

**Implication for our compliance platform:**
Urban renewal plans in Ness Ziona that depend on supplementary land
should be cross-referenced against the roof agreement allocations.
Plans that assume unlimited supplementary land are unrealistic.

**Open questions for Ellen:**
- Is the text of the roof agreement available?
- Which plans currently have allocated supplementary land vs. which
  are awaiting allocation?

---

## P-026: Sewage capacity constraint at Gan Rave / Shafdan line

**topic_keywords:** [גן רווה, שפד"ן, תחנת שאיבה, קו סניקה, ביוב, מי ציונה]
**request_types_affected:** [תב"ע, היתר בנייה in NW Ness Ziona]
**status:** verified_policy (water/sewage committee finding)
**confidence:** high
**evidence_count:** 1 detailed finding
**first_observed:** 2023-10-24
**last_observed:** 2023-10-24

**Pattern:**
The district committee's water and sewage subcommittee (ועדה מקצועית
למים וביוב) found the **Gan Rave pumping station + suction line to
the Shafdan** has reached capacity. Adding sewage from new development
in Ness Ziona AND Rehovot risks "קריסת הקו... זרימת שפכים גולמיים
לסביבה באזור רגיש סביבתית" (line collapse + raw sewage to
environmentally sensitive area, possibly reaching Sorek stream).

Affected volume: **30,000 cubic meters/day, serving 200,000+
residents** of Ness Ziona and Rehovot.

The committee imposed mandatory conditions on plans 407-1048248
(**our pilot's adjacent plan**) and 407-1087006:
1. The two cities **must urgently** approve and execute a statutory
   plan to upgrade the line, or building restrictions will follow
   in both cities.
2. For Ness Ziona's Histadrut-Hetzeisim plan area 5 (תא שטח 5),
   **no permits will be issued** until existing structures in the
   proposed שצ"פ are demolished and water/sewage lines relocated.

**Direct quote (Water/Sewage committee, 24.10.2023):**
"הקו הגיע למיצוי של כמויות השפכים שניתן להעביר בו ויש חשש ממשי כי
הוספת שפכים משתי הערים לקו תגרום לקריסתו... הערים נס ציונה ורחובות
חייבות לקדם בדחיפות אישור תכנית סטטוטורית ואת ביצוע קו הסניקה
מתחנת שאיבה גן רווה אל השפד"ן"

**Implication for our compliance platform:**
**Directly affects our pilot.** Any plan in plan 407-1048248 area or
adjacent must verify sewage line status. Permits in area 5 of the
plan are conditioned on demolition + relocation work.

**Open questions for Ellen:**
- What is the current status of the Gan Rave → Shafdan line upgrade?
- Has area 5 of plan 407-1048248 had permits issued, and if so,
  under what conditions?

---

## P-027: Cancel road connections that fragment שצ"פ

**topic_keywords:** [שצ"פ, חיבור דרך, רשת דרכים, תחבורה, מתקני אגירה]
**request_types_affected:** [תב"ע, תכנית בינוי]
**status:** observed_pattern (city's stated position)
**confidence:** medium
**evidence_count:** 2 statements
**first_observed:** 2025-06-25

**Pattern:**
The City Engineer and Mayor jointly oppose new road connections
that would cut through public open spaces (שצ"פ) when shared
property buildings, water-retention installations (מתקני אגירה),
or pedestrian infrastructure could be impaired.

The city favors:
1. Pedestrian + bicycle connections instead of vehicle connections
2. **35% modal-split target for public transit** (cited as the
   model used in NE neighborhood traffic studies)
3. Single-entry neighborhood designs (cited Charodi/חרודי plan
   precedent: 1 entry + 65% public-transit split)

The Mayor explicitly opposed a proposed road in plan 407-1087006
(Margolin) because it would: pass adjacent to shared-property
buildings + a shelter, and fragment שב"צ areas.

**Direct quotes:**
- City Engineer: "הכביש חותך שצ"פ משמעותי בשכונה הצפון מזרחי. חותך
  את השב"צ ומגביל את הפיתוח בו"
- Mayor: "לא רוצים לפגוע בשצ"פים שבהם מתוכננים מתקני אגירה"
- Mayor: נתן לדוגמא את התכנית המקודמת חרודי, שם מוצעת כניסה אחת
  לשכונה ופיצול של 65% לתחבורה ציבורית
- City Engineer: "הבדיקה לקחה מודל פיצול מחמיר, 35% בתחב"צ, רוצים
  לייצר את התנועות הרכות ופחות כבישים לכלי רכב"

**Implication for our compliance platform:**
Plans proposing new vehicle road connections through public spaces
or that fragment שב"צ should be flagged. The city's preferred
alternatives — pedestrian/bicycle connectivity, single-entry
neighborhoods with high transit modal split — should be referenced
in compliance review.

**Open questions for Ellen:**
- Is the 35% transit modal-split a written planning standard?
- Is the Charodi/חרודי plan a precedent the city formally endorses?

---

## P-028: Acoustic protection demanded as wall, not earth berm

**topic_keywords:** [קיר אקוסטי, סוללה אקוסטית, מיגון רעש, נספח אקוסטי]
**request_types_affected:** [תב"ע, פינוי-בינוי near major roads]
**status:** observed_pattern (city's stated position)
**confidence:** medium
**evidence_count:** 1 detailed (with 4 sub-demands accepted)
**first_observed:** 2014-10-19

**Pattern:**
For plans bordering major roads or transit corridors, the city
explicitly demands acoustic protection in the form of a **wall
(קיר אקוסטי), not an earth berm (סוללה)**. The city's stated
reasons:
1. Walls are spatially efficient — berms consume large open-space areas
2. Walls can be built incrementally with private building permits
3. Berms create maintenance and aesthetic issues

The city also demands:
- Wall built at the property boundary (גבול המגרשים), not
  midway through the public open space (שצ"פ)
- Wall built **as part of private building permits** (within
  individual plots), funded by developers
- Existing photo references to be respected

**Evidence:**
- Plan 407-0121749 (Northern Approach Ness Ziona, 2014): The
  district committee accepted the city's demand for an acoustic
  wall, with the wall to be located in the שצ"פ adjacent to
  residential plots.

**Implication for new submissions:**
Plans near major roads should anticipate that the city will demand
a wall solution, not a berm. If a submitted plan proposes a berm,
this is likely to face local committee objection.

**Open questions for Ellen:**
- Is there a written city policy on this?
- Are there specifications for acoustic wall design?

---

## P-029: 25%+ small-unit allocation distributed across plots

**topic_keywords:** [יח"ד קטנות, דיור מכליל, פיזור יח"ד, תמהיל]
**request_types_affected:** [תב"ע, התחדשות עירונית]
**status:** observed_pattern (city's stated position)
**confidence:** medium
**evidence_count:** 1 detailed
**first_observed:** 2014-10-19

**Pattern:**
The city demands that small apartments (יח"ד קטנות, typically up
to 55-80 m²) be **distributed across multiple plots** rather than
concentrated in a single building. The city's argument: concentrating
all small units in one structure creates **socio-economic segregation**
and harms neighborhood mixing.

Specific city demand on Northern Approach plan: each residential
plot in residential-C zone must have at least **20% small units**.

**Evidence:**
- Plan 407-0121749 (2014): The district committee accepted this
  demand and amended plan provisions: "בכל אחד ממגרשי המגורים
  ביעוד מגורים ג' יהיו 20% יח"ד קטנות".

**Implication for new submissions:**
Plans concentrating small units in a single building should expect
city objection. The expected pattern is distribution of mixed-size
units across the plan.

**Open questions for Ellen:**
- Is the 20% minimum per plot still city policy?
- How is "small unit" defined now (after Amendment 155)?

---

## P-030: Master drainage/runoff plan (תכנית אב לניקוז) is binding reference

**topic_keywords:** [תכנית אב לניקוז, ניהול מי נגר, חלחול, הצפות]
**request_types_affected:** [תב"ע, היתר בנייה in flood-prone areas]
**status:** verified_policy (cited by city as binding reference)
**confidence:** high
**evidence_count:** 4 statements
**first_observed:** 2014-10-19
**last_observed:** 2026-01

**Pattern:**
The city has a **master drainage plan (תכנית אב לניקוז של נס ציונה)**
that the City Engineer treats as a binding reference for all plans.
The City Engineer demands:
1. Drainage appendix (נספח ניקוז) showing connection to master plan's
   main drainage channel (מובל הניקוז)
2. Drainage design must be coordinated with the city's drainage
   authority (רשות הניקוז המוסמכת)
3. **Pre-existing flooding problems are a constraint**: "התוכנית
   תחמיר את בעיית ההצפות שכבר קיימת" — plans worsening flooding
   will be opposed.
4. Site-level retention solutions (in plot, in שצ"פ) are required;
   drainage to public open spaces is not a substitute for plot-level
   solutions.
5. **Northern Ness Ziona** is treated as a flood-sensitive area —
   the city has built **a 4km × 10m retention wall/berm** to protect
   Yad Eliezer neighborhood. New plans must not eliminate this
   protection.

**Evidence:**
- Plan 407-0121749 (2014): Drainage objections from city accepted
  in part by district committee.
- Plan 407-0730606 NE Ness Ziona (2022): "כל השטח הצפוני של נס
  ציונה משמש היום כשטח הצפה, השכונה תגרום להצפות בישוב במורד
  הנגר". Detailed objection from city engineer about flood
  consequences.
- Plan 407-1087006 Margolin (2026): City engineer required
  hydraulic upgrade and flood-mitigation in Etzel and Ephraim
  streets as condition.

**Implication for new submissions:**
Plans that include drainage components must align with the master
drainage plan. Plans that increase site coverage (תכסית) reducing
infiltration require both site-level retention and a hydrologist's
opinion (see also P-013).

**Open questions for Ellen:**
- Has the master drainage plan been updated since 2022?
- Where is its formal text accessible?

---

## P-031: Local committee will appeal district decisions when not heard

**topic_keywords:** [ערר, ועדת המשנה לעררים, התנגדות הועדה המקומית, סירוב הוועדה]
**request_types_affected:** [תב"ע]
**status:** observed_pattern
**confidence:** high
**evidence_count:** 3 documented appeals
**first_observed:** 2014-10-19
**last_observed:** 2022-09-18

**Pattern:**
The Ness Ziona local committee has a documented history of formally
appealing district committee decisions when the city's substantive
objections are dismissed. Examples:

1. **Plan 407-0121749 (Northern Approach)** — Local committee was
   the formal objector. After district approval, the local committee
   appealed to the National Council's appeals subcommittee. The
   appeal was rejected, but the city continued to delay by withholding
   document signatures, requiring 90-day extensions.
2. **Plan 407-0139295 (Kfar Aharon, נס/155)** — Same pattern. Local
   committee filed appeal after objection rejection. Appeal rejected
   nationally. City continued to withhold signatures, requiring
   extensions.
3. **Plan 407-0730606 (Northeast Ness Ziona)** — On 10.8.2021, the
   local committee formally voted to **recommend rejection** to the
   district committee until roof agreement was signed and corrections
   made.

This pattern shows the city uses every available procedural lever
to push back on plans it disagrees with — even after objection
hearings, even when appeals are unlikely to succeed.

**Direct quote from 2014 hearing chair:**
"בנסיבות העניין מאחר ומדובר בתכנית למגורים, בעלת חשיבות, שקודמה
במשך שנים על ידי המדינה ובשל הנסיבות המיוחדות של קידומה של
התכנית... מחליטה הועדה להאריך את מועד ההחלטה למתן תוקף ב-90
ימים נוספים"

**Implication for our compliance platform:**
Plans that the local committee has formally objected to or
recommended rejection should be cross-referenced — they may be
in extended limbo even after district approval. Documents from
these plans may have non-standard timelines.

**Open questions for Ellen:**
- Is this list of appeals comprehensive, or are there others?
- What's the current status of plans 407-0121749 and 407-0139295?

---

## P-032: Roof agreement (הסכם גג) as condition has been rejected by district committee

**topic_keywords:** [הסכם גג, רמ"י, תנאי לאישור תכנית, היטל השבחה]
**request_types_affected:** [תב"ע, פינוי-בינוי]
**status:** verified_policy (district position; city continues to demand)
**confidence:** high
**evidence_count:** 2 explicit rejections by district
**first_observed:** 2022-09-18
**last_observed:** 2022-09-18

**Pattern:**
Ness Ziona has repeatedly **demanded that plan approval be
conditioned on signing a roof agreement (הסכם גג) with ILA**. The
district committee has repeatedly **rejected this demand** as
mixing planning with administrative-economic arrangements:

"אין לקשור בין הליכי תכנון לבין הסדרים מינהליים-כלכליים בין
הרשות המקומית (עיריית נס ציונה) לבין רמ"י"

The city's argument: without roof agreement, infrastructure cannot
be funded, and the plan creates obligations the city cannot meet.

**Evidence:**
- Plan 407-0730606 NE Ness Ziona (2022): City demanded roof
  agreement as condition. District rejected.
- Plan 407-1048248 Hetzeisim (our pilot, 2023): Same pattern via
  water/sewage subcommittee — line upgrade made a permit condition
  without specific roof agreement requirement.

**Implication for our compliance platform:**
The city's roof-agreement-first position has not prevailed at
district level. However, infrastructure conditions (sewage, water,
roads) are routinely imposed. Reviewers should track which
infrastructure obligations apply to specific plans.

**Open questions for Ellen:**
- Has the city changed its strategy on roof agreement linkage?
- Which plans have signed roof agreements vs. pending?

---

## P-033: Indemnity letter (כתב שיפוי) demand rejected at district level

**topic_keywords:** [כתב שיפוי, תביעות נגד העירייה, פגיעה תכנונית]
**request_types_affected:** [תב"ע]
**status:** observed_pattern (city demand consistently rejected)
**confidence:** medium
**evidence_count:** 1 explicit rejection
**first_observed:** 2022-09-18

**Pattern:**
The city has demanded **indemnity letters (כתב שיפוי)** from plan
sponsors as a condition for approval, to protect the city against
future compensation claims. The district committee rejected this in
plan 407-0730606 with the standard reasoning that indemnity letters
are exceptions, not the rule, and require demonstration of specific
foreseeable harm. The city was unable to demonstrate this concrete
harm beyond general claims.

**Direct quote from district decision:**
"כתב שיפוי הינו החריג לכלל ויש לשקול את ההצדקה לכתב שיפוי לפי
השיקולים שהותוו בפסיקה... הועדה המקומית לא הצביעה על הפגיעה
האפשרית מהתכנית המצדיקה הפקדת כתב שיפוי מעבר לטענות כלליות"

**Implication for our compliance platform:**
The city's indemnity-letter demand pattern is unlikely to succeed
unless backed by specific demonstrable harm. Plans where the city
has demanded this should be flagged.

---

## P-034: 12-story height cap at boundaries with existing low-rise neighborhoods

**topic_keywords:** [גובה בנייה, מגבלת גובה, תפר בין שכונות, יד אליעזר, 12 קומות]
**request_types_affected:** [תב"ע, פינוי-בינוי]
**status:** observed_pattern (city's stated position from prior agreement with residents)
**confidence:** medium
**evidence_count:** 1 detailed (with prior-agreement reference)
**first_observed:** 2022-09-18

**Pattern:**
The city has **prior commitments to residents in established
neighborhoods** that new construction at the boundary will be
capped at **12 stories**. The city raises this commitment as a
binding constraint when adjacent plans propose taller buildings.

In plan 407-0730606, the city said:
"ישנו סיכום עם הדיירים בשכונת יד אליעזר שהבינוי שגובל בשכונה
יהיה עד 12 קומות. בממשק בין השכונה החדשה לקיימת מבקשים שהגובה
לא יעלה על 12 קומות"

The district committee partially rejected this constraint, citing
that adjacent neighborhoods may also undergo urban renewal in the
future, and that 9-story buildings already exist nearby.

**Implication for our compliance platform:**
Plans bordering established residential neighborhoods may have
informal city commitments on building heights that aren't visible
in statutory text. Reviewer should verify with the city engineer
whether boundary height commitments exist for the specific plan
location.

**Open questions for Ellen:**
- Is there a written record of these boundary commitments?
- Which neighborhoods have 12-story (or other) caps?

---

## P-035: Sub-3.5m floor-to-floor height standard

**topic_keywords:** [גובה קומה, 3.5 מטר, גובה מבנה]
**request_types_affected:** [תב"ע, היתר חדש]
**status:** observed_pattern (technical correction city demanded)
**confidence:** medium
**evidence_count:** 1 detailed
**first_observed:** 2014-10-19

**Pattern:**
For residential buildings, the city expects floor-to-floor heights
to be calculated at **3.5m per story plus 5% margin if needed**.
When statutory plan text inconsistently specifies number of floors
vs. total building height, the city demands recalculation per this
standard.

Specifically in plan 407-0121749 (2014): plots with **13 stories
were approved at 63m height** = exactly 3.5m × 13 + 4.85m margin
(roughly 7.7%).

For low-rise residential (single family), the city specifies:
- Standard: 11m maximum height
- Special low-rise plots: 9m maximum

**Evidence:**
- Plan 407-0121749 (2014): District committee accepted city's
  recalculation request: "גובה המבנים בייעוד מגורים ב+ ג' יתוקן
  כך שגובה המבנה יהיה לפי 3.5 מטר לקומה בתוספת 5% לגובה ככל שידרש".

**Implication for our compliance platform:**
For plan compliance review, building heights should be cross-checked
against floor count × 3.5m. Submissions exceeding this without
explanation may face city objection.

---

## P-036: Maximum 400m² individual store size in mixed-use plans

**topic_keywords:** [מסחר, גודל חנות, חזית מסחרית, מסחר נלווה]
**request_types_affected:** [תב"ע, פינוי-בינוי]
**status:** verified_policy
**confidence:** medium
**evidence_count:** 1 specific city-driven cap
**first_observed:** 2014-10-19

**Pattern:**
For mixed-use plans (residential with commercial frontage), the
city's stated policy: **maximum individual store size of 400m²
of main area (עיקרי)**. The city's reasoning: protect the
city-center commercial district from competition by large
suburban retailers.

In plan 407-0121749, the city objected to 1,400m² total commercial
allocation, arguing it threatened city-center commerce. The district
committee partially accepted: total commercial allocation kept at
1,400m² but individual store size capped at 400m².

**Evidence:**
- Plan 407-0121749 (2014): "הוועדה קובעת כי גודל חנות מקסימלי
  יקבע על 400 מ"ר עיקרי"

**Implication for our compliance platform:**
Plans proposing individual stores larger than 400m² in
neighborhoods with mixed-use designation should be flagged for
city review. The city protects city-center commerce from
suburban large-format competition.

**Open questions for Ellen:**
- Is the 400m² cap still city policy, or has it been updated?
- Are there exceptions for specific store types (supermarkets,
  pharmacies)?

---



## Open issues and methodology notes

### What this file does NOT yet cover

Even after reading all 36 protocols in the corpus, several topics remain
unobserved or under-sampled:
- **Apartment mix policy** for high-rise / multi-unit projects
  (תמהיל יח"ד for new construction). Mostly seen in district-committee
  documents attached to plenary protocols, not local committee
  decisions.
- **Urban renewal (פינוי-בינוי)** — entirely absent from corpus.
  May be handled at plenary level or in separate committee structures.
- **Public buildings (שב"צ)** — only two projects observed
  (Garden of Remembrance, MDA station, school).
- **Heritage preservation** / specific neighborhood policies.
- **Daycare integration** policies in residential designs.
- **Detailed parking ratio policies** beyond accessible parking
  designation.

### How to extend this file

When new protocols become available:
1. Check if pattern matches existing P-NNN entry. If yes, add evidence.
2. If no, add new P-NNN entry with same structure.
3. If pattern is contradicted by new decision: flag the contradiction
   in prose. Don't silently overwrite.

### Verification protocol

Before any of these patterns become "trusted" in the platform:
1. Ellen reviews each entry and confirms or rejects.
2. Confirmed entries: `observed_pattern` → `verified_policy` with
   `confidence: high`.
3. Rejected entries: removed, with explanatory note.
4. "I don't know" entries: stay `observed_pattern` with re-discussion
   flag.

### Verified resolutions catalog

| Resolution | Date | Topic | Plan reference |
|---|---|---|---|
| 202203 | 2022-05-17 | Pool setback to 1.0m | (procedural) |
| (unnamed) | 2020-11-30 | Balcony 30% + 6% area | 407-0867242, ס/מק/13/1 |
| 202508 | 2025-07-30 | Concessions for low-rise (supersedes 2020) | 407-1459544 |
| 202101 | (date unknown) | TMA-38 local extension to 18.05.2025 | (procedural) |

Each would benefit from acquiring the full text — possibly from Ellen,
the local committee meeting archive, or the plan archives.

### Procedural patterns observed

- **Protocol types in corpus**:
  - **רשות רישוי** (licensing authority) — ~25 of 36 protocols.
    Mostly straightforward "approve subject to compliance" decisions.
    Few concession debates, mostly procedural patterns (P-006, P-016,
    P-017, P-018, P-019).
  - **ועדת משנה** (subcommittee) — ~10 of 36 protocols. Substantive
    concession debates (P-002, P-003, P-007, P-010 originate here).
  - **מליאת הועדה** (plenary) — 1 of 36. District-level statutory plans;
    less directly relevant to building permits.
- **Vote structure**: Subcommittee decisions track each member's vote
  individually when there's dissent. Standard members in 2025-2026:
  Amos Logasi (chair), Smadar Aharoni, Omri Revah, Gil Anukov,
  Yehuda Chimovitz, Eran Rafael, Itay Dagan.
- **Document structure**: Most cases follow: מהות הבקשה → הערות בדיקה
  → המלצות מהנדס העיר → מהלך דיון → החלטות → גליון דרישות (~30-50
  items per approval).

### Decision distribution observation

The corpus is **overwhelmingly approvals**. Out of ~250 cases observed:
- ~95% approvals (with or without conditions/concessions)
- ~3% rejections (mostly clear-cut: בנייה בדיעבד, missed deadlines)
- ~2% deferrals or partial approvals

This implies that the licensing pipeline filters out problem cases
before they reach the committee — most rejections happen earlier in
the review-comments stage. The committee mostly serves to (a) approve
clean applications, (b) approve concessions with reasoning, (c) defend
prior policy resolutions.
