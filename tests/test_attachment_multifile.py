"""Gate: an attachment with several files is checked as ONE document (§3g).

A traffic appendix often arrives as one PDF per תא שטח. The rule, the same a
single file already had:
  * an item is present if it is found in ANY file;
  * "לא הוגש" only when every page of every file is readable and none
    mentions it - one unreadable file means absence proves nothing.

The page text is injected (monkeypatched _page_texts) so the gate states the
rule without depending on Hebrew PDF generation; everything else - upload,
storage, guideline selection, verdicts - is the real API.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "app" / "sidecar")]

READABLE_WITH = ("נספח התנועה כולל תכנית מרתף ובה החניון התת קרקעי, חדרי המערכות "
                 "והמחסנים, וטבלת חניה לכל תא שטח עם חניות פרטיות ונגישות. ") * 3
READABLE_WITHOUT = ("גיליון זה מציג את הסדרי התנועה במפלס הקרקע, את הכניסות לחניון "
                    "ואת שבילי ההולכים והרוכבים סביב הבניינים. ") * 3
GARBLED = ("הסינכ הסינ מנ חדריח הפשכ הישסייח חדר תוליע דייריח מיתדימ מתעכ מיקיח "
           "הסינכ מתעכ מיקיח מחזיר קרניסיח יזח חדריח חצר ורתימ לחסיימ רמשכ ") * 3

TEXT_OF = {"with.pdf": [READABLE_WITH], "without.pdf": [READABLE_WITHOUT],
           "without2.pdf": [READABLE_WITHOUT], "garbled.pdf": [GARBLED],
           "broken.pdf": []}                      # could not be opened at all


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_DATA_DIR", str(tmp_path))
    for m in [m for m in sys.modules if m == "sidecar" or m.startswith("sidecar.")]:
        del sys.modules[m]
    from sidecar import attachments as A
    from fastapi.testclient import TestClient
    from sidecar.main import app
    monkeypatch.setattr(A, "_page_texts",
                        lambda p: TEXT_OF.get(Path(p).name, [""]))
    with TestClient(app) as c:
        yield c


def _blank_pdf() -> bytes:
    import fitz
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


def _review(client, names):
    pid = client.post("/projects", json={"name_he": "נספח", "tava_number": "407-0000996"}).json()["id"]
    files = [("files", (n, _blank_pdf(), "application/pdf")) for n in names]
    att = client.post(f"/projects/{pid}/attachments", data={"discipline_key": "sec-3-4"},
                      files=files).json()
    assert [f["name"] for f in att["files"]] == names
    return client.post(f"/attachments/{att['id']}/run-review").json()


def _basement(review):
    return next(c for c in review["checks"] if c["rule_name_he"] == "תכנית מרתף")


def test_found_in_one_file_counts_as_present(client):
    r = _review(client, ["with.pdf", "without.pdf"])          # the hit is NOT the last file
    assert _basement(r)["verdict"] == "requires_review"          # present, not absent
    per = {f["name"]: f for f in r["files"]}
    assert "תכנית מרתף" in per["with.pdf"]["found"]
    assert "תכנית מרתף" not in per["without.pdf"]["found"]


def test_absent_from_every_readable_file_is_not_submitted(client):
    r = _review(client, ["without.pdf", "without2.pdf"])
    assert _basement(r)["verdict"] == "not_submitted"


def test_one_unreadable_file_blocks_not_submitted(client):
    r = _review(client, ["garbled.pdf", "without.pdf"])           # the bad file is NOT the last
    assert not [c for c in r["checks"] if c["verdict"] == "not_submitted"]
    assert r["checks"][0]["rule_name_he"] == "לא ניתן לקרוא את הטקסט בקובץ"


def test_a_file_that_cannot_be_opened_blocks_not_submitted(client):
    """Found by the UI spec: an unopenable file has NO pages, so merged with
    readable files it vanished from the census and "לא הוגש" came back."""
    r = _review(client, ["without.pdf", "without2.pdf", "broken.pdf"])
    assert not [c for c in r["checks"] if c["verdict"] == "not_submitted"]


def test_file_checks_aggregate_and_name_the_files(client):
    r = _review(client, ["without.pdf", "garbled.pdf"])
    pages = next(c for c in r["checks"] if c["rule_code"] == "ATTACH_FILE_PAGES")
    assert "2 קבצים" in pages["notes_he"]
