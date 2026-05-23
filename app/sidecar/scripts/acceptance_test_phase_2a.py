#!/opt/homebrew/bin/python3.13
"""Phase 2a acceptance test — 8 criteria from the Phase 2a kickoff brief.

This test exercises every endpoint the frontend uses, in the order the
acceptance scenario walks through. The sidecar is restarted mid-test to prove
persistence (criterion 5).

Run:
    /opt/homebrew/bin/python3.13 app/sidecar/scripts/acceptance_test_phase_2a.py

Requires:
    * sidecar NOT running on 127.0.0.1:17321 (this script starts/stops it)
    * v24.3 PDF available at projects/407-1048248/submissions/v24.3/v24.3.pdf
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # planning-platform/
BASE = "http://127.0.0.1:17321"
TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)
PDF_PATH = REPO_ROOT / "projects/407-1048248/submissions/v24.3/v24.3.pdf"

EXPECTED_DISCIPLINES = {"pass": 9, "fail": 8, "requires_review": 16}

results: list[tuple[int, str, str]] = []   # (criterion#, label, status_string)


def report(criterion: int, label: str, status: str) -> None:
    results.append((criterion, label, status))
    icon = "✅" if status.startswith("PASS") else "❌"
    print(f"  {icon} criterion {criterion} — {label}: {status}", flush=True)


def hr(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def start_sidecar() -> subprocess.Popen:
    """Spawn the sidecar in a subprocess. Returns when /health is reachable."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        ["/opt/homebrew/bin/python3.13", "-m", "sidecar.main"],
        cwd=str(REPO_ROOT / "app" / "sidecar"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15.0
    while time.time() < deadline:
        try:
            httpx.get(f"{BASE}/health", timeout=1.0)
            return proc
        except (httpx.HTTPError, httpx.RequestError):
            time.sleep(0.3)
    proc.kill()
    raise RuntimeError("sidecar did not come up within 15s")


def kill_sidecar(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def wipe_db():
    home = Path.home() / ".platform"
    for f in ("platform.db", "platform.db-wal", "platform.db-shm"):
        p = home / f
        if p.exists():
            p.unlink()
    proj = home / "projects"
    if proj.exists():
        shutil.rmtree(proj)


def main() -> int:
    # ── Setup ────────────────────────────────────────────────────────────
    if not PDF_PATH.exists():
        print(f"FATAL: PDF not at {PDF_PATH}", file=sys.stderr)
        return 1

    # Kill any existing sidecar
    subprocess.run(["pkill", "-f", "sidecar.main"], capture_output=True)
    subprocess.run(["pkill", "-f", "Planning Platform.app"], capture_output=True)
    time.sleep(1)
    wipe_db()

    hr("Boot fresh sidecar")
    proc = start_sidecar()
    print("  sidecar up", flush=True)

    client = httpx.Client(timeout=TIMEOUT)
    project_id_pilot: int = -1
    project_id_second: int = -1
    submission_id: int = -1

    try:
        # ── Criterion 1: create project via API ──────────────────────
        hr("Criterion 1 — Create 'מתחם הטייסים-ההסתדרות' (407-1048248)")
        r = client.post(f"{BASE}/projects", json={
            "name_he": "מתחם הטייסים-ההסתדרות",
            "tava_number": "407-1048248",
            "name_en": "Hatayasim-Hahistadrut Complex",
            "address": "נס ציונה",
        })
        if r.status_code != 201:
            report(1, "POST /projects", f"FAIL HTTP {r.status_code}: {r.text}")
            return 2
        project = r.json()
        project_id_pilot = project["id"]
        if not project["has_schema"]:
            report(1, "has_schema flag", "FAIL — schema not detected")
            return 2
        report(1, f"created id={project_id_pilot}, has_schema=true", "PASS")

        # ── Criterion 2: upload v24.3 PDF ────────────────────────────
        hr("Criterion 2 — Upload v24.3 PDF")
        with PDF_PATH.open("rb") as f:
            r = client.post(
                f"{BASE}/projects/{project_id_pilot}/submissions",
                data={"version_string": "v24.3"},
                files={"pdf": ("v24.3.pdf", f, "application/pdf")},
            )
        if r.status_code != 201:
            report(2, "POST submissions", f"FAIL HTTP {r.status_code}: {r.text}")
            return 2
        sub = r.json()
        submission_id = sub["id"]
        size = Path(sub["pdf_path"]).stat().st_size
        report(2, f"submission id={submission_id}, {size:,} bytes stored", "PASS")

        # ── Criterion 3: Run Engine, status queued → running → complete ──
        hr("Criterion 3 — Run Engine + watch status transitions")
        r = client.post(f"{BASE}/submissions/{submission_id}/run-engine")
        if r.status_code != 202:
            report(3, "POST run-engine", f"FAIL HTTP {r.status_code}: {r.text}")
            return 2
        job_id = r.json()["id"]
        seen_statuses: list[str] = []
        deadline = time.time() + 240.0
        final_status = None
        while time.time() < deadline:
            j = client.get(f"{BASE}/jobs/{job_id}").json()
            s = j["status"]
            if not seen_statuses or seen_statuses[-1] != s:
                seen_statuses.append(s)
                print(f"    status → {s}", flush=True)
            if s in ("completed", "failed"):
                final_status = s
                break
            time.sleep(2)
        else:
            report(3, "status transitions", "FAIL — job didn't terminate within 4 min")
            return 2
        if final_status != "completed":
            report(3, "final status", f"FAIL — got {final_status}, expected completed")
            return 2
        # Verify the queue produced the expected status sequence (queued may or
        # may not be observed depending on poll timing; running + completed are
        # guaranteed).
        if "running" not in seen_statuses or "completed" not in seen_statuses:
            report(3, "transitions", f"FAIL — missing running/completed in {seen_statuses}")
            return 2
        report(3, f"transitions: {' → '.join(seen_statuses)}", "PASS")

        # ── Criterion 4: findings JSON returned ──────────────────────
        hr("Criterion 4 — Fetch findings, verify shape + verdict counts")
        r = client.get(f"{BASE}/submissions/{submission_id}/findings")
        if r.status_code != 200:
            report(4, "GET findings", f"FAIL HTTP {r.status_code}: {r.text}")
            return 2
        findings = r.json()
        expected_keys = {"format", "content", "disciplines", "extraction_cache",
                         "extracts_overlay", "feedback_entries", "audit_run_id"}
        if not expected_keys.issubset(findings.keys()):
            report(4, "JSON keys", f"FAIL — missing {expected_keys - set(findings.keys())}")
            return 2
        d_counts = dict(Counter(r["verdict"] for r in findings.get("disciplines", [])))
        if d_counts != EXPECTED_DISCIPLINES:
            report(4, "discipline counts", f"FAIL — {d_counts} != {EXPECTED_DISCIPLINES}")
            return 2
        report(4, f"disciplines: {d_counts}; audit_run_id={findings.get('audit_run_id')}", "PASS")

        # ── Criterion 5: restart, verify persistence ────────────────
        hr("Criterion 5 — Restart sidecar; project, submission, findings persist")
        kill_sidecar(proc)
        time.sleep(1)
        proc = start_sidecar()
        print("  sidecar back up", flush=True)
        r = client.get(f"{BASE}/projects/{project_id_pilot}")
        if r.status_code != 200:
            report(5, "GET project after restart", f"FAIL HTTP {r.status_code}")
            return 2
        if r.json()["name_he"] != "מתחם הטייסים-ההסתדרות":
            report(5, "project survives", "FAIL — name_he mismatched after restart")
            return 2
        r = client.get(f"{BASE}/submissions/{submission_id}")
        if r.status_code != 200 or r.json()["status"] != "complete":
            report(5, "submission survives", f"FAIL — {r.status_code} {r.text}")
            return 2
        r = client.get(f"{BASE}/submissions/{submission_id}/findings")
        if r.status_code != 200:
            report(5, "findings survive", f"FAIL HTTP {r.status_code}")
            return 2
        d_counts2 = dict(Counter(r["verdict"] for r in r.json().get("disciplines", [])))
        if d_counts2 != EXPECTED_DISCIPLINES:
            report(5, "findings byte-identical?", f"FAIL — counts changed: {d_counts2}")
            return 2
        report(5, "project + submission + findings all persisted after restart", "PASS")

        # ── Criterion 6: sidebar shows correct status badge ─────────
        hr("Criterion 6 — list_projects exposes status badge data")
        r = client.get(f"{BASE}/projects")
        if r.status_code != 200:
            report(6, "GET /projects", f"FAIL HTTP {r.status_code}")
            return 2
        pilot = next((p for p in r.json() if p["id"] == project_id_pilot), None)
        if pilot is None:
            report(6, "pilot in list", "FAIL")
            return 2
        if pilot["status"] != "active":
            report(6, "status badge", f"FAIL — got {pilot['status']}, expected active")
            return 2
        if pilot["submission_count"] != 1:
            report(6, "submission_count", f"FAIL — got {pilot['submission_count']}")
            return 2
        if pilot["latest_submission"] is None or pilot["latest_submission"]["status"] != "complete":
            report(6, "latest_submission", f"FAIL — {pilot['latest_submission']}")
            return 2
        report(6, f"sidebar payload: status=active, submission_count=1, latest=complete", "PASS")

        # ── Criterion 7: 2nd project, switching preserves state ─────
        hr("Criterion 7 — Create 2nd project; switching preserves each one's state")
        r = client.post(f"{BASE}/projects", json={
            "name_he": "פרויקט בדיקה שני",
            "tava_number": "999-0000000",
        })
        if r.status_code != 201:
            report(7, "POST 2nd project", f"FAIL HTTP {r.status_code}")
            return 2
        project_id_second = r.json()["id"]
        if r.json()["has_schema"]:
            report(7, "2nd project has_schema", "FAIL — 999-0000000 shouldn't have schema")
            return 2
        # Now fetch each project and verify their state is independent
        p1 = client.get(f"{BASE}/projects/{project_id_pilot}").json()
        p2 = client.get(f"{BASE}/projects/{project_id_second}").json()
        if p1["submission_count"] != 1 or p2["submission_count"] != 0:
            report(7, "independent state", f"FAIL — p1={p1['submission_count']} p2={p2['submission_count']}")
            return 2
        if p1["has_schema"] is False or p2["has_schema"] is True:
            report(7, "independent has_schema", "FAIL")
            return 2
        report(7, f"p1(has_schema=true, 1 sub) vs p2(has_schema=false, 0 sub) — independent", "PASS")

        # ── Criterion 8: engine failure surfaces a useful error ─────
        hr("Criterion 8 — Engine failure (schema missing) surfaces useful error")
        # Upload a fake PDF to the 2nd project so we can try to run-engine.
        # The endpoint should reject with 409 ("no schema").
        with PDF_PATH.open("rb") as f:
            r = client.post(
                f"{BASE}/projects/{project_id_second}/submissions",
                data={"version_string": "v1.0"},
                files={"pdf": ("anything.pdf", f, "application/pdf")},
            )
        if r.status_code != 201:
            report(8, "upload to 2nd project", f"FAIL HTTP {r.status_code}: {r.text}")
            return 2
        sub2_id = r.json()["id"]
        r = client.post(f"{BASE}/submissions/{sub2_id}/run-engine")
        if r.status_code != 409:
            report(8, "run-engine no-schema", f"FAIL — expected 409, got {r.status_code}: {r.text}")
            return 2
        err_body = r.text
        if "schema" not in err_body.lower():
            report(8, "useful error message", f"FAIL — error doesn't mention 'schema': {err_body}")
            return 2
        report(8, f"HTTP 409 with schema-explanation message", "PASS")

        # ── Summary ─────────────────────────────────────────────────
        hr("All criteria summary")
        for i, label, status in results:
            icon = "✅" if status.startswith("PASS") else "❌"
            print(f"  {icon} {i}. {label}", flush=True)
        all_pass = all(s.startswith("PASS") for _, _, s in results)
        if not all_pass:
            return 3
        print("\n🎯 PHASE 2A ACCEPTANCE TEST: ALL 8 CRITERIA PASSED.", flush=True)
        return 0

    finally:
        kill_sidecar(proc)


if __name__ == "__main__":
    sys.exit(main())
