"""Gate: the דו"ח התייחסות of four REAL attachments must not change silently (§5).

tests/golden/attachments/*.json hold the expected per-check table for each
real attachment - the three אאורה traffic sheets (12753.1/1, /3, /5) and the
development plan (189-6-plan-08). Lior approves a table before it becomes a
baseline; until then its "_status" says PROPOSED.

TWO HALVES, because the repository is PUBLIC and the real drawings are a
client's - they are not committed (path + md5 in tests/fixtures/real/README.md):

  1. ROWS, in CI: the expected rows of each table must be exactly the rows the
     real mapping selects for that attachment type - guidelines by their
     structural identity (section_key#sort_order), the type's named extra
     checks, the file checks. Change one mapping row and this goes red with
     no file needed.
  2. VERDICTS, wherever the files are (this Mac): every file is run through
     the real API on a fresh database and the whole table - order, codes,
     titles, verdicts - must equal the golden one. Skipped, loudly, where the
     files are absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "sidecar")]

GOLDEN = sorted((ROOT / "tests/golden/attachments").glob("*.json"))
FIXTURES = Path(os.environ.get("GOLDEN_FIXTURES_DIR",
                               Path.home() / "planning-platform-fixtures" / "real"))
FILE_CHECKS = ["ATTACH_FILE_FORMAT", "ATTACH_FILE_PAGES", "ATTACH_FILE_TEXT_LAYER"]
NOTICE = "ATTACH_NO_TEXT_LAYER_NOTICE"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _seed_guidelines():
    rows = _load(ROOT / "app/sidecar/seed/guidelines_seed.json")["guidelines"]
    return [SimpleNamespace(id=i, **{k: r.get(k) for k in (
        "title", "discipline_key", "section_key", "sort_order", "check_key")})
        for i, r in enumerate(rows, 1)]


def test_there_are_four_golden_tables():
    assert len(GOLDEN) == 4, [p.name for p in GOLDEN]


@pytest.mark.parametrize("golden", GOLDEN, ids=[p.stem for p in GOLDEN])
def test_golden_rows_are_what_the_mapping_selects(golden):
    """Half 1 - runs in CI. A mapping change that adds, drops or reorders a
    check for one of these attachment types fails here."""
    from sidecar.attachments import select_guidelines
    g = _load(golden)
    mapping = _load(ROOT / "app/sidecar/seed/attachment_check_mapping.json")
    picked = select_guidelines(mapping, g["attachment_type"], _seed_guidelines())
    extra = mapping["types"].get(g["attachment_type"], {}).get("extra_checks", [])
    expected = ([f"{x.section_key}#{x.sort_order}" for x in picked]
                + ["ATTACH_" + c["id"].upper().replace("-", "_") for c in extra]
                + FILE_CHECKS)
    actual = [r.get("guideline") or r["rule_code"]
              for r in g["checks"] if r["rule_code"] != NOTICE]
    assert actual == expected, (
        f"{golden.name}: the golden rows no longer match the mapping.\n"
        f"  only in golden : {[a for a in actual if a not in expected]}\n"
        f"  only in mapping: {[e for e in expected if e not in actual]}\n"
        "If the mapping change is intended, regenerate the table and get it "
        "approved - do not edit the golden file to make this pass.")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if not FIXTURES.is_dir():
        pytest.skip(f"real attachments not on this machine ({FIXTURES}); the "
                    "repository is public, so they are not in it - see "
                    "tests/fixtures/real/README.md")
    os.environ["PLATFORM_DATA_DIR"] = str(tmp_path_factory.mktemp("golden-data"))
    for m in [m for m in sys.modules if m == "sidecar" or m.startswith("sidecar.")]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    from sidecar.main import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("golden", GOLDEN, ids=[p.stem for p in GOLDEN])
def test_real_attachment_report_matches_golden(golden, client):
    """Half 2 - the whole table, verdicts included, from the real file."""
    g = _load(golden)
    path = FIXTURES / g["file"]
    if not path.exists():
        pytest.skip(f"{g['file']} not in {FIXTURES}")
    assert hashlib.md5(path.read_bytes()).hexdigest() == g["md5"], (
        f"{g['file']} is not the file the golden table was made from")
    pid = client.post("/projects", json={"name_he": "golden",
                                         "tava_number": f"407-golden-{golden.stem}"}).json()["id"]
    with path.open("rb") as f:
        att = client.post(f"/projects/{pid}/attachments",
                          data={"discipline_key": g["attachment_type"]},
                          files={"file": (g["file"], f, "application/pdf")}).json()
    review = client.post(f"/attachments/{att['id']}/run-review").json()
    got = [(c["rule_code"], c["rule_name_he"], c["verdict"]) for c in review["checks"]]
    want = [(r["rule_code"], r["title"], r["verdict"]) for r in g["checks"]]
    diff = [f"  #{i+1}: golden {w}  !=  now {o}"
            for i, (w, o) in enumerate(zip(want, got)) if w != o]
    if len(want) != len(got):
        diff.append(f"  length: golden {len(want)} != now {len(got)}")
    assert not diff, f"{g['file']}: the report changed:\n" + "\n".join(diff)
    assert review["text_layer_ok"] == g["text_layer_ok"]
