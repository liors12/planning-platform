# app/ — Desktop UI (Phase 1 skeleton)

Tauri v2 + React + FastAPI scaffold for the Municipal Compliance Platform.
Spec: [docs/product_spec_v0.1.md](../docs/product_spec_v0.1.md).

## Layout

```
app/
├── frontend/    Vite + React + TypeScript — the UI (npm-managed)
├── sidecar/     FastAPI + SQLCipher backend (Python-managed)
└── tauri/       Tauri v2 shell (Rust-managed) — boots both frontend and sidecar
```

## Subprocess isolation, from day one

The sidecar **never** does heavy work in-process. Even the Phase 1 `/jobs/echo`
endpoint spawns a separate Python worker via `subprocess.run` and reads the
result from disk. See [docs/architecture/ADR-001-subprocess-isolation.md](../docs/architecture/ADR-001-subprocess-isolation.md).

Adding a new job type:

1. Add a row to [docs/architecture/job_types.md](../docs/architecture/job_types.md).
2. Write the worker as `app/sidecar/sidecar/jobs/{name}_worker.py`.
   It must accept `--job-dir DIR` and read/write `job_input.json` / `job_output.json` / `error.json`.
3. Add a FastAPI endpoint that calls `dispatch.run_job(...)`. Never import the worker module's code directly.

## Dev quick-start (macOS)

Prereqs (one-time):

```bash
brew install sqlcipher
brew install node            # if missing
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo install tauri-cli --version "^2.0.0" --locked

# Python deps (the sidecar reuses the same /opt/homebrew/bin/python3.13
# as the rest of the platform; see ADR-001 § Implication 4).
SQLCIPHER_PREFIX=$(brew --prefix sqlcipher)
LDFLAGS="-L${SQLCIPHER_PREFIX}/lib" \
  CPPFLAGS="-I${SQLCIPHER_PREFIX}/include/sqlcipher" \
  pip install --break-system-packages --no-binary :all: sqlcipher3
pip install --break-system-packages -r app/sidecar/requirements.txt

# Frontend deps
(cd app/frontend && npm install)
```

Run everything together:

```bash
cd app/tauri && cargo tauri dev
```

That command:
- Starts Vite at `http://127.0.0.1:1420`
- Compiles + launches the Tauri shell (Rust)
- Tauri shell spawns the FastAPI sidecar (`python -m sidecar.main`) at `http://127.0.0.1:17321`
- The window loads the React app; the React app calls `/health` and shows results

Run the sidecar alone (for backend dev without the Tauri shell):

```bash
cd app/sidecar && python3.13 -m sidecar.main
# --fail so a 5xx response surfaces as a non-zero exit, not a happy-path
# 200-shaped pipe to json.tool that errors with "Expecting value":
curl --fail -sS http://127.0.0.1:17321/health | python3.13 -m json.tool
```

## Configuration

| Env var | Default | What it does |
|---|---|---|
| `PLATFORM_DATA_DIR` | `~/.platform` | Where the encrypted DB + per-job temp dirs live |
| `PLATFORM_BIND_HOST` | `127.0.0.1` | Sidecar bind host. Anything other than localhost is rejected. |
| `PLATFORM_BIND_PORT` | `17321` | Sidecar TCP port |
| `PLATFORM_MAX_CONCURRENT_JOBS` | `1` | Subprocess concurrency cap (ADR-001 § Implication 2) |
| `PLATFORM_DB_KEY` | `phase1-dev-key-DO-NOT-SHIP` | SQLCipher key. Production derives from Ellen's PIN (spec § 8). |
| `PLATFORM_PYTHON` | `/opt/homebrew/bin/python3.13` | Interpreter for worker subprocesses |

## What's out of scope for Phase 1

Per spec § 10:

- Module A (projects + submissions) — Phase 2
- Module B (compliance review workspace + pdf.js) — Phase 2
- Module C (guidelines editor) — Phase 3
- Module D (discipline feedback) — Phase 3
- Module E (final חוות דעת generation) — Phase 3
- Packaging (PyInstaller, NSIS installer, signed builds) — Phase 4
