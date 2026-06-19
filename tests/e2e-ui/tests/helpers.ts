import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";

// ── Paths that must match the installer + sidecar config ──────────────
// IMPORTANT: Tauri NSIS with installMode=currentUser AND the sidecar's
// default data dir BOTH resolve to %LOCALAPPDATA%\Planning Platform\.
// So install and data co-exist in the same folder, e.g.:
//   %LOCALAPPDATA%\Planning Platform\
//     Planning Platform.exe       <-- install (Tauri shell)
//     sidecar\sidecar.exe         <-- install
//     weasyprint\weasyprint.exe   <-- install
//     uninstall.exe               <-- install
//     platform.db                 <-- DATA
//     projects\                   <-- DATA (uploaded PDFs, metadata)
//     audit_outputs\              <-- DATA (rendered reports)
//     logs\                       <-- DATA
//     jobs\                       <-- DATA
// Wiping the whole folder would brick the install. So the "wipe" step
// targets only the known DATA names and leaves binaries alone.
const PRODUCT_DIR = "Planning Platform";
const DATA_FILES = ["platform.db", "platform.db-shm", "platform.db-wal"];
const DATA_SUBDIRS = ["projects", "audit_outputs", "logs", "jobs"];

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

export function dataDir(): string {
  return join(localAppData(), PRODUCT_DIR);
}

// ── Wipe data, preserve install ───────────────────────────────────────
// "Fresh data state" per the spec, without nuking the binaries that
// would force a reinstall every run. After this returns, the app comes
// up exactly as a freshly-installed first-launch would: seed populates
// the pilot project, no prior submissions, no DB.
export function wipeData(): void {
  const d = dataDir();
  if (!existsSync(d)) return;
  for (const f of DATA_FILES) {
    const p = join(d, f);
    if (existsSync(p)) rmSync(p, { force: true });
  }
  for (const s of DATA_SUBDIRS) {
    const p = join(d, s);
    if (existsSync(p)) rmSync(p, { recursive: true, force: true });
  }
}

// Sanity check: after wipeData(), confirm none of the data names remain.
// Throws with a diagnostic listing if any survived.
export function assertDataWiped(): void {
  const d = dataDir();
  if (!existsSync(d)) return; // pre-install state — also OK
  const survivors: string[] = [];
  for (const name of [...DATA_FILES, ...DATA_SUBDIRS]) {
    if (existsSync(join(d, name))) survivors.push(name);
  }
  if (survivors.length > 0) {
    const all = readdirSync(d).join(", ");
    throw new Error(
      `wipeData() did not remove: ${survivors.join(", ")}. ` +
      `Full dir listing: ${all}`
    );
  }
}

// ── Launch the installed .exe with WebView2 CDP port open ─────────────
// WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS is read by the WebView2 loader
// itself; no Tauri config change needed. Production runs without the
// var set, so the debug port never opens in shipped builds.
export function launchApp(cdpPort: number): ChildProcess {
  const exe = installedExePath();
  if (!existsSync(exe)) {
    throw new Error(`Packaged app not found at ${exe}. Was the installer run with /S?`);
  }
  const child = spawn(exe, [], {
    env: {
      ...process.env,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${cdpPort}`,
    },
    detached: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: false,
  });
  child.stdout?.on("data", (b) => process.stdout.write(`[app stdout] ${b}`));
  child.stderr?.on("data", (b) => process.stderr.write(`[app stderr] ${b}`));
  return child;
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

// ── Kill the app process and any stragglers ───────────────────────────
// Tauri spawns the sidecar as a child; killing the parent should cascade,
// but on Windows that's not always true. We use taskkill /T to walk
// the tree and /F to skip graceful shutdown (the next test will wipe
// the data dir anyway). Safe to call repeatedly.
export function killApp(child: ChildProcess | null): void {
  if (child?.pid) {
    try {
      const { execSync } = require("node:child_process");
      execSync(`taskkill /F /T /PID ${child.pid}`, { stdio: "ignore" });
    } catch {
      // process may already be gone — ignore
    }
  }
}
