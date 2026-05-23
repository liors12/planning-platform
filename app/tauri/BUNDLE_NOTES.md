# Tauri bundle notes

## What `cargo tauri build` produces, by platform

`bundle.targets = "all"` in `tauri.conf.json` means "every bundler the
current host can run". The actual artifacts differ per host:

| Host OS | Bundlers fired | Artifacts |
|---|---|---|
| **macOS** (this dev box) | `app`, `dmg` | `Planning Platform.app/`, `Planning Platform_0.1.0_aarch64.dmg` |
| **Windows** (Lior's UTM, planned) | `msi`, `nsis` | `Planning Platform_0.1.0_x64-setup.exe` (NSIS), `Planning Platform_0.1.0_x64_en-US.msi` |
| **Linux** | `deb`, `rpm`, `appimage` | n/a — not a target deployment OS |

Tauri does not cross-compile Windows installers from macOS (the toolchain
gap is too wide — would need Windows SDK + signtool + Visual C++ runtime).
NSIS verification on Mac is config-level only:

1. `bundle.targets = "all"` is set ✓
2. `cargo tauri build` runs cleanly without configuration errors ✓
3. The `tauri-cli` shipped (v2.11.2) supports both `nsis` and `msi` bundlers
   ✓ (verified via `cargo tauri info` output earlier).

The first actual `.nsis` and `.msi` artifacts produce on Lior's Windows 11
UTM VM with the same `cargo tauri build` invocation — no Mac-side changes
required.

## Phase 1 Mac build verification

```
Finished `release` profile [optimized] target(s) in 1m 05s
Built application at: target/release/planning-platform
Bundling Planning Platform.app   → target/release/bundle/macos/
Bundling Planning Platform.dmg   → target/release/bundle/macos/ (28 MB)
```

Binary is 4.1 MB stripped. The 28 MB DMG includes the WebKit shell + the
embedded React bundle (~150 KB compressed) + icons.

The Phase 1 binary **does not yet bundle the FastAPI sidecar**. The Rust
shell still spawns `python -m sidecar.main` at startup from the host's
Homebrew Python (see `src/lib.rs` `spawn_sidecar()`). Phase 4 swaps to:

1. Build the sidecar via `pyinstaller backend.spec` → `dist/sidecar/sidecar`.
2. Rename to Tauri's expected platform-suffix form (e.g.
   `sidecar-aarch64-apple-darwin`) and place under `app/tauri/binaries/`.
3. Reference it from `tauri.conf.json` as `bundle.externalBin`.
4. Update `src/lib.rs` to spawn via Tauri's `Sidecar` API instead of
   `Command::new("python")`.

That's a documented Phase 4 deliverable, not a Phase 1 one. The forward-
compat work proves the PyInstaller side is ready when we get there.

## Known caveats for the Windows port

- The `WeasyPrint` dylib glob in `backend_full.spec` is macOS-only. For
  Windows we need to bundle the GTK3-for-Windows runtime DLLs. See open
  item #3 in `app/sidecar/PYINSTALLER_NOTES.md`.
- The Tauri `binaries/` directory naming convention is platform-suffixed
  (`sidecar-aarch64-apple-darwin`, `sidecar-x86_64-pc-windows-msvc.exe`).
  A `build.rs` or shell script renames the PyInstaller output before
  `cargo tauri build` consumes it.
- Code signing (Apple Developer cert on Mac, EV cert on Windows) is
  deferred per spec § 8.
