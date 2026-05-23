# Dev environment setup — the `.app` wrapper around the Tauri dev binary

This doc covers a non-obvious piece of the dev workflow: a thin `.app`
bundle that wraps the bare `cargo build` binary, giving it a macOS bundle
identifier so external tools (Cowork's `request_access`, AppleScript's
"tell application by identifier", etc.) can find and interact with the
running app.

If you're just doing day-to-day frontend or sidecar work, you don't need
to read this — `bash scripts/prep_cowork_session.sh` does everything
automatically. Read this when something breaks or when you're onboarding.

---

## Why this exists

`cargo tauri dev` is the idiomatic Tauri dev workflow: it runs Vite, runs
`cargo run`, and watches Rust sources. But the binary it produces is a
**bare Mach-O executable** at `target/debug/planning-platform` — not a
`.app` bundle.

macOS only assigns a bundle identifier to processes whose binary lives
inside a `.app/Contents/MacOS/` directory and whose `.app/Contents/Info.plist`
declares `CFBundleIdentifier`. A bare binary has no `Info.plist` and
therefore no bundle identifier. Concretely:

```bash
# With cargo tauri dev's bare binary:
$ osascript -e 'tell application "System Events" to get bundle identifier of (first process whose unix id is 43796)'
missing value
```

`missing value` is the symptom. Cowork's `request_access` filters at the
LaunchServices layer — which is keyed on bundle identifier. No identifier
means `request_access` returns `didYouMean: []` and Cowork literally
cannot grant itself screenshot permission for the window. That blocks
visual verification entirely.

We hit this concretely after Phase 2b Step 7: Cowork kept finding the old
Phase 1 `.app` (because it had a proper identifier from `cargo tauri
build`) while ignoring our actual running dev binary (which had none).

## The fix: a `.app` shell around the bare binary

The fix is small and localized. We build the dev binary normally with
`cargo build`, then assemble a thin `.app` wrapper at
`app/tauri/target/debug/Planning Platform Dev.app/` with:

- `Contents/MacOS/planning-platform` — a **symlink** to
  `target/debug/planning-platform` (not a copy; auto-tracks rebuilds)
- `Contents/Info.plist` — minimal Info.plist with
  `CFBundleIdentifier = co.nessziona.planning-platform.dev`

Then `open -n "Planning Platform Dev.app"` launches the binary through
LaunchServices with the identifier set. The binary itself is unchanged —
same code, same WebView, same Vite hookup, same sidecar spawn. The
wrapper is pure metadata.

After launch:

```bash
$ osascript -e 'tell application "System Events" to get bundle identifier of (first process whose unix id is <PID>)'
co.nessziona.planning-platform.dev
```

Cowork can now `request_access` on that identifier.

### Why **`.dev`** suffix?

`co.nessziona.planning-platform.dev` keeps the dev wrapper distinct from
any future production `.app` (which `tauri.conf.json` declares as
`co.nessziona.planning-platform`). If we ever produce a real signed
production bundle and install it side-by-side, LaunchServices won't
confuse the two. Two identifiers, two registrations, zero shadowing.

### Why **inside `target/debug/`** and not somewhere else?

The Rust shell's `spawn_sidecar()` in `app/tauri/src/lib.rs` walks
`current_exe()` ancestors looking for `app/sidecar/sidecar/main.py` —
that's how it finds the Python sidecar to spawn. The wrapper has to be
located somewhere whose ancestors include the repo root, otherwise the
ancestor walk fails and the sidecar never starts.

`app/tauri/target/debug/Planning Platform Dev.app/Contents/MacOS/`
satisfies this: walking up reaches `target/debug/` → `target/` →
`app/tauri/` → `app/` → the repo root, which has `app/sidecar/` as a
child. ✅

Locations that **don't work**:
- `/Applications/Planning Platform Dev.app` — ancestors include `/`, not
  the repo
- `/tmp/Planning Platform Dev.app` — same issue
- `~/Applications/Planning Platform Dev.app` — same

## When does the wrapper need refreshing?

The wrapper's binary is a symlink to `target/debug/planning-platform`.
When `cargo build` (or `cargo tauri dev`) rebuilds the binary, the
symlink target is updated transparently. **No refresh needed for Rust
rebuilds.**

The wrapper itself (the `.app` directory) needs refreshing only when:

1. The `Info.plist` content needs to change (rare — identifier shouldn't
   drift)
2. The wrapper got deleted (e.g., `cargo clean` wipes `target/`)
3. macOS LaunchServices "forgot" about the wrapper after a long idle

In all three cases, just re-run `scripts/prep_cowork_session.sh`. The
script is idempotent — it deletes and rebuilds the wrapper every time.

## The full launch flow (what `prep_cowork_session.sh` does)

1. Kill any leftover dev processes (Vite, cargo, planning-platform, sidecar)
2. Free TCP ports 1420 (Vite) and 17321 (sidecar)
3. **Stale-.app guard**: refuse to launch if any `Planning Platform.app`
   exists on disk that **isn't** our wrapper. Better to abort than to
   silently let a stale build steal LaunchServices traffic.
4. Start Vite (`npm --prefix app/frontend run dev`) and wait for port 1420
5. `cargo build` in `app/tauri/` (incremental — fast after first run)
6. Rebuild the wrapper `.app` from scratch, symlink the binary, write
   `Info.plist` with the `.dev` identifier
7. `lsregister -f` to force LaunchServices to pick up the wrapper
8. `open -n` the wrapper to launch
9. Wait for the binary process to appear AND for the sidecar `/health`
   endpoint to respond
10. Confirm via `osascript` that the bundle identifier is readable from
    the running process — log a warning if it isn't (something deeper is
    wrong)
11. Activate the window via `System Events` by PID
12. Print a Cowork-scrapeable line: `READY pid=N identifier=... sidecar=... vite=...`

## Identifier summary

| Build | Bundle identifier | Where it lives |
|---|---|---|
| Production `.app` (`cargo tauri build`) | `co.nessziona.planning-platform` | declared in `app/tauri/tauri.conf.json`, baked into `Info.plist` at build time |
| Dev wrapper (this doc) | `co.nessziona.planning-platform.dev` | declared in `scripts/prep_cowork_session.sh` (the `WRAPPER_IDENTIFIER` variable) |

Both identifiers can coexist in LaunchServices without conflict.

## Troubleshooting

### `osascript ... get bundle identifier` still returns `missing value` after `prep_cowork_session.sh`

1. The binary was launched some other way, not via the wrapper. Kill it
   and re-run the script:
   ```bash
   pkill -f "target/debug/planning-platform"
   bash scripts/prep_cowork_session.sh
   ```
2. The wrapper's `Info.plist` is malformed. Verify with:
   ```bash
   plutil -lint "/path/to/Planning Platform Dev.app/Contents/Info.plist"
   ```
3. LaunchServices got into a bad state. Reset its cache:
   ```bash
   /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
     -kill -r -domain local -domain system -domain user
   ```
   Then re-run `prep_cowork_session.sh`.

### The wrapper opens but Vite shows "ERR_CONNECTION_REFUSED"

Vite died after the script started it. Check `tail /tmp/prep_cowork_vite_*.log`. Typical causes: port 1420 held by another process (the script should have killed it, but check), or `node_modules` mismatch (re-run `npm install --prefix app/frontend`).

### The wrapper opens but the sidecar never responds

Check `/tmp/prep_cowork_*.log` for cargo errors. If cargo built fine,
check the binary's stderr — which `open -n` swallows. Re-launch
foreground to see it:

```bash
pkill -f "Planning Platform Dev.app"
"/Users/liorlevin/Desktop/planning-platform/app/tauri/target/debug/Planning Platform Dev.app/Contents/MacOS/planning-platform"
```

Most likely a Python sidecar dep is missing — see `app/sidecar/PYINSTALLER_NOTES.md`.

### Cowork still can't find the app even though osascript shows the right identifier

Cowork may have a cached enumeration. Tell it to retry; if still failing,
have it run `tccutil reset ScreenCapture co.nessziona.planning-platform.dev`
(this resets only our app's screen-capture permission, not all apps).

### `cargo clean` removed `target/` — wrapper is gone

Normal. Re-run `prep_cowork_session.sh` and everything regenerates.

## Production considerations

**Everything in this doc is for the dev wrapper.** Before we ship a
distributable `.app` to Ellen (Phase 5), three settings have to change.
Leaving them at dev defaults will either fail App Store / MDM review or
work today but break on Ellen's machine when macOS tightens defaults.

### 1. ATS — replace `NSAllowsArbitraryLoads` with `NSExceptionDomains`

The dev wrapper's `Info.plist` declares:

```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key><true/>
  <key>NSAllowsLocalNetworking</key><true/>
</dict>
```

That's a hammer — it permits HTTP loads to **any** origin. Acceptable
for dev (we're hitting `127.0.0.1` only and the binary never leaves
this machine), but distribution reviewers (App Store, MDM-enterprise
deployments) treat `NSAllowsArbitraryLoads=true` as a red flag and may
block install entirely. macOS Sequoia+ also gates the binary at install
time and may quarantine it.

The production fix is a **scoped exception** — allow HTTP only to
loopback, nowhere else:

```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key><false/>
  <key>NSExceptionDomains</key>
  <dict>
    <key>127.0.0.1</key>
    <dict>
      <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
      <key>NSExceptionRequiresForwardSecrecy</key><false/>
      <key>NSIncludesSubdomains</key><false/>
    </dict>
    <key>localhost</key>
    <dict>
      <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
      <key>NSExceptionRequiresForwardSecrecy</key><false/>
      <key>NSIncludesSubdomains</key><false/>
    </dict>
  </dict>
</dict>
```

This must be declared in `app/tauri/tauri.conf.json` under
`bundle.macOS.entitlements` (or wherever Tauri 2 surfaces ATS — verify
at build time with `plutil -p` on the bundled Info.plist).

### 2. CSP — keep the current `connect-src` whitelist

`tauri.conf.json` `app.security.csp` already lists
`http://127.0.0.1:17321` explicitly in `connect-src`. **Do not relax
this to `*` or remove the directive.** The dev wrapper inherits this
CSP only loosely (Vite injects it via Tauri's runtime), but the
production bundle bakes it into the served HTML. A misconfigured CSP
will look identical to a misconfigured ATS — both produce
`TypeError: Load failed` — so confirm at build time that the CSP in the
shipped HTML still allows `http://127.0.0.1:17321`.

### 3. Sidecar startup — wait for `/health 200` before showing the window

The dev wrapper has a known startup race: the React app fires
`listProjects()` within milliseconds of WebView load, but the Python
sidecar takes 1–3 s to import FastAPI and bind port 17321. The dev
band-aid is a 3-retry-with-backoff in `app/frontend/src/api.ts`
(`fetchOrThrow`) that masks the race transparently. The real fix lives
in `app/tauri/src/lib.rs`:

```rust
// In setup(), AFTER spawn_sidecar succeeded, poll /health up to ~10s
// before letting the window become visible. The frontend then never
// observes the race.
```

This change must land before Phase 5 because once the binary is
distributed it will start cold on every launch — Ellen will see the
empty/error state on slow machines unless the wrapper gates window
visibility on sidecar readiness.

### 4. Identifier — switch to `co.nessziona.planning-platform` (no `.dev`)

The dev wrapper uses `co.nessziona.planning-platform.dev` to coexist
with a future signed production bundle. Production must use the plain
identifier `co.nessziona.planning-platform` (declared in
`tauri.conf.json` `identifier`). Make sure no production codepath
references the `.dev` suffix — search the repo for both before tagging.

---

## Future cleanup

Eventually we should land the wrapper logic upstream in Tauri (or as a
Tauri plugin) so this stops being a custom maintained script. For now,
the script is small enough that it's not worth fighting Tauri's
conventions over.
