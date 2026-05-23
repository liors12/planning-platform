# Hebrew RTL PDF styles — staged, not yet active

This directory holds CSS that the future Hebrew PDF renderer will use. It is **not wired into any code path yet** — there is no rendering module to consume it.

## What's here

- **[hebrew-rtl-base.css](hebrew-rtl-base.css)** — the base stylesheet for Hebrew RTL PDFs in the NZC planning compliance platform. Provides typography (NotoSansHebrew via two `@font-face` rules with `{REGULAR_BASE64}` / `{BOLD_BASE64}` placeholders), the page-block components (cover banner, info boxes, tables, score card, action card, timeline cells, FAQ blocks), and the NZC color palette (`#005030` primary green, `#007840` brand green; status colors preserved).

## Why it's not integrated yet

The CSS sits here because the project decided on its PDF stack early — see *Architectural Decisions → PDF rendering for Hebrew output* in [`CONTEXT.md`](../../../CONTEXT.md) — but no Hebrew PDF actually needs to be generated until **Phase 3** (the חוות דעת draft generator). Until then:

- All intermediate outputs are Markdown.
- No `wkhtmltopdf` binary or `NotoSansHebrew` font asset is added to the project's dependencies.
- The renderer module (`src/pdf/render.py` or similar) does not exist.

Building the renderer earlier would be busywork — there's nothing to render. Saving the CSS now means we lose nothing if the source skill becomes unavailable later.

## Source

Adapted from the workspace skill **`keyword-feasibility-report`** (its `SKILL.md` § *FULL CSS*). That skill has battle-tested Hebrew RTL PDF generation against `wkhtmltopdf` with NotoSansHebrew embedded as base64. The CSS here is a verbatim copy with **only the brand colors swapped** to NZC's palette:

| Veedda (skill default) | NZC (this project) |
|---|---|
| `#1a1a2e` (dark navy) | `#005030` (NZC primary green) |
| `#0f3460` (brand blue) | `#007840` (NZC brand green) |

All other colors (status reds/ambers/greens/blues, neutrals, backgrounds) are preserved.

## When this becomes active

**Phase 3 — חוות דעת draft generator.** The renderer will:

1. Build an HTML document with `<html dir="rtl">` plus this CSS inlined into a `<style>` block.
2. Replace `{REGULAR_BASE64}` and `{BOLD_BASE64}` with actual base64-encoded NotoSansHebrew TTF data.
3. Shell out to `wkhtmltopdf` (with the flags documented in the source skill) to produce the final PDF.

## Do NOT use this CSS with

- **ReportLab** — Hebrew renders incorrectly.
- **WeasyPrint** — produces *visual-order* Hebrew that breaks copy/paste/search in the resulting PDFs.
- **Chrome headless `--print-to-pdf`** — same visual-order problem as WeasyPrint.

The CSS is shaped for `wkhtmltopdf`'s rendering quirks specifically. Other engines may need a different stylesheet.

## Required font files (Phase 3)

When implementing the rendering module, NotoSansHebrew TTF files will need to be base64-embedded into generated HTML (replacing the `{REGULAR_BASE64}` and `{BOLD_BASE64}` placeholders in `hebrew-rtl-base.css`). Source:

> https://fonts.google.com/specimen/Noto+Sans+Hebrew

Download the family, extract `NotoSansHebrew-Regular.ttf` and `NotoSansHebrew-Bold.ttf`. License: **SIL Open Font License 1.1** — redistribution is allowed, but the license text must accompany any binary distribution.

**Do NOT commit the TTF files to the repo.** The renderer should read them from a configurable path (default: `src/pdf/fonts/`), and `src/pdf/fonts/` should be in `.gitignore` with its own `README.md` pointing back to this section.
