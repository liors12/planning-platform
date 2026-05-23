# Hebrew PDF font assets

Two font directories live in this repo. Both are version-controlled —
the Heebo and NotoSansHebrew families are licensed under SIL Open Font
License 1.1, which permits redistribution as long as the OFL license
text travels with the binaries.

## Where the fonts live

| Directory | Family | Status | Used by |
|---|---|---|---|
| `assets/fonts/` | Heebo (Regular + Bold) | **Tracked.** Used by the current PDF production path (Phase 2a WeasyPrint report). | `compliance_engine/report_generator.py` + the report template |
| `src/pdf/fonts/` *(this dir)* | NotoSansHebrew (Regular + Bold) | **Reserved for Phase 3.** Empty today. Will be tracked once populated. | Future Phase 3 חוות דעת draft generator |

## Renderer expectations (Phase 3)

When the Phase 3 חוות דעת generator lands, it will read NotoSansHebrew
TTFs from this directory. The expected contract:

1. Accept a `--fonts-dir` flag (or `NZC_FONTS_DIR` env var), defaulting
   to this directory (`src/pdf/fonts/`).
2. Read both TTF files, base64-encode them.
3. Substitute `{REGULAR_BASE64}` and `{BOLD_BASE64}` into
   `src/pdf/styles/hebrew-rtl-base.css` before inlining.
4. Fail fast with a clear error if the files aren't present, pointing
   the operator at the styles README for upstream download instructions.

## License

Heebo: SIL OFL 1.1 (Google Fonts).
NotoSansHebrew: SIL OFL 1.1 (Google Fonts).

Both license texts must accompany any binary distribution. The OFL
permits redistribution, which is why these binaries live in the repo
rather than being downloaded at clone time.
