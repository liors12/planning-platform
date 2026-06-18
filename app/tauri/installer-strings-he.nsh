; Custom Hebrew strings for the Planning Platform NSIS installer.
;
; This file is merged with Tauri's built-in Hebrew.nsh translations at
; bundle time — only LangString entries listed here override the defaults.
; Everything else (page titles, button labels, error messages we haven't
; customized) keeps Tauri's stock Hebrew copy.
;
; Built-in template for reference:
;   https://github.com/tauri-apps/tauri/blob/dev/crates/tauri-bundler/src/bundle/windows/templates/nsis-languages/Hebrew.nsh
; Tauri-side wiring lives in app/tauri/tauri.conf.json
;   bundle.windows.nsis.customLanguageFiles."Hebrew" = "installer-strings-he.nsh"

; Override the "app is running" upgrade prompt. The default Tauri Hebrew
; copy is generic ("התוכנה רצה. לחץ אישור לסגירה"); ours is product-
; specific and uses inclusive Hebrew (לחץ/י) so it reads naturally for
; Ellen and any future female users.
LangString appRunningOkKill ${LANG_HEBREW} "הפלטפורמה פתוחה במחשב. לחץ/י על אישור כדי לסגור אותה ולהתקין את הגרסה החדשה."
