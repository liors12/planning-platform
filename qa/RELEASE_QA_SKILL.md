# RELEASE QA SKILL — the per-release procedure

Distilled from the 2026-07 QA campaign (see QA_CAMPAIGN.md for the full
history). Run this top-to-bottom before every tagged release. A release is
GO only when every layer below is green (or its failure is a documented
dev-only backlog item) AND the manual VM checklist passed.

## 0. Preconditions

- main is the release candidate; all feature/fix PRs merged, working tree clean.
- Local: macOS dev machine with `/opt/homebrew/bin/python3.13`, the 100MB
  pilot PDF at `projects/407-1048248/submissions/v24.3/v24.3.pdf`
  (uncommitted, local-only — real-engine specs skip honestly without it).
- CI: `.github/workflows/qa-suite.yml` (layer 0 + UI suite) and
  `build-windows.yml` (bundle + 49 API probes) must be green on the main tip.

## 1. The five layers (in order — cheap gates first)

| Layer | What | How to run |
|---|---|---|
| 0a | Em/en-dash gate (Ellen's style: plain hyphens only) | `python3.13 -m pytest tests/test_no_emdash.py -q` |
| 0b | Jargon lexicon gate (no technical Hebrew/English leaks) | `python3.13 -m pytest tests/test_jargon_lexicon.py -q`; lexicon `qa/jargon-lexicon.txt`, whitelist `qa/jargon-whitelist.txt` |
| 1 | Per-screen states + affordances + DOM-leakage afterEach | `cd tests/ui-dev && npx playwright test 00-layer1` (leak markers live in `tests/fixtures.ts`) |
| 2 | Viewport matrix 1024x700 + 1280x800 (no overflow, no clipped labels) | `npx playwright test 01-layer2` |
| 3 | Screenshots + codified judgment (LOOK at them; committed under `tests/ui-dev/screenshots/`) | `npx playwright test 02-layer3`, then open the PNGs |
| — | Flow specs F1-F6 (guidelines edit→enforce, create, upload, real audit, findings, report) | `npx playwright test` (whole dir = layers 1-3 + flows, 18 specs) |
| — | Round-1 regression suite | `cd tests/ui-fixes && npx playwright test` |
| — | Full pytest | `python3.13 -m pytest tests -q` (B-7: 3 known dev-only determinism failures are acceptable) |
| 4 | Manual VM checklist (below) — the packaged app on real Windows | human, ~10 minutes |
| 5 | Process: triage → fix-or-backlog → re-run → tag | this document |

The Playwright harness wipes and re-seeds its own data dir every run
(`tests/ui-dev/playwright.config.ts` webServer command) — every suite run is
a fresh-install simulation. Never point it at real data.

## 2. Standing rules

- **Red-green rule.** No test counts as evidence until it has been seen to
  FAIL for the right reason. New test: sabotage the code (or assert against
  the pre-fix build) → red → restore → green. A test born green is a
  suspect, not a witness.
- **The fake-test lesson (spec-4 race).** Spec 4 originally asserted
  `data-status == "complete"` and passed in 2.5s against a *sabotaged*
  engine — the seed ships the pilot as complete, so the assert never tested
  the run. The fix: require the observable *transition* (`analyzing` →
  `complete`), not the end state. Generalize: whenever the seed (or any
  fixture) can pre-satisfy your assertion, assert the state CHANGE.
- **FLAG → backlog.** Anything ambiguous found while testing gets a B-n
  entry in QA_CAMPAIGN.md instead of an inline "probably fine". Blocks-Ellen
  → fix now; cosmetic/dev-only → backlog, never silently dropped.
- **New convention → new gate.** Every time a wording/style convention is
  established (e.g. "no em-dashes", "no סכמה"), it becomes a Layer-0 gate
  the same day, with a planted-violation self-test proving the gate fires.
- **Selectors:** data-testid / data-check-key only; never getByText() on
  Hebrew copy.
- **Hebrew-only UI.** Any English or technical string reaching the screen is
  a bug (ErrorNotice's פרטים טכניים collapsible is the ONLY sanctioned
  place for raw error text).

## 3. Regression checklist — the 9 bug families from the first hands-on session

Every one of these was a REAL finding on the packaged app (round 1,
2026-07-22). They are automated now, but re-check them consciously whenever
touching adjacent code:

1. Dashboard pipeline pills: zero-count stages muted, nonzero emphasized.
2. Em/en dashes anywhere in UI copy (gate 0a).
3. Jargon leaking to Ellen — "סכמת בדיקה", module names, English errors (gate 0b).
4. Upload form breaks at narrow widths (layer 2).
5. Button rows clip/overflow instead of wrapping (layer 2 + round1 item 5).
6. Findings tab: raw HTTP 409 instead of a friendly state (F-1 — now seeded
   consistent + friendly fallback pinned by route-interception test).
7. CAD scan enabled with no DXF uploaded → raw 422 (must be disabled + hint).
8. Raw API/fetch error strings rendered directly (must route through
   ErrorNotice / MaybeApiError).
9. Sidebar footer pushed off-screen at 1024x700 (must stay pinned).

## 4. Layer 4 — the 10-minute manual VM checklist

Run on the Windows VM against the freshly built installer, INSTALLING OVER
the previous version (that is Ellen's actual upgrade path — never test only
clean installs). Default window size as the installer opens it — do not
maximize first.

| # | Checkpoint | Pass looks like |
|---|---|---|
| 1 | Install over existing version, launch | App opens; no error dialog; previous projects and their submissions still listed |
| 2 | Default window size sanity | Sidebar footer (הנחיות/הגדרות) visible without resizing; no horizontal scrollbar |
| 3 | Dashboard | Pilot project card shows; pipeline pills correct (nonzero emphasized) |
| 4 | Findings tab on the pilot | Findings render immediately (three sections, Hebrew); NO raw English/HTTP text anywhere |
| 5 | Guidelines | Sections collapsible in document order; edit a checkable value → גרסה +1; היסטוריה shows both; הורדת PDF downloads a styled PDF |
| 6 | Upload + engine | New version upload works; הפעילי את התוכנה enabled only with schema data; run reaches מנתחת then הושלם |
| 7 | Report + Excel | הפיקי דו"ח produces the banner and a PDF that opens; Excel export opens in Excel |
| 8 | Hebrew-only sweep | Click through Settings, CAD tab, comments; feminine imperatives everywhere; פרטים טכניים is the only place raw text may hide |

Findings from this checklist follow rule "FLAG → backlog": blocks-Ellen →
stop the release, fix, rebuild, redo the checklist; cosmetic → B-n entry and
proceed.

## 5. Release mechanics

1. Confirm `Build Windows Installer` green on the main tip (the only
   tolerated red is the known non-fatal cleanup check).
2. Tag: `v0.1.0-<yyyymmdd>-<short-sha>` on the main tip, push the tag.
3. Wait for the tagged build; verify the GitHub Release exists, has the
   `.exe` asset, and the direct download URL answers 200.
4. Note: releases are marked Pre-release, so `/releases/latest` does NOT
   resolve — always hand Ellen the direct asset URL.
5. Run the Layer-4 VM checklist on the downloaded artifact before telling
   anyone the release is ready.
