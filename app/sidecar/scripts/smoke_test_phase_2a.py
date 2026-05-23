#!/opt/homebrew/bin/python3.13
"""End-to-end Phase 2a backend smoke test.

Proves:
  1. Create a project via POST /projects (tava_number 407-1048248)
  2. Upload v24.3 PDF via POST /projects/{id}/submissions
  3. POST /submissions/{id}/run-engine → enqueues a Job
  4. Poll GET /jobs/{id} until status in {completed, failed}
  5. GET /submissions/{id}/findings returns the audit JSON
  6. Verdict counts match the v8j baseline from engine_output_contract.md

Assumes a sidecar is already running on http://127.0.0.1:17321.
Spawn it first with:
    cd app/sidecar && /opt/homebrew/bin/python3.13 -m sidecar.main
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:17321"
TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)

PDF_PATH = Path("/Users/liorlevin/Desktop/planning-platform/projects/407-1048248/submissions/v24.3/v24.3.pdf")

EXPECTED_DISCIPLINES = {"pass": 9, "fail": 8, "requires_review": 16}


def step(n: int, msg: str) -> None:
    print(f"\n=== {n}. {msg} ===", flush=True)


def fail(reason: str) -> "NoReturn":
    print(f"\n❌ SMOKE TEST FAILED: {reason}", flush=True)
    sys.exit(1)


def run() -> int:
    if not PDF_PATH.exists():
        fail(f"v24.3 PDF not found at {PDF_PATH}")

    client = httpx.Client(timeout=TIMEOUT)

    # 0. health check
    step(0, "sidecar /health")
    r = client.get(f"{BASE}/health")
    if r.status_code != 200:
        fail(f"/health returned {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False), flush=True)

    # 1. create project
    step(1, "POST /projects — create 'מתחם הטייסים-ההסתדרות' (תב\"ע 407-1048248)")
    r = client.post(f"{BASE}/projects", json={
        "name_he": "מתחם הטייסים-ההסתדרות",
        "tava_number": "407-1048248",
        "name_en": "Hatayasim-Hahistadrut Complex",
        "address": "נס ציונה",
    })
    if r.status_code != 201:
        fail(f"create project: HTTP {r.status_code} {r.text}")
    project = r.json()
    print(json.dumps(project, indent=2, ensure_ascii=False), flush=True)
    project_id = project["id"]
    if not project["has_schema"]:
        fail(f"project {project_id} reports has_schema=false; engine bridge can't find a schema")

    # 2. upload v24.3 submission
    step(2, "POST /projects/{id}/submissions — upload v24.3 PDF")
    with PDF_PATH.open("rb") as f:
        r = client.post(
            f"{BASE}/projects/{project_id}/submissions",
            data={"version_string": "v24.3"},
            files={"pdf": ("v24.3.pdf", f, "application/pdf")},
        )
    if r.status_code != 201:
        fail(f"upload submission: HTTP {r.status_code} {r.text}")
    submission = r.json()
    print(json.dumps(submission, indent=2, ensure_ascii=False), flush=True)
    submission_id = submission["id"]
    sub_pdf_path = Path(submission["pdf_path"])
    if not sub_pdf_path.exists():
        fail(f"PDF reportedly stored at {sub_pdf_path} but file doesn't exist")
    pdf_size = sub_pdf_path.stat().st_size
    print(f"    stored {pdf_size:,} bytes at {sub_pdf_path}", flush=True)

    # 3. run engine
    step(3, "POST /submissions/{id}/run-engine — enqueue engine job")
    r = client.post(f"{BASE}/submissions/{submission_id}/run-engine")
    if r.status_code != 202:
        fail(f"run-engine: HTTP {r.status_code} {r.text}")
    job = r.json()
    print(json.dumps(job, indent=2, ensure_ascii=False), flush=True)
    job_id = job["id"]

    # 4. poll until terminal
    step(4, f"GET /jobs/{{id}} — poll until status terminal (budget 5 min)")
    deadline = time.time() + 360.0
    last_status = None
    while time.time() < deadline:
        r = client.get(f"{BASE}/jobs/{job_id}")
        if r.status_code != 200:
            fail(f"get job: HTTP {r.status_code} {r.text}")
        j = r.json()
        if j["status"] != last_status:
            print(f"    status → {j['status']}  ({j.get('started_at') or 'not started'})", flush=True)
            last_status = j["status"]
        if j["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    else:
        fail("job did not reach terminal status within 6 minutes")

    if j["status"] == "failed":
        print("    error payload:", j.get("error"), flush=True)
        fail(f"engine job failed: {j.get('error')}")

    print(f"    final job state:\n{json.dumps(j, indent=2, ensure_ascii=False)}", flush=True)

    # 5. get findings
    step(5, "GET /submissions/{id}/findings — fetch raw findings JSON")
    r = client.get(f"{BASE}/submissions/{submission_id}/findings")
    if r.status_code != 200:
        fail(f"get findings: HTTP {r.status_code} {r.text}")
    findings = r.json()
    print(f"    top-level keys: {sorted(findings.keys())}", flush=True)
    print(f"    audit_run_id:   {findings.get('audit_run_id')}", flush=True)

    # 6. verdict counts vs v8j baseline
    step(6, "Verify verdict counts match v8j baseline")
    def counts(rules):
        return dict(Counter(r["verdict"] for r in rules))
    f_counts = counts(findings.get("format", []))
    c_counts = counts(findings.get("content", []))
    d_counts = counts(findings.get("disciplines", []))
    print(f"    format:      {f_counts}", flush=True)
    print(f"    content:     {c_counts}", flush=True)
    print(f"    disciplines: {d_counts}", flush=True)

    # Strict assertion: discipline counts MUST equal 9/8/16 — this is the
    # v8j checkpoint from engine_output_contract.md.
    mismatch = []
    for k, want in EXPECTED_DISCIPLINES.items():
        got = d_counts.get(k, 0)
        if got != want:
            mismatch.append(f"disciplines.{k}={got} expected {want}")
    if mismatch:
        fail("discipline-verdict regression vs v8j baseline:\n  - " + "\n  - ".join(mismatch))

    # 7. submission status verification
    step(7, "GET /submissions/{id} — verify status=complete + findings_json_path set")
    r = client.get(f"{BASE}/submissions/{submission_id}")
    if r.status_code != 200:
        fail(f"get submission: HTTP {r.status_code}")
    sub = r.json()
    print(json.dumps(sub, indent=2, ensure_ascii=False), flush=True)
    if sub["status"] != "complete":
        fail(f"submission status is {sub['status']!r}, expected 'complete'")
    if not sub["findings_json_path"]:
        fail("submission has no findings_json_path after engine completed")

    print("\n✅ SMOKE TEST PASSED — full Phase 2a backend round-trip works end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
