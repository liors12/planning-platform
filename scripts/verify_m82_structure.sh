#!/usr/bin/env bash
# Verify that an audit PDF renders in M8.2 architect-facing format.
#
# Usage:
#   LEVEL=N scripts/verify_m82_structure.sh [PROJECT_KEY] [VERSION]
#
# Levels — each commit in the phase-3-vision → M8.2-default refactor
# tightens to a higher level:
#
#   LEVEL=1  (commit 1: sanitizer integration)
#     Renders the PDF and gates on §3 voice cleanliness (no banned phrases
#     like תואם ויזואלית, כדאי לאמת, נדרשת בדיקה הנדסית, יש לדרוש, כנראה,
#     לא היה לי זמן, ראו 3, לא היה ניתן לוודא, קיים רק מדגם).
#     Auto-regenerates audit_results.m4.sanitized.json when missing or
#     when audit_results.m4.json is newer.
#
#   LEVEL=2  (commit 2: drop §4, §5, נספח א)
#     LEVEL 1 +
#     anchors sec-4, sec-5, sec-appendix-a must NOT appear in HTML.
#     PDF text must NOT contain "סיכום וממצאים סופיים", "היקף הסקירה",
#     or "ליקויי פורמט" (as a standalone label).
#
#   LEVEL=3  (commit 3: drop front-matter + §2א/2ב/2ג)
#     LEVEL 2 +
#     anchors sec-2-section-a, sec-2-section-b, sec-2-section-c must NOT
#     appear. PDF text must NOT contain "חסר / תיקונים / הבהרות".
#
#   LEVEL=4  (commit 4: parcel filter + page cap)
#     LEVEL 3 +
#     PDF text must NOT contain "תא שטח 9".
#     Page count must be ≤ 25.
#
# NOTE: pages ≤ 25 is calibrated for v24.3 (5 audited parcels, 9 §3 disciplines).
# This is a project-specific upper bound, not a general invariant. When a new
# submission arrives with different parcel count or finding density, retune
# the bound at the call site or switch to a relative-growth check.

set -euo pipefail

LEVEL="${LEVEL:-1}"
PROJECT="${1:-407-1048248}"
VER="${2:-24.3}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$REPO_ROOT/audit_outputs/$PROJECT/v$VER"
M4_JSON="$DIR/audit_results.m4.json"
SANITIZED="$DIR/audit_results.m4.sanitized.json"
PDF="$DIR/audit_report_$VER.pdf"
HTML="$DIR/audit_report_$VER.html"
PY="/opt/homebrew/bin/python3.13"

echo "── verify_m82_structure.sh — LEVEL=$LEVEL project=$PROJECT ver=v$VER"

# ─── Pre-flight: m4.json must exist ──────────────────────────────────────
if [[ ! -f "$M4_JSON" ]]; then
  echo "FAIL: $M4_JSON not found. Run a full audit first." >&2
  exit 2
fi

# ─── 0. Auto-regenerate sanitized.json if missing or stale ────────────────
need_regen=0
if [[ ! -f "$SANITIZED" ]]; then
  echo "→ $SANITIZED missing, regenerating..."
  need_regen=1
elif [[ "$M4_JSON" -nt "$SANITIZED" ]]; then
  echo "→ $M4_JSON newer than $SANITIZED, regenerating..."
  need_regen=1
fi
if [[ $need_regen -eq 1 ]]; then
  (cd "$REPO_ROOT" && "$PY" -m vision_scanner.m4.sanitizer_hebrew \
    --input "$M4_JSON" --output "$SANITIZED")
fi

# ─── 1. Render PDF (--render-only prefers sanitized.json automatically) ───
echo "→ rendering PDF..."
(cd "$REPO_ROOT" && "$PY" scripts/run_audit.py --render-only "$PROJECT" "$VER" > /dev/null)

if [[ ! -f "$PDF" || ! -f "$HTML" ]]; then
  echo "FAIL: render did not produce $PDF or $HTML" >&2
  exit 2
fi

# ─── 2. Sanitizer cleanliness (gate at ALL levels — sanitizer is commit 1) ─
echo "→ checking banned phrases in HTML..."
banned_phrases=(
  "תואם ויזואלית"
  "כדאי לאמת"
  "כדאי לבחון"
  "כדאי לבדוק"
  "נדרשת בדיקה הנדסית"
  "יש לדרוש"
  "כנראה"
  "לא היה לי זמן"
  "ראו 3"
  "לא היה ניתן לוודא"
  "קיים רק מדגם"
)
for pat in "${banned_phrases[@]}"; do
  if grep -q "$pat" "$HTML"; then
    n=$(grep -c "$pat" "$HTML")
    echo "FAIL[LEVEL≥1]: HTML contains banned phrase '$pat' ($n× hits)" >&2
    exit 1
  fi
done
echo "  ✓ 0/11 banned phrases in HTML"

# ─── 3. Anchor + label assertions per LEVEL ───────────────────────────────
forbidden_anchors=()
forbidden_labels=()

if [[ $LEVEL -ge 2 ]]; then
  forbidden_anchors+=('sec-4"' 'sec-5"' 'sec-appendix-a')
  forbidden_labels+=("סיכום וממצאים סופיים" "היקף הסקירה" "ליקויי פורמט")
fi
if [[ $LEVEL -ge 3 ]]; then
  forbidden_anchors+=('sec-2-section-a' 'sec-2-section-b' 'sec-2-section-c')
  forbidden_labels+=("חסר / תיקונים / הבהרות")
fi
if [[ $LEVEL -ge 4 ]]; then
  forbidden_labels+=("תא שטח 9")
fi

if [[ ${#forbidden_anchors[@]} -gt 0 ]]; then
  echo "→ checking forbidden anchors (LEVEL=$LEVEL)..."
  for a in "${forbidden_anchors[@]}"; do
    if grep -q "id=\"$a" "$HTML"; then
      n=$(grep -c "id=\"$a" "$HTML")
      echo "FAIL[LEVEL≥$LEVEL]: HTML contains forbidden anchor 'id=\"$a' ($n× hits)" >&2
      exit 1
    fi
  done
  echo "  ✓ ${#forbidden_anchors[@]} forbidden anchors all absent"
fi

if [[ ${#forbidden_labels[@]} -gt 0 ]]; then
  echo "→ checking forbidden labels in PDF text (LEVEL=$LEVEL)..."
  labels_csv=$(printf '%s\n' "${forbidden_labels[@]}")
  "$PY" - "$PDF" <<PY
import sys, fitz
forbidden = """$labels_csv""".strip().splitlines()
text = "\n".join(p.get_text() for p in fitz.open(sys.argv[1]))
bad = [f for f in forbidden if f in text]
if bad:
    print(f"FAIL[LEVEL≥$LEVEL]: PDF contains forbidden labels: {bad}", file=sys.stderr)
    sys.exit(1)
print(f"  ✓ {len(forbidden)} forbidden labels all absent")
PY
fi

# ─── 4. Page count cap at LEVEL=4 ─────────────────────────────────────────
if [[ $LEVEL -ge 4 ]]; then
  pages=$("$PY" -c "import fitz, sys; print(len(fitz.open('$PDF')))")
  if [[ $pages -gt 25 ]]; then
    echo "FAIL[LEVEL≥4]: PDF page count $pages > 25 (project-specific cap for v24.3)" >&2
    exit 1
  fi
  echo "  ✓ page count = $pages (≤ 25)"
fi

echo "OK: verify LEVEL=$LEVEL passed for $PROJECT v$VER"
