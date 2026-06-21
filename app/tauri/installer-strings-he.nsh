; Custom Hebrew strings for the Planning Platform NSIS installer.
;
; This file is included AFTER Tauri's MUI_LANGUAGE "Hebrew" call, so
; every LangString here overrides the NSIS / Tauri defaults for that key.
; Tauri's stock Hebrew.nsh covers only flow/state strings (appRunningOkKill,
; webview2*, etc.) and doesn't define MUI wizard-page body text.  NSIS's
; own Hebrew MUI file leaves some of those bodies empty.  We define them
; all here so every installer screen shows Hebrew rather than blank text.
;
; Built-in Tauri Hebrew.nsh reference:
;   https://github.com/tauri-apps/tauri/blob/dev/crates/tauri-bundler/src/bundle/windows/nsis/languages/Hebrew.nsh
; Tauri-side wiring: app/tauri/tauri.conf.json → bundle.windows.nsis.customLanguageFiles."Hebrew"

; ── "App is running" upgrade prompt ────────────────────────────────────────
; Overrides Tauri's generic copy with a product-specific, inclusive-Hebrew version.
LangString appRunningOkKill ${LANG_HEBREW} "הפלטפורמה פתוחה במחשב. לחצי על אישור כדי לסגור אותה ולהתקין את הגרסה החדשה."

; ── Welcome page ───────────────────────────────────────────────────────────
LangString MUI_TEXT_WELCOME_INFO_TITLE ${LANG_HEBREW} "ברוכות הבאות לאשף ההתקנה של פלטפורמת הסקירה"
LangString MUI_TEXT_WELCOME_INFO_TEXT ${LANG_HEBREW} "אשף זה ינחה אתכם בתהליך ההתקנה של פלטפורמת הסקירה.$\r$\n$\r$\nמומלץ לסגור את כל היישומים האחרים לפני ההמשך.$\r$\n$\r$\nלחצי על הבא להמשך."

; ── Directory (install location) page ─────────────────────────────────────
LangString MUI_TEXT_DIRECTORY_TITLE ${LANG_HEBREW} "בחרי תיקיית התקנה"
LangString MUI_TEXT_DIRECTORY_SUBTITLE ${LANG_HEBREW} "בחרי את התיקייה שבה תותקן פלטפורמת הסקירה."

; ── Start menu shortcuts page ──────────────────────────────────────────────
LangString MUI_TEXT_STARTMENU_TITLE ${LANG_HEBREW} "קיצורי דרך בתפריט התחל"
LangString MUI_TEXT_STARTMENU_SUBTITLE ${LANG_HEBREW} "בחרי תיקייה בתפריט התחל לקיצורי הדרך של הפלטפורמה."

; ── Installation progress page ─────────────────────────────────────────────
LangString MUI_TEXT_INSTALLING_TITLE ${LANG_HEBREW} "מתקינה את פלטפורמת הסקירה"
LangString MUI_TEXT_INSTALLING_SUBTITLE ${LANG_HEBREW} "נא להמתין בזמן שהפלטפורמה מותקנת..."

; ── Finish page ────────────────────────────────────────────────────────────
LangString MUI_TEXT_FINISH_INFO_TITLE ${LANG_HEBREW} "ההתקנה הושלמה בהצלחה"
LangString MUI_TEXT_FINISH_INFO_TEXT ${LANG_HEBREW} "פלטפורמת הסקירה הותקנה בהצלחה.$\r$\nלחצי על סיום לסגירת אשף ההתקנה."
LangString MUI_TEXT_FINISH_RUN_TEXT ${LANG_HEBREW} "הפעילי את פלטפורמת הסקירה"

; ── Uninstall: confirm page ────────────────────────────────────────────────
LangString MUI_UNTEXT_CONFIRM_TITLE ${LANG_HEBREW} "הסרת פלטפורמת הסקירה"
LangString MUI_UNTEXT_CONFIRM_SUBTITLE ${LANG_HEBREW} "פלטפורמת הסקירה תוסר מהמחשב."

; ── Uninstall: progress page ───────────────────────────────────────────────
LangString MUI_UNTEXT_UNINSTALLING_TITLE ${LANG_HEBREW} "מסירה את פלטפורמת הסקירה"
LangString MUI_UNTEXT_UNINSTALLING_SUBTITLE ${LANG_HEBREW} "נא להמתין בזמן שהפלטפורמה מוסרת מהמחשב..."

; ── Uninstall: finish page ─────────────────────────────────────────────────
LangString MUI_UNTEXT_FINISH_INFO_TITLE ${LANG_HEBREW} "ההסרה הושלמה"
LangString MUI_UNTEXT_FINISH_INFO_TEXT ${LANG_HEBREW} "פלטפורמת הסקירה הוסרה בהצלחה מהמחשב.$\r$\nלחצי על סיום."
