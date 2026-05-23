#!/usr/bin/env bash
# prep_cowork_session.sh — bring up a clean Phase 2b dev session that Cowork
# can access via LaunchServices.
#
# THE CORE PROBLEM (see docs/dev_setup.md for the full story):
#
#   `cargo tauri dev` produces a bare Mach-O binary at
#   `target/debug/planning-platform` — NOT a .app bundle. macOS only gives
#   each .app a bundle identifier (via Info.plist). A bare binary has no
#   Info.plist, hence `osascript ... get bundle identifier` returns
#   `missing value`, and Cowork's `request_access` (which filters at the
#   LaunchServices layer) can't grant screenshot access.
#
# THE FIX:
#
#   We build the binary normally via `cargo build` and Vite via `npm run
#   dev`, then wrap the binary in a thin `.app` bundle at
#   `app/tauri/target/debug/Planning Platform Dev.app/` whose Info.plist
#   carries `CFBundleIdentifier = co.nessziona.planning-platform.dev`.
#   Launching that .app puts the process in LaunchServices with the
#   identifier set, so Cowork can request_access on it.
#
#   The .app is a thin wrapper — its MacOS/planning-platform is a symlink
#   to the actual binary. No code duplication, no extra build steps when
#   the frontend changes (Vite HMR still works).
#
# Usage:
#   bash scripts/prep_cowork_session.sh
#
# Exit codes:
#   0  — window up, identified, ready for Cowork
#   1  — stale .app shadowing — manual deletion needed (we abort to never
#        let a stale build silently steal LaunchServices traffic)
#   2  — Vite never came up
#   3  — cargo build failed
#   4  — wrapper .app launched but process never appeared
#   5  — sidecar /health never responded
#   6  — frontend fetch path broken (CORS / route / serialization on /projects)

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAURI_DIR="${REPO_ROOT}/app/tauri"
FRONTEND_DIR="${REPO_ROOT}/app/frontend"
DEV_BINARY="${TAURI_DIR}/target/debug/planning-platform"
WRAPPER_APP="${TAURI_DIR}/target/debug/Planning Platform Dev.app"
WRAPPER_IDENTIFIER="co.nessziona.planning-platform.dev"
WRAPPER_DISPLAY_NAME="Planning Platform Dev"
SIDECAR_HEALTH="http://127.0.0.1:17321/health"
VITE_URL="http://127.0.0.1:1420/"
BOOT_TIMEOUT_S=90

source "$HOME/.cargo/env" 2>/dev/null || true

log()  { printf "[prep] %s\n" "$*"; }
fail() { printf "[prep] ❌ %s\n" "$*" >&2; exit "${2:-99}"; }

# ── 1. Kill leftover processes ───────────────────────────────────────────
log "killing leftover dev processes…"
pkill -f "cargo tauri" 2>/dev/null
pkill -f "cargo run.*planning-platform" 2>/dev/null
pkill -f "target/debug/planning-platform" 2>/dev/null
pkill -f "Planning Platform Dev.app" 2>/dev/null
pkill -f "sidecar.main" 2>/dev/null
pkill -f "node node_modules/.bin/vite" 2>/dev/null
pkill -f "node node_modules/vite" 2>/dev/null
sleep 1

# ── 2. Free the ports ────────────────────────────────────────────────────
for PORT in 1420 17321; do
  PIDS=$(lsof -ti :"$PORT" 2>/dev/null)
  if [ -n "$PIDS" ]; then
    log "port $PORT still held by $PIDS — killing"
    echo "$PIDS" | xargs -r kill -9 2>/dev/null
  fi
done
sleep 1

# ── 3. Stale .app guard ──────────────────────────────────────────────────
# Only allow OUR wrapper to be registered as 'Planning Platform' or
# 'Planning Platform Dev'. Anything else is a shadow that must be cleaned
# up before we launch (otherwise LaunchServices may pull the wrong app
# forward when Cowork activates by name).
STALE_HITS=$(mdfind "kMDItemDisplayName == 'Planning Platform' && kMDItemKind == 'Application'" 2>/dev/null \
             | grep -v "Planning Platform Dev.app$" || true)
if [ -n "$STALE_HITS" ]; then
  log "❌ stale 'Planning Platform.app' (NOT our wrapper) still indexed:"
  printf "    %s\n" $STALE_HITS
  log "   Delete these manually then re-run:"
  log "     rm -rf '<path>'"
  log "     /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -kill -r -domain local -domain system -domain user"
  fail "refusing to launch until stale .app is gone" 1
fi
log "✅ no stale Planning Platform.app shadowing"

# Belt + braces — known-bad on-disk paths
for STALE in \
  "/Applications/Planning Platform.app" \
  "/Applications/Planning Platform.OLD-phase1.app" \
  "${TAURI_DIR}/target/release/bundle/macos/Planning Platform.app"
do
  if [ -e "$STALE" ]; then
    fail "stale bundle still on disk: $STALE — rm -rf before re-running" 1
  fi
done

# ── 4. Start Vite (frontend dev server) ──────────────────────────────────
log "starting Vite dev server…"
VITE_LOG="/tmp/prep_cowork_vite_$(date +%s).log"
(
  cd "$FRONTEND_DIR" && npm run dev > "$VITE_LOG" 2>&1
) &
VITE_LAUNCHER_PID=$!
log "   vite launcher pid: $VITE_LAUNCHER_PID, log: $VITE_LOG"

# Wait until Vite serves the index page.
# --fail so a 5xx from Vite doesn't masquerade as healthy (without it, ANY
# HTTP response — including an error page — returns curl exit 0).
DEADLINE=$(( $(date +%s) + 30 ))
until curl -sS --fail --max-time 1 "$VITE_URL" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    log "tail of vite log:"; tail -20 "$VITE_LOG" | sed 's/^/    /'
    fail "Vite did not come up with 2xx within 30s (see $VITE_LOG)" 2
  fi
  sleep 1
done
log "✅ Vite serving at $VITE_URL"

# ── 5. Build the Tauri binary (incremental) ─────────────────────────────
log "building Tauri binary (cargo build — incremental)…"
BUILD_LOG="/tmp/prep_cowork_cargo_$(date +%s).log"
(
  cd "$TAURI_DIR" && cargo build > "$BUILD_LOG" 2>&1
)
if [ $? -ne 0 ]; then
  log "tail of cargo build log:"; tail -30 "$BUILD_LOG" | sed 's/^/    /'
  fail "cargo build failed (see $BUILD_LOG)" 3
fi
if [ ! -x "$DEV_BINARY" ]; then
  fail "binary not at $DEV_BINARY after cargo build" 3
fi
log "✅ binary built: $DEV_BINARY"

# ── 6. Build/refresh the wrapper .app ────────────────────────────────────
# Why inside target/debug/: spawn_sidecar() in lib.rs walks current_exe()
# ancestors looking for `app/sidecar/sidecar/main.py`. The repo root is an
# ancestor of target/debug/Planning Platform Dev.app/Contents/MacOS/, so
# the sidecar discovery still works. (A wrapper at /tmp/ or ~/Applications
# would break that lookup.)
log "refreshing wrapper .app at $WRAPPER_APP …"
rm -rf "$WRAPPER_APP"
mkdir -p "$WRAPPER_APP/Contents/MacOS" "$WRAPPER_APP/Contents/Resources"

# Symlink (not copy) so cargo build updates are picked up automatically.
ln -s "$DEV_BINARY" "$WRAPPER_APP/Contents/MacOS/planning-platform"

cat > "$WRAPPER_APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>planning-platform</string>
  <key>CFBundleIdentifier</key><string>${WRAPPER_IDENTIFIER}</string>
  <key>CFBundleName</key><string>${WRAPPER_DISPLAY_NAME}</string>
  <key>CFBundleDisplayName</key><string>${WRAPPER_DISPLAY_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>0.1.0-dev</string>
  <key>CFBundleShortVersionString</key><string>0.1.0-dev</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <!--
    ATS (App Transport Security) — dev wrapper allows arbitrary HTTP loads.
    Without this, WKWebView blocks fetches from React → http://127.0.0.1:17321
    even though the page itself is loaded over HTTP from Vite. Symptom in the
    browser console: 'TypeError: Load failed' on every fetch.

    NSAllowsLocalNetworking alone wasn't enough — declaring ATS config seems
    to make WKWebView MORE strict than the bare-binary (no-plist) default.
    Production builds will need an explicit NSExceptionDomains list for
    whatever endpoints they call; for dev, NSAllowsArbitraryLoads is fine.
  -->
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsArbitraryLoads</key><true/>
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
</dict>
</plist>
EOF

# Force LaunchServices to re-register this specific bundle
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
  -f "$WRAPPER_APP" 2>/dev/null
log "✅ wrapper built; identifier=$WRAPPER_IDENTIFIER"

# ── 7. Launch via LaunchServices ─────────────────────────────────────────
log "launching wrapper via LaunchServices…"
open -n "$WRAPPER_APP"

# ── 8. Wait for the process + sidecar /health ────────────────────────────
# Note: `open -n` launches the .app via launchd, and the kernel resolves the
# Contents/MacOS/planning-platform symlink before exec — so the process's
# command line shows the RESOLVED path (target/debug/planning-platform),
# not the wrapper path. We disambiguate by PPID==1 (launchd) — a binary
# launched via `cargo run` or any shell would have a different parent.
log "waiting up to ${BOOT_TIMEOUT_S}s for binary + sidecar…"
DEADLINE=$(( $(date +%s) + BOOT_TIMEOUT_S ))
DEV_PID=""
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  if [ -z "$DEV_PID" ]; then
    # Find planning-platform processes whose parent is launchd (PID 1) —
    # i.e., the wrapper-launched one (not any cargo-spawned leftover).
    for CAND in $(pgrep -f "target/debug/planning-platform"); do
      PPID_OF=$(ps -o ppid= -p "$CAND" 2>/dev/null | tr -d ' ')
      if [ "$PPID_OF" = "1" ]; then
        DEV_PID="$CAND"
        break
      fi
    done
  fi
  # --fail makes curl exit non-zero on HTTP 4xx/5xx (without it, a 500
  # response still returns exit 0 and we'd wrongly conclude /health is OK).
  if [ -n "$DEV_PID" ] && curl -sS --fail --max-time 1 "$SIDECAR_HEALTH" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if [ -z "$DEV_PID" ]; then
  fail "binary process never appeared after open ${WRAPPER_APP}" 4
fi
if ! curl -sS --fail --max-time 1 "$SIDECAR_HEALTH" >/dev/null 2>&1; then
  fail "sidecar /health never responded with 2xx within ${BOOT_TIMEOUT_S}s" 5
fi
log "✅ binary pid=$DEV_PID + sidecar healthy"

# ── 8b. Frontend-fetch smoke test ────────────────────────────────────────
# /health passing only proves the sidecar process is alive. It doesn't
# prove that the actual cross-origin fetch the React app makes will work
# — CORS headers, route registration, schema serialization can all break
# /projects independently. We exercise the EXACT path the React WebView
# uses (including the Origin header it would send) so failures here are
# caught at script time, before Cowork opens the window and reports
# "TypeError: Load failed".
SIDECAR_PROJECTS="http://127.0.0.1:17321/projects"
log "smoke-testing frontend fetch path: GET $SIDECAR_PROJECTS (Origin: tauri://localhost)…"
if ! curl --fail -sS --max-time 3 \
      -H "Origin: tauri://localhost" \
      "$SIDECAR_PROJECTS" \
   | jq -e '. | type == "array"' >/dev/null 2>&1; then
  log "❌ /projects didn't return a JSON array — frontend fetch path broken"
  log "   debug:"; log "     curl -sS -H 'Origin: tauri://localhost' '$SIDECAR_PROJECTS'"
  fail "FAIL: frontend fetch path broken (CORS, route, or serialization)" 6
fi
log "✅ /projects returns a JSON array via tauri://localhost origin"

# ── 9. Verify the bundle identifier IS readable from the running process ─
ACTUAL_ID=$(osascript -e "tell application \"System Events\" to get bundle identifier of (first process whose unix id is $DEV_PID)" 2>/dev/null)
if [ "$ACTUAL_ID" != "$WRAPPER_IDENTIFIER" ]; then
  log "⚠️  bundle identifier from osascript: '$ACTUAL_ID' (expected '$WRAPPER_IDENTIFIER')"
  log "   Cowork may still fail request_access. See docs/dev_setup.md → Troubleshooting."
else
  log "✅ osascript confirms bundle identifier: $ACTUAL_ID"
fi

# ── 10. Activate the window ──────────────────────────────────────────────
osascript -e "tell application \"System Events\" to set frontmost of (first process whose unix id is $DEV_PID) to true" >/dev/null 2>&1

# ── 11. READY line — Cowork-scrapeable ───────────────────────────────────
log ""
log "Phase 2b sanity markers — Cowork should see these in the window:"
log "  • Home page title: \"בקרת תכניות עיצוב\" (NOT \"שלב 1 (שלד)\")"
log "  • Sidebar: \"מתחם הטייסים-ההסתדרות\" (407-1048248)"
log "  • Findings tab → content rules in Hebrew (e.g. \"שטח עיקרי\", \"תקן חניה\")"
log ""

echo "READY pid=$DEV_PID identifier=$WRAPPER_IDENTIFIER sidecar=$SIDECAR_HEALTH vite=$VITE_URL"
