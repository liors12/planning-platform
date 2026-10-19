"""The packaged-UI gate must never show a run that did not happen as a pass."""
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("v", ROOT / ".github/scripts/ui_smoke_verdict.py")
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)

CDP_LOG = "Error: WebView2 CDP endpoint :52735 never responded. Last error: TypeError: fetch failed"


def _run(tmp_path, exit_code, log):
    lp = tmp_path / "ui.log"; lp.write_text(log, encoding="utf-8")
    summ = tmp_path / "summary.md"; out = tmp_path / "out.txt"
    os.environ.update(GITHUB_STEP_SUMMARY=str(summ), GITHUB_OUTPUT=str(out), DRY_RUN="1")
    try:
        rc = v.main(["--exit-code", str(exit_code), "--log", str(lp)])
    finally:
        for k in ("GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "DRY_RUN"):
            os.environ.pop(k, None)
    return rc, summ.read_text(encoding="utf-8"), out.read_text(encoding="utf-8")


def test_cdp_never_attached_reports_NOT_RUN_and_does_not_fail_the_build(tmp_path):
    rc, summ, out = _run(tmp_path, 1, CDP_LOG)
    assert rc == 0
    assert "ui_status=NOT_RUN" in out
    assert "NOT RUN" in summ and "This is not a pass" in summ
    assert "PASSED" not in summ


def test_real_ui_failure_still_fails_the_build(tmp_path):
    rc, summ, out = _run(tmp_path, 1, "expect(locator).toBeVisible() failed")
    assert rc == 1 and "ui_status=FAILED" in out


def test_only_an_actual_run_reports_PASSED(tmp_path):
    rc, summ, out = _run(tmp_path, 0, "12 passed (2.1m)")
    assert rc == 0 and "ui_status=PASSED" in out and "NOT RUN" not in summ


def test_not_run_publishes_a_neutral_not_a_success_check():
    assert v.classify(1, CDP_LOG) == "NOT_RUN"
    # the mapping that decides the colour in the commit's checks list
    src = (ROOT / ".github/scripts/ui_smoke_verdict.py").read_text(encoding="utf-8")
    assert '"NOT_RUN": "neutral"' in src
