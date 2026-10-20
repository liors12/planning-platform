"""Gate: the overview tab's "זמן מאז אישור התב"ע" reads as Hebrew (v0.2.3 §3c).

Runs the REAL app/frontend/src/lib/duration.ts through esbuild + node, the
same way tests/test_bidi_isolation.py runs the bidi rule.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "app/frontend"

# (approval date, today, expected)
CASES = [
    ("2025-08-06", "2026-10-20", "שנה וחודשיים"),     # 407-1048248 today
    ("2026-05-17", "2026-10-20", "5 חודשים"),
    ("2026-10-01", "2026-10-20", "פחות מחודש"),
    ("2026-09-20", "2026-10-20", "חודש"),
    ("2026-08-20", "2026-10-20", "חודשיים"),
    ("2026-08-21", "2026-10-20", "חודש"),            # second month not complete
    ("2025-10-20", "2026-10-20", "שנה"),
    ("2024-10-20", "2026-10-20", "שנתיים"),
    ("2024-09-01", "2026-10-20", "שנתיים וחודש"),
    ("2023-08-01", "2026-10-20", "3 שנים וחודשיים"),
    ("2016-01-01", "2026-10-20", "10 שנים ו-9 חודשים"),
    ("2027-01-01", "2026-10-20", None),               # future: not shown
    ("06/08/2025", "2026-10-20", None),               # not ISO: not shown
]


def _run():
    esbuild = FE / "node_modules/.bin/esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed (run npm ci in app/frontend)")
    entry = FE / "src" / "_duration_entry.ts"
    bundle = FE / "_duration_bundle.mjs"
    entry.write_text(
        'import { timeSince } from "./lib/duration";\n'
        f"const C = {json.dumps(CASES, ensure_ascii=False)};\n"
        "console.log(JSON.stringify(C.map(([a, t]) => {\n"
        "  const [y, m, d] = (t as string).split('-').map(Number);\n"
        "  return timeSince(a as string, new Date(y, m - 1, d));\n"
        "})));\n", encoding="utf-8")
    try:
        b = subprocess.run([str(esbuild), str(entry), "--bundle", "--format=esm",
                            "--platform=node", f"--outfile={bundle}", "--log-level=error"],
                           capture_output=True, text=True, cwd=str(FE))
        assert b.returncode == 0, b.stderr
        r = subprocess.run(["node", str(bundle)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    finally:
        entry.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


def test_time_since_approval_reads_as_hebrew():
    got = _run()
    wrong = [f"{a} -> {t}: expected {e!r}, got {g!r}"
             for (a, t, e), g in zip(CASES, got) if g != e]
    assert not wrong, "\n".join(wrong)
