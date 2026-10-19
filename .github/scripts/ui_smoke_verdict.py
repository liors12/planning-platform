"""Turn the packaged-app UI smoke result into a verdict nobody can misread.

Three outcomes, and only one of them may look green:

  PASSED   Playwright ran and passed.            -> success check, exit 0
  NOT RUN  WebView2 never accepted the CDP       -> NEUTRAL check, exit 0
           attach, so no UI test executed (B-6).    (yellow annotation,
                                                     summary banner)
  FAILED   any other UI failure.                 -> failure check, exit 1

Before this script, the NOT RUN case printed a warning and exited 0, so the
step showed GREEN on every build since ~July 2026 while testing nothing.
A step cannot be coloured yellow; a check run with conclusion=neutral can,
so the honest status is published as its own check run, "UI smoke
(packaged app)". The build is not failed - B-6 stays tracked, not blocking.

Usage:  python ui_smoke_verdict.py --exit-code N --log PATH
Writes  $GITHUB_STEP_SUMMARY, $GITHUB_OUTPUT (ui_status=...), and the check
run when GITHUB_TOKEN/GITHUB_REPOSITORY/GITHUB_SHA are set (DRY_RUN=1 skips).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

CDP_SIGNATURE = re.compile(r"WebView2 CDP endpoint .* never responded")
CHECK_NAME = "UI smoke (packaged app)"


def classify(exit_code: int, log_text: str) -> str:
    if exit_code == 0:
        return "PASSED"
    if CDP_SIGNATURE.search(log_text or ""):
        return "NOT_RUN"
    return "FAILED"


def summary_md(status: str) -> str:
    if status == "PASSED":
        return "### UI smoke (packaged app): PASSED\n\nPlaywright ran against the installed app and passed.\n"
    if status == "NOT_RUN":
        return ("### UI smoke (packaged app): NOT RUN\n\n"
                "> **This is not a pass.** WebView2 never accepted the debugger attach "
                "(`WebView2 CDP endpoint ... never responded`), so **no UI test executed**. "
                "Known runner issue, tracked as B-6. The build is not failed for it, but "
                "nothing about the packaged UI was verified.\n")
    return "### UI smoke (packaged app): FAILED\n\nA UI test ran and failed. See the Playwright report artifact.\n"


def publish_check(status: str) -> None:
    if os.environ.get("DRY_RUN") == "1":
        return
    token, repo, sha = (os.environ.get(k) for k in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_SHA"))
    if not (token and repo and sha):
        return
    conclusion = {"PASSED": "success", "NOT_RUN": "neutral", "FAILED": "failure"}[status]
    title = {"PASSED": "PASSED", "NOT_RUN": "NOT RUN - CDP never attached (B-6)", "FAILED": "FAILED"}[status]
    body = json.dumps({"name": CHECK_NAME, "head_sha": sha, "status": "completed",
                       "conclusion": conclusion,
                       "output": {"title": title, "summary": summary_md(status)}}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/check-runs", data=body,
                                 method="POST", headers={"Authorization": f"Bearer {token}",
                                                         "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:          # a reporting failure must not mask the verdict
        print(f"::warning::could not publish the '{CHECK_NAME}' check run: {exc}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit-code", type=int, required=True)
    ap.add_argument("--log", required=True)
    a = ap.parse_args(argv)
    try:
        text = open(a.log, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    status = classify(a.exit_code, text)
    for env, payload in (("GITHUB_STEP_SUMMARY", summary_md(status)),
                         ("GITHUB_OUTPUT", f"ui_status={status}\n")):
        if os.environ.get(env):
            with open(os.environ[env], "a", encoding="utf-8") as fh:
                fh.write(payload)
    if status == "NOT_RUN":
        print("::warning::UI smoke (packaged app): NOT RUN - WebView2 CDP never attached (B-6). Not a pass.")
    elif status == "FAILED":
        print("::error::UI smoke (packaged app) FAILED - installer will not publish.")
    print(f"UI smoke (packaged app): {status.replace('_', ' ')}")
    publish_check(status)
    return 1 if status == "FAILED" else 0


if __name__ == "__main__":
    sys.exit(main())
