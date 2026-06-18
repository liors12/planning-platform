; Tauri NSIS install hooks.
;
; NSIS_HOOK_PREINSTALL runs after the user clicks "Install" but BEFORE
; any file copying starts — the right window to release locks on files
; we're about to overwrite. Without this, an upgrade-in-place over a
; running app fails partway through with "the process cannot access the
; file because it is being used by another process" and leaves the
; install half-applied.
;
; taskkill /f kills sidecar.exe silently — /f forces, no prompt. If
; sidecar isn't running (fresh install) taskkill returns a non-zero
; exit code which ExecToLog just logs; the install continues either
; way. Same pattern for the Tauri shell process so a running window
; doesn't lock the WebView2 DLLs.
!macro NSIS_HOOK_PREINSTALL
  nsExec::ExecToLog 'taskkill /f /im sidecar.exe'
  ; Tauri bundles the Rust binary as "<productName>.exe" — covers both
  ; the productName variant ("Planning Platform.exe") and the crate-name
  ; variant ("planning-platform.exe") so we don't depend on which one
  ; the bundler emits on a given Tauri version.
  nsExec::ExecToLog 'taskkill /f /im "Planning Platform.exe"'
  nsExec::ExecToLog 'taskkill /f /im "planning-platform.exe"'
!macroend
