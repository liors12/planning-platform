use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

/// Handle to the FastAPI sidecar subprocess. Wrapped in a Mutex so we can
/// take ownership during shutdown to kill it explicitly.
///
/// Per ADR-001 — the sidecar is the only Python process Tauri owns. Workers
/// it spawns (echo_worker, future run_audit, etc.) are not Tauri's concern;
/// the sidecar manages those lifetimes itself.
struct SidecarProcess(Mutex<Option<Child>>);

/// Result of spawning the sidecar with metadata about which path was taken.
/// Used purely for logging.
struct SpawnResult {
    child: Child,
    mode: &'static str,
    command: String,
}

/// Choose between the dev-mode Python spawn and the production-mode bundled
/// binary based on Rust's release-build flag.
///
/// - **debug build** (`cargo tauri dev`): spawns `python -m sidecar.main` from
///   `app/sidecar/`. Lets us edit Python and restart without rebuilding the
///   PyInstaller bundle.
/// - **release build** (`cargo tauri build` → bundled `.app` / `.dmg` /
///   `.nsis`): spawns the PyInstaller --onedir binary that Tauri ships as a
///   resource under `binaries/sidecar/sidecar` (see tauri.conf.json
///   `bundle.resources`).
///
/// Both modes write to the same data dir (`~/.platform`) and bind the same
/// port (127.0.0.1:17321 by default). The frontend doesn't know the difference.
fn spawn_sidecar(app: &AppHandle) -> std::io::Result<SpawnResult> {
    if cfg!(debug_assertions) {
        spawn_dev_python(app)
    } else {
        spawn_bundled_binary(app)
    }
}

fn spawn_dev_python(_app: &AppHandle) -> std::io::Result<SpawnResult> {
    let python = std::env::var("PLATFORM_PYTHON")
        .unwrap_or_else(|_| "/opt/homebrew/bin/python3.13".into());

    // Locate app/sidecar/ relative to the running exe. In `cargo tauri dev`
    // the exe lives at app/tauri/target/debug/planning-platform; walking the
    // ancestors finds the repo root, then app/sidecar/.
    let sidecar_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .as_ref()
        .and_then(|d| {
            for ancestor in d.ancestors() {
                let candidate = ancestor.join("app").join("sidecar");
                if candidate.join("sidecar").join("main.py").exists() {
                    return Some(candidate);
                }
            }
            None
        })
        .unwrap_or_else(|| PathBuf::from("../sidecar"));

    let command = format!("{} -m sidecar.main (cwd={})", python, sidecar_dir.display());
    let child = Command::new(&python)
        .args(["-m", "sidecar.main"])
        .current_dir(&sidecar_dir)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()?;
    Ok(SpawnResult {
        child,
        mode: "dev (python -m sidecar.main)",
        command,
    })
}

fn spawn_bundled_binary(app: &AppHandle) -> std::io::Result<SpawnResult> {
    // Resolve the PyInstaller --onedir bundle that was shipped as a Tauri
    // resource (declared in tauri.conf.json: `bundle.resources`). On macOS
    // this lands under `Contents/Resources/binaries/sidecar/`.
    // Windows ships `sidecar.exe`; macOS/Linux ship the extensionless binary.
    // `Path::exists()` requires the EXACT filename — without the .exe suffix
    // on Windows it returns false, spawn returns Err, and (before the
    // companion panic! below) the setup() block swallowed it silently.
    // That's how the auto-spawn died on Ellen's first install.
    let sidecar_rel = if cfg!(target_os = "windows") {
        "binaries/sidecar/sidecar.exe"
    } else {
        "binaries/sidecar/sidecar"
    };
    let sidecar_exe = app
        .path()
        .resolve(sidecar_rel, BaseDirectory::Resource)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::NotFound, e.to_string()))?;

    if !sidecar_exe.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!(
                "bundled sidecar binary not found at {} — was the PyInstaller \
                 build run before `cargo tauri build`? See app/sidecar/PYINSTALLER_NOTES.md",
                sidecar_exe.display()
            ),
        ));
    }

    let command = format!("{} (release bundle)", sidecar_exe.display());
    let mut cmd = Command::new(&sidecar_exe);
    // On Windows the sidecar is a console-subsystem binary. Without
    // CREATE_NO_WINDOW, the OS opens a visible cmd.exe shell behind the app
    // window — confusing for Ellen. The flag suppresses it while leaving the
    // process fully functional. stdout/stderr go to null: the Tauri GUI parent
    // has no console to receive them, and the sidecar logs to
    // data_dir/logs/errors.log for diagnostics.
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000) // CREATE_NO_WINDOW
            .stdout(Stdio::null())
            .stderr(Stdio::null());
    }
    #[cfg(not(target_os = "windows"))]
    cmd.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    let child = cmd.spawn()?;
    Ok(SpawnResult {
        child,
        mode: "release (PyInstaller bundle)",
        command,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar = SidecarProcess(Mutex::new(None));

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(sidecar)
        .setup(|app| {
            // Boot the sidecar before the window finishes loading so the
            // first /health request from React has something to talk to.
            let handle = app.handle();
            match spawn_sidecar(handle) {
                Ok(result) => {
                    println!(
                        "[tauri] sidecar started ({}): {}",
                        result.mode, result.command,
                    );
                    let state = app.state::<SidecarProcess>();
                    *state.0.lock().unwrap() = Some(result.child);
                }
                Err(e) => {
                    // PANIC on purpose. A silent eprintln! here means the
                    // app loads its window, the frontend tries to hit
                    // /health, fails, and the user sees a "dead" UI with no
                    // signal as to why. That was the Windows install-day
                    // failure mode. Crashing here at least surfaces the
                    // problem in the runner log / Windows Event Viewer.
                    //
                    // Diagnostics for the most common causes are included
                    // in the panic message so a single screenshot is enough
                    // to triage.
                    panic!(
                        "[tauri] FAILED to spawn sidecar: {e}\n\
                         hint (dev): set PLATFORM_PYTHON to a python with the \
                         sidecar deps (fastapi, sqlcipher3, ...)\n\
                         hint (prod): ensure `pyinstaller backend.spec` ran and \
                         `app/tauri/binaries/sidecar/` was populated before \
                         `cargo tauri build`"
                    );
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                // Tear down the sidecar on close so we don't leak a Python
                // process if Tauri exits early.
                //
                // Hoist the take() out of the `if let` head so the temporary
                // MutexGuard drops before the `state` binding goes out of
                // scope — borrow-checker requires this in Rust 2021 edition.
                let state = window.state::<SidecarProcess>();
                let maybe_child = state.0.lock().unwrap().take();
                if let Some(mut child) = maybe_child {
                    println!("[tauri] killing sidecar pid={}", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            // Belt-and-braces: also catch the global exit path.
            let state = app_handle.state::<SidecarProcess>();
            let maybe_child = state.0.lock().unwrap().take();
            if let Some(mut child) = maybe_child {
                println!("[tauri] (exit) killing sidecar pid={}", child.id());
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
