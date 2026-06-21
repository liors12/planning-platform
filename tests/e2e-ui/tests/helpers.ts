import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Browser, Page } from "@playwright/test";

// ── Install vs data dir ───────────────────────────────────────────────
// The INSTALL dir is where NSIS unpacks the binaries:
//   %LOCALAPPDATA%\Planning Platform\
//     Planning Platform.exe       <-- shell
//     sidecar\sidecar.exe         <-- bundled FastAPI
//     weasyprint\weasyprint.exe
//     uninstall.exe
//
// The DATA dir is where the sidecar writes platform.db, projects/,
// audit_outputs/, logs/, jobs/. By default it ALSO resolves to
// %LOCALAPPDATA%\Planning Platform\ — i.e. install and data co-exist.
// That collision is what made every "wipe data" risk the install.
//
// P3 fix: the sidecar's PLATFORM_DATA_DIR env var (already supported
// at app/sidecar/sidecar/config.py:68) overrides the data dir. The
// UI suite now creates a per-run tempdir and passes it via that env
// var on launch, so:
//   - data lives at a fresh tmpdir for each test run
//   - teardown is rmSync(perRunDataDir) — no install-dir surgery
//   - the install dir is never touched, even by mistake
const PRODUCT_DIR = "Planning Platform";

function localAppData(): string {
  const p = process.env.LOCALAPPDATA;
  if (!p) throw new Error("LOCALAPPDATA not set — this test only runs on Windows");
  return p;
}

// Discover the Tauri shell .exe rather than hardcoding the filename.
// First run on the runner proved the assumption "<productName>.exe"
// wrong — the actual binary lives under %LOCALAPPDATA%\Planning Platform\
// but with a different name. Mirror the existing CI's discovery pattern:
// scan top-level *.exe and exclude the three known non-shell binaries.
export function installedExePath(): string {
  const dir = join(localAppData(), PRODUCT_DIR);
  if (!existsSync(dir)) {
    throw new Error(
      `Install dir not found at ${dir}. Has the NSIS installer run with /S?`
    );
  }
  const excluded = new Set(["uninstall.exe", "sidecar.exe", "weasyprint.exe"]);
  const candidates = readdirSync(dir).filter(
    (n) => n.toLowerCase().endsWith(".exe") && !excluded.has(n.toLowerCase())
  );
  if (candidates.length === 0) {
    throw new Error(
      `No shell .exe found in ${dir}. Listing: ${readdirSync(dir).join(", ")}`
    );
  }
  if (candidates.length > 1) {
    // Not fatal — pick the first deterministically (alphabetical) and log.
    process.stderr.write(
      `[helpers] Multiple shell .exe candidates in ${dir}: ${candidates.join(", ")}. ` +
      `Picking ${candidates[0]}.\n`
    );
  }
  return join(dir, candidates[0]);
}

// Diagnostic listing of the install dir — print before any assertion so a
// failure artifact shows what was actually on disk, not just the
// assertion that tripped.
export function logInstallDirContents(): void {
  const dir = join(localAppData(), PRODUCT_DIR);
  if (!existsSync(dir)) {
    process.stdout.write(`[helpers] Install dir does NOT exist: ${dir}\n`);
    return;
  }
  process.stdout.write(`[helpers] Install dir contents (${dir}):\n`);
  for (const entry of readdirSync(dir)) {
    process.stdout.write(`[helpers]   ${entry}\n`);
  }
}

// ── P3: per-run data dir (PLATFORM_DATA_DIR override) ─────────────────
// Each test run gets a fresh tempdir; the sidecar's PLATFORM_DATA_DIR
// env var (config.py:68) redirects the entire data tree there. After
// this:
//   - "wipe" is just "make a new tmpdir" — fresh by construction
//   - teardown is rmSync on that tmpdir — never touches the install
//   - two tests on the same machine can't poison each other
// Caller responsibility: pass the returned path to launchApp(),
// wipe it in teardown via wipePerRunDataDir().
export function createPerRunDataDir(): string {
  return mkdtempSync(join(tmpdir(), "pp-ui-smoke-data-"));
}

export function wipePerRunDataDir(folder: string | null): void {
  if (!folder) return;
  try {
    rmSync(folder, { recursive: true, force: true });
  } catch {
    // Best-effort. SQLite WAL files sometimes linger past sidecar exit;
    // the OS reclaims the tempdir eventually. Don't fail the test over
    // teardown noise.
  }
}

// ── P2: dynamic free TCP port ─────────────────────────────────────────
// Hard-coding the CDP port (was 9223) breaks when a previous test run
// left WebView2 holding it, or when two test invocations overlap. Ask
// the OS for any free port — bind to 0, read the assigned port, close.
// The window between close and re-bind is small but non-zero; the
// alternative (port-in-use retry loop) hides real bugs behind retries.
export function freeTcpPort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      if (addr === null || typeof addr === "string") {
        srv.close();
        return reject(new Error("freeTcpPort: server address unavailable"));
      }
      const port = addr.port;
      srv.close(() => resolve(port));
    });
  });
}

// ── P2: per-run WebView2 user data folder ─────────────────────────────
// WebView2's default user data location is shared across all WebView2
// hosts on the machine. When two test runs (or a leftover msedge.exe
// from the previous run) touch the same folder, you get file-lock
// flakiness: "another instance has this database open", cookies
// corruption, GPU cache races. Microsoft's WebView2 + Playwright docs
// require a unique folder per session for exactly this reason.
//
// Caller responsibility: pass the returned path to launchApp() AND
// wipe it in teardown via wipeUserDataFolder(). Lives under the OS
// tempdir so OS-level cleanup eventually reclaims orphans.
export function createUserDataFolder(): string {
  return mkdtempSync(join(tmpdir(), "pp-ui-smoke-webview2-"));
}

export function wipeUserDataFolder(folder: string | null): void {
  if (!folder) return;
  try {
    rmSync(folder, { recursive: true, force: true });
  } catch {
    // Best-effort. WebView2 sometimes holds file handles past process
    // exit; OS will reclaim the temp dir eventually. Don't fail the
    // test over teardown noise.
  }
}

// ── Launch the installed .exe with full per-run isolation ─────────────
// Three env vars layered on the spawn:
//
//   WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS — opens the CDP debug port
//     (WebView2 loader honors this; production unsets it so the port
//     stays closed in shipped installers).
//
//   WEBVIEW2_USER_DATA_FOLDER — private WebView2 cookies / cache /
//     IndexedDB so concurrent or back-to-back runs don't collide.
//
//   PLATFORM_DATA_DIR — sidecar config.py:68 honors this to redirect
//     ALL platform data (platform.db, projects/, audit_outputs/, logs/,
//     jobs/) away from %LOCALAPPDATA%\Planning Platform\ (which is
//     where the binaries also live). Tauri's Command::new inherits env
//     by default, so the env we set on the shell propagates to the
//     spawned sidecar.exe automatically — verified against
//     app/tauri/src/lib.rs:111.
//
// All three vars are unset in production: the shipped app uses default
// paths and the debug port stays closed.
export function launchApp(
  cdpPort: number,
  userDataFolder: string,
  platformDataDir: string,
): ChildProcess {
  const exe = installedExePath();
  if (!existsSync(exe)) {
    throw new Error(`Packaged app not found at ${exe}. Was the installer run with /S?`);
  }
  const child = spawn(exe, [], {
    env: {
      ...process.env,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdpPort}`,
      WEBVIEW2_USER_DATA_FOLDER: userDataFolder,
      PLATFORM_DATA_DIR: platformDataDir,
    },
    detached: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: false,
  });
  child.stdout?.on("data", (b) => process.stdout.write(`[app stdout] ${b}`));
  child.stderr?.on("data", (b) => process.stderr.write(`[app stderr] ${b}`));
  return child;
}

// ── P2: select the Tauri main window page deterministically ───────────
// Don't assume pages()[0] — a Tauri WebView2 host can expose:
//   - the Tauri main window (tauri://localhost or http://tauri.localhost)
//   - blank/preload pages (about:blank)
//   - DevTools or service worker targets
// pages()[0] picks whichever target hit the CDP list first; on a slow
// boot, that's frequently about:blank, and clicks fired there silently
// do nothing. Filter explicitly.
export async function pickTauriPage(browser: Browser, timeoutMs = 15_000): Promise<Page> {
  const deadline = Date.now() + timeoutMs;
  let lastSeen: string[] = [];
  while (Date.now() < deadline) {
    for (const ctx of browser.contexts()) {
      for (const p of ctx.pages()) {
        const url = p.url();
        if (
          url.startsWith("tauri://") ||
          url.startsWith("http://tauri.localhost") ||
          url.startsWith("https://tauri.localhost")
        ) {
          return p;
        }
        lastSeen.push(url);
      }
    }
    await sleep(250);
  }
  throw new Error(
    `pickTauriPage: no tauri:// or tauri.localhost page found within ${timeoutMs}ms. ` +
    `Saw URLs: ${[...new Set(lastSeen)].join(", ") || "<none>"}`
  );
}

// ── Wait for sidecar /health to respond ───────────────────────────────
// Sidecar boot is the slowest cold-start step (~1–3s in dev, up to ~8s
// in the frozen Windows build). Poll until it answers or give up so the
// test fails with a clear "sidecar never came up" rather than a generic
// CDP attach error 30s later.
export async function waitForSidecar(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr: unknown = null;
  while (Date.now() < deadline) {
    try {
      const r = await fetch("http://127.0.0.1:17321/health");
      if (r.ok) return;
    } catch (e) { lastErr = e; }
    await sleep(500);
  }
  throw new Error(
    `Sidecar /health did not respond within ${timeoutMs}ms. Last error: ${String(lastErr)}`
  );
}

// ── Wait for WebView2 CDP endpoint to be reachable ────────────────────
// Even after sidecar boots, WebView2 takes another moment to expose its
// /json/version endpoint. Same poll-with-deadline pattern.
export async function waitForCdp(port: number, timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastErr: unknown = null;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (r.ok) {
        const data = await r.json() as { webSocketDebuggerUrl?: string };
        if (data.webSocketDebuggerUrl) return data.webSocketDebuggerUrl;
      }
    } catch (e) { lastErr = e; }
    await sleep(500);
  }
  throw new Error(
    `WebView2 CDP endpoint :${port} never responded. Last error: ${String(lastErr)}`
  );
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ── P2: defensive teardown — kill app tree + sweep stragglers ─────────
// `taskkill /F /T /PID` walks the parent's process tree, which SHOULD
// catch the spawned sidecar.exe + the WebView2 msedge.exe children.
// But on Windows that's not always reliable: a previous CI run left
// orphan msedge.exe processes that held the user data folder open,
// breaking the next run. Belt-and-braces:
//   1. Kill the Tauri parent PID with /T (the happy path)
//   2. Defensively sweep any remaining sidecar.exe by image name
//   3. Defensively sweep any remaining msedge.exe by image name —
//      acceptable risk: if the developer happens to be running Edge
//      on the same Windows box, this kills their browser. In CI
//      (windows-latest) and a dedicated test VM, no Edge is running.
// Errors swallowed — taskkill exit 128 means "no such process",
// which is success for our purposes.
export function killApp(child: ChildProcess | null): void {
  const { execSync } = require("node:child_process") as typeof import("node:child_process");
  const sweep = (cmd: string) => {
    try { execSync(cmd, { stdio: "ignore" }); } catch { /* already gone */ }
  };
  if (child?.pid) {
    sweep(`taskkill /F /T /PID ${child.pid}`);
  }
  // Image-name sweeps are CI-safe; a real developer machine running
  // this teardown shouldn't have these processes for any other reason.
  sweep("taskkill /F /IM sidecar.exe /T");
  sweep("taskkill /F /IM msedgewebview2.exe /T");
  sweep("taskkill /F /IM msedge.exe /T");
}
