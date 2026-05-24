# Known issues — dev mode quirks + Phase 5 to-dos

Things we've decided NOT to fix right now, with the reasoning and the
trigger that would bump them up the priority list. Each entry is keyed
to a Task ID so the connection between the markdown and the in-flight
todo list is explicit.

---

## Task #10 — `curl … -sS` readiness checks missing `--fail`

**Symptom**: a readiness probe (`curl -sS …`) returns exit `0` even when
the server replied `5xx`. The script concludes "server is healthy" and
moves on. Downstream caller hits the same endpoint and gets a 500.

**Why**: `-sS` only controls progress/error verbosity. Without `--fail`,
curl exits `0` for any HTTP response that came back at all — only
transport-level failures (connection refused, DNS, etc.) return
non-zero.

**Audit results (2026-05-19)**:

| Location | Before | Status |
|---|---|---|
| `scripts/prep_cowork_session.sh:117` (Vite up) | `curl -sS --max-time 1` | **Fixed** — now `--fail` |
| `scripts/prep_cowork_session.sh:221` (sidecar /health, in retry loop) | `curl -sS --max-time 1` | **Fixed** — now `--fail` |
| `scripts/prep_cowork_session.sh:229` (sidecar /health, final assertion) | `curl -sS --max-time 1` | **Fixed** — now `--fail` |
| `app/README.md:66` (dev `/health` example) | `curl -sS …\| json.tool` | **Fixed** — now `--fail` |
| `docs/phase_1_completion.md:88` (historical phase-1 snapshot) | `curl -sS …` | **Left as-is** — historical doc, never re-executed, fixing would falsify the snapshot |
| `app/README.md:35` (rustup install) | `curl -sSf …` | OK — already has `-f` (the `f` in `-sSf` IS `--fail`) |

**Going forward**: every new readiness/health check in shell must use
`curl --fail -sS`. Add it to any future doc that demos a curl-and-pipe
pattern. The `prep_cowork_session.sh` smoke test added under Task #11
also uses `--fail`.

---

## Task #12 — `prep_cowork_session.sh` wedges on exit (Vite pipe leak)

**Symptom**: after the script reaches `echo READY …`, the bash process
stays alive in `__wait4` forever. The pipe to whatever caller invoked
the script (e.g. `bash prep_cowork_session.sh | tail -40`) never EOFs,
so the caller hangs too. Manual fix: `kill -9 <bash pid>`.

**Root cause**: the script backgrounds Vite via:

```bash
(
  cd "$FRONTEND_DIR" && npm run dev > "$VITE_LOG" 2>&1
) &
VITE_LAUNCHER_PID=$!
```

The subshell `(…)` is forked while bash's stdout is still connected to
the caller's pipe. The redirect `> "$VITE_LOG"` rebinds fd 1 inside the
subshell, but the originally-open pipe fd is still inherited via the
fork. `npm` therefore keeps the pipe's write end open. When bash itself
exits, the kernel keeps the bash process alive because some child holds
an fd that bash wrote to. (Approximate description — actual mechanics
involve job-control + `__wait4` on the subshell PID.)

**Workaround in use today**: after the first prep run that wedges,
identify the bash PID (`pgrep -f prep_cowork_session.sh`), `kill -9`
it. Wrapper, Vite, and sidecar are reparented to launchd and survive.

**Real fix (deferred)**: detach the Vite subshell with `nohup` /
`setsid` AND close fd 0/1/2 in the subshell explicitly:

```bash
nohup setsid bash -c "
  cd '$FRONTEND_DIR' && exec npm run dev
" </dev/null >"$VITE_LOG" 2>&1 &
```

Why deferred: the workaround is one `kill -9` per session. Three
follow-ups (`#9`, `#10`, `#11`) ranked higher; the wedge fix queued
behind them. Re-prioritise if it breaks a Cowork session more than
once a week.

---

## Task #13 — Dev wrapper dies on screen lock / sleep

**Symptom**: leave the dev wrapper running, let macOS auto-lock the
screen, come back: wrapper PID is gone, sidecar (its child) is gone,
ports 17321 + 1420 may or may not be free. We saw this in the
2026-05-19 debugging session — the wrapper died sometime between
`12:33` (when we last `curl`ed /health = 200) and `12:40` (next
screenshot showed cached state with no process).

**Theory**: `cargo build` debug binaries are not signed with the
entitlements that let an app survive `loginwindow` lock. macOS may also
send SIGSTOP / cancel WebKit XPC connections aggressively for unsigned
apps during lock.

**Workaround in use today**: re-run `prep_cowork_session.sh` (or
manually `open -n target/debug/Planning Platform Dev.app`) when
returning to the machine. Bring the user back to a fresh window.

**Phase 5 acceptance**: a SIGNED production `.app` MUST survive:
1. Screen lock + 5 min idle + unlock — sidecar still healthy, UI still
   shows project list.
2. System sleep + 30 min idle + wake — same.
3. Mac restart with the app in Login Items — opens to working state.

If any of these fail in the signed bundle, Ellen will open the app one
morning to a stale window and won't know whether to click around or
restart. Test all three before shipping the first dmg.

---

## Task #14 — Startup race: WebView fetch before sidecar binds 17321

**Symptom (pre-fix)**: opening the wrapper would briefly show
`TypeError: Load failed` in the sidebar + recent-projects card. The
error sometimes persisted on screen even after the data loaded
successfully, because the React state held the failed-fetch error
across the successful retry.

**Root cause confirmed 2026-05-19**: in `app/tauri/src/lib.rs`,
`setup()` calls `spawn_sidecar()` and returns immediately. The WebView
loads `devUrl` in parallel. The React app's `useEffect` fires
`listProjects()` in milliseconds. The Python sidecar takes 1–3 s to
import FastAPI + bind 17321. The first fetch lands on an empty port
and rejects with `TypeError: Load failed`.

**Phase 2b fix (shipped)**: two-part, lives in `app/frontend/src/api.ts`
+ components:

1. **`fetchOrThrow` with retry + backoff** — 3 retries after the first
   failure, waits 200 ms / 500 ms / 1500 ms between attempts. Total
   wait before giving up: ~2.2 s, which is comfortably above the
   observed sidecar boot time. AbortError is not retried.
2. **`setErr(null)` on success** — Sidebar, Home, ProjectWorkspace all
   clear their error state in the success path so a stale
   `TypeError: Load failed` doesn't linger next to data from the
   eventual successful retry.

**Phase 5 production fix (TODO)**: gate `window.show()` in `lib.rs` on
sidecar `/health 200`. Once that lands, the React app physically
cannot observe the race because the WebView won't begin loading until
the sidecar is ready. Belt + braces — keep the retry as well, for
transient sidecar restarts during use.

---

## Task #17 — `screencapture` Screen Recording perm gap

**Symptom**: `screencapture` invoked from the bash context my agent
runs in returns ONLY desktop wallpaper + menu bar. Application window
contents (Tauri wrapper, Chrome, anything) render as empty/transparent
in the captured image, even when those windows are visibly open and
focused on screen.

**Theory**: macOS 14+ requires per-app Screen Recording permission
under System Settings → Privacy & Security → Screen & System Audio
Recording. The shell that invokes `screencapture` for the agent
doesn't have it, so the compositor blacks out content from any
application not granted to that shell.

**Workaround in use today**: drive Chrome via the `claude-in-chrome`
MCP for visual verification (its grants are independent and it
captures via DevTools Protocol, not `screencapture`). Playwright also
works — its headed Chromium has its own capture path that doesn't go
through `screencapture`.

**Real fix (low urgency)**: grant Screen Recording to whichever shell
host the agent uses. Until then, never rely on `screencapture` from
agent bash for window content — only for menu bar / desktop snapshots
that don't need an app's window.

---

## Task #18 — React key collision: `rule_code=CONTENT_UNIT_COUNT`

**Symptom**: in `FindingsView.tsx`, the rules-list `.map()` keys each
`<FindingRow>` by `r.rule_code`. Two rules in the content section emit
the same `rule_code = "CONTENT_UNIT_COUNT"`, triggering the React
warning `Encountered two children with the same key`. The UI still
renders, but React may drop / duplicate identity on re-renders, which
can flicker drawer state or cause stale highlights.

**Diagnosis pending (Task #18 Phase 2)**: same rule reported twice
(engine dedup bug) vs. two distinct rules with accidentally identical
code (rename one). The fix path depends on which.

**Workaround**: none today — the warning is benign as long as the
content section's rules are read-only. Becomes user-visible if /when
we add row-level state (e.g. "marked for follow-up") that needs
stable identity.

---

## Task #19 — Dev-mode console 404 (favicon or source-map)

**Symptom**: `Failed to load resource: the server responded with a status
of 404 (Not Found)` shows in the Playwright console capture when loading
`http://127.0.0.1:1420/` in dev. Surfaced during Step 8 verification re-
runs of Task #18, but predates the fix — same error appears on a clean
checkout the moment a Playwright/DevTools console listener is attached.

**Workaround in use today**: ignore. The 404 doesn't affect rendering or
data flow — sidebar, recent projects, findings tab, PDF jump, drawer,
all behave normally.

**Real fix (deferred)**: identify the asset. Likely candidates:
1. `favicon.ico` — not present at `app/frontend/public/`. Add an icon or
   a `<link rel="icon" data:,>` no-op in `app/frontend/index.html`.
2. A source-map reference (`.js.map`) emitted by Vite for a vendored
   library that ships without source-maps.
3. The Tauri-injected runtime fetching a probe URL.

Reproduce with:
```bash
/tmp/pw_venv/bin/python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.on('console', lambda m: m.type == 'error' and print(m.text))
    page.on('requestfailed', lambda r: print('FAIL', r.url))
    page.goto('http://127.0.0.1:1420/', wait_until='networkidle')
    b.close()
"
```
The `requestfailed` listener will name the URL.

---

## Task #21 — Stale orphan directory at `/Users/liorlevin/Desktop/:planning-platform:`

**Symptom**: a second directory `:planning-platform:` (literal colons) sits
on the Desktop next to the real repo `planning-platform`. It holds only 3
files — none of the actual project. Surfaced during git-init prep when the
shell's cwd was found pointing at the orphan instead of the real repo.

**Origin**: leftover from the historical colon-path bug (the repo was once
at a colon path that broke cargo's DYLD resolution; it was renamed to the
clean `planning-platform`, but the colon directory was never deleted).

**Risk**: a shell that lands in the orphan by accident will run git / build
commands against the wrong tree. Pre-flight `pwd` checks catch it, but the
directory should not exist at all.

**Resolution**: scheduled for deletion **after** the git-init + commit
sequence completes (deferred so nothing is destroyed mid-versioning). Once
`phase-2b-v1` is tagged and pushed:
```bash
rm -rf "/Users/liorlevin/Desktop/:planning-platform:"
```
Verify first that it still holds only the 3 stray files and nothing was
added to it since.

---

## Task #22 — Source documents in data/ not version-controlled

Severity: medium · Target: Phase 4 · Blocking: no

Excluded ~53MB of source PDFs/JPGs/rasters under data/ from version
control to keep the repo lean. These are public records (planning
authority documents) but their loss would be costly to recover.

Before Phase 4: establish a backup strategy. Options to evaluate:
  - Git LFS for binary attachments
  - External backed-up mount (Dropbox/Drive symlink into data/)
  - Separate sync script to authoritative source

---

## Task #24 — Monitor src/corpus/ size; evaluate Git LFS at 200 MB

Severity: low · Target: when triggered · Blocking: no

`src/corpus/fixtures/` currently holds 20 Tel Aviv planning-case PDFs
(~61 MB) committed directly to git. The corpus is intentionally frozen
(re-downloading via `src/corpus/mass_download.py` would risk drift in
upstream case availability), so the binaries stay in the repo.

**Trigger:** if `du -sh src/corpus/` crosses **200 MB**, evaluate
migrating those binaries to Git LFS. Smaller corpora can live in plain
git without much friction; past ~200 MB the clone time and shallow-fetch
ergonomics start to bite.

Re-check after any new batch of corpus PDFs is added.

---

## Task #26 — Migrate `google-generativeai` → `google-genai` (post-M0)

**Symptom**: `vision_scanner/clause_inventory/extract.py` imports
`google.generativeai`, which prints a `FutureWarning` on every run:

```
All support for the `google.generativeai` package has ended. It will no
longer be receiving updates or bug fixes. Please switch to the
`google.genai` package as soon as possible.
```

**Root cause**: Google replaced the SDK. The old package still works for
`gemini-2.5-pro` calls today, but receives no fixes — any future server
behavior change or quota / auth tweak could break us with no recourse.

**Workaround in use today**: keep using the deprecated SDK for M0. It
works correctly with `response_schema=ClausesResponse`, key rotation on
429, and `usage_metadata`.

**Real fix (deferred)**: swap to `google-genai`. The new API surface
differs (client object instead of module-level `configure`, different
generation-config shape, different exception classes) — touching
`config.py` (rotator) and `extract.py` (call site + 429 handling). Add
a regression run against `canonical_clauses.json` to confirm the new
SDK produces a faithfully-comparable output before deleting the old
import. Not blocking M0 acceptance.

---

## Task #27 — Design-doc to takanon plot-number reconciliation (M2 scope)

**Discovered:** 2026-05-23 during M1 round 2 verification of page 13.

**Issue:** The design document (v24.3) uses a plot-numbering scheme distinct from the takanon's:
- Takanon plot designations: 1-10 (residential, public, road), 20 (path)
- Design document labels: "ת.ש 52", "ת.ש 64", and similar — likely cadastral parcels or architect's internal subdivision codes

**Implication for M2:** Unified extraction must reconcile design-doc plot refs with takanon plot designations before compliance checking can proceed. Likely needs a project-level mapping table (manually curated or derived from page-by-page evidence).

**Out of scope for M1.** M1 captures plot refs as visibly printed; M2 does the reconciliation.

**Status (2026-05-24):** Confirmed as M2 scope during PDF design/coverage audit. M1 captures design-doc plot refs as visibly printed (ת.ש 52, 64, etc.); M2's unified extraction will reconcile against takanon plot designations 1-10/20.

---

## Resolved — PDF report design version

**Date:** 2026-05-24

**Context:** Two CSS templates existed in the repo: `v6_design_reference (1).html` (white cover, "בהגשה" column) and `v6_design_reference (2).html` (dark green cover, "בתוכנית עיצוב" column). `report_generator.py:3` was updated to use v2 sometime between May 17 and May 24. Lior reviewed both side-by-side and approved v2 as the canonical design.

**Decision:** v2 is the canonical PDF design. `v6_design_reference (1).html` can be removed or archived. Future PDF iterations build on v2.

**Specifics of approved v2 design:**
- Cover: dark green full-bleed background
- Brand color (NZC green #005030) used as accent + background
- Section 2 table column header: "ממצא בתוכנית עיצוב"
- Footer format: "מינהלת התחדשות עירונית נס ציונה — סקירת תוכנית עיצוב N / M"
- Appendix A with title page + content pages

---

## Task #28 — Easements category has 0 implemented rules (M2 scope)

**Discovered:** 2026-05-24 during PDF design/coverage audit

**Issue:** M0 canonical_clauses.json identifies 8 normative clauses in the `easements` category. The current compliance engine has zero rules checking any of these clauses. Submissions with easement-related issues will never be flagged.

**Implication:** M2 must implement rule_code coverage for the 8 easement clauses, OR explicitly document why each is non-checkable (e.g., requires DWG parse, requires manual review).

**Out of scope for M1.**

---

## Task #29 — Phasing category has 0 implemented rules (M2 scope)

**Discovered:** 2026-05-24 during PDF design/coverage audit

**Issue:** M0 identifies 3 normative clauses in `phasing`. Zero corresponding rules. Same pattern as Task #28.

**Out of scope for M1.**

---

## Task #30 — Phantom findings for unsubmitted plots (policy decision)

**Discovered:** 2026-05-24

**Issue:** v24.3 submitted designs for plots 1-5 only. The takanon defines plots 6-10 as well. The current engine flags "missing" plots 6-10 with findings. This is arguably correct (the architect should know they haven't covered the full takanon scope) but could also be noise (those plots may be intentionally deferred).

**Policy decision needed:** Should findings for unsubmitted plots be:
- (a) Flagged loudly (current behavior)
- (b) Suppressed unless explicitly requested
- (c) Shown in a separate "scope gap" section

**Out of scope for M1.** Need Lior + Ellen's input before M2.

---

## Adding entries

When you defer a fix here, follow this template:

```
## Task #N — <one-line symptom>

**Symptom**: ...
**Root cause**: ...
**Workaround in use today**: ...
**Real fix (deferred)**: ...
```

Always link to the Task ID so the in-flight todo list and the
documented backlog don't drift.
