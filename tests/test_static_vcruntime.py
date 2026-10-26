"""Gate: the Windows exe links the VC++ runtime statically, and CI proves it.

0.2.2 and 0.2.3 installed fine on a Windows 11 VM without the Visual C++
redistributable and then refused to start: "VCRUNTIME140.dll was not found".
planning-platform.exe imported VCRUNTIME140.dll and VCRUNTIME140_1.dll;
tauri-build 2.6.2 links them in only when STATIC_VCRUNTIME is exactly "true",
and nothing set it. The installer does not ship vc_redist either.

Four things must hold, and this file checks each:
  1. build-windows.yml sets STATIC_VCRUNTIME: "true" for the whole job.
  2. app/tauri/.cargo/config.toml sets it for local builds.
  3. build.rs reruns when it changes (tauri-build does not ask Cargo to).
  4. CI runs scripts/pe_imports.py --forbid-vcruntime on the built exe, so a
     build that still imports the runtime fails before any release step.

WORKFLOWS_DIR / TAURI_DIR override the paths for the red half of a red-green.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = Path(os.environ.get("WORKFLOWS_DIR") or ROOT / ".github/workflows") / "build-windows.yml"
TAURI = Path(os.environ.get("TAURI_DIR") or ROOT / "app/tauri")


def _job() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["build-windows"]


def test_ci_job_sets_static_vcruntime():
    env = _job().get("env") or {}
    assert env.get("STATIC_VCRUNTIME") == "true", (
        f"{WF.name}: jobs.build-windows.env.STATIC_VCRUNTIME must be the string "
        f"\"true\" (got {env.get('STATIC_VCRUNTIME')!r}) - tauri-build compares it "
        "literally"
    )


def test_local_cargo_config_sets_static_vcruntime():
    cfg = TAURI / ".cargo/config.toml"
    assert cfg.exists(), f"{cfg} missing - local Windows builds would link the runtime dynamically"
    env = tomllib.loads(cfg.read_text(encoding="utf-8")).get("env", {})
    assert env.get("STATIC_VCRUNTIME") == "true", f"{cfg}: [env] STATIC_VCRUNTIME must be \"true\""


def test_build_script_reruns_on_the_flag():
    src = (TAURI / "build.rs").read_text(encoding="utf-8")
    assert "cargo:rerun-if-env-changed=STATIC_VCRUNTIME" in src, (
        "build.rs must print cargo:rerun-if-env-changed=STATIC_VCRUNTIME, or a cached "
        "build script keeps the dynamic import"
    )


def test_ci_checks_the_binary_imports_after_the_build():
    steps = _job()["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    build = next(i for i, r in enumerate(runs) if "cargo tauri build --bundles nsis" in r)
    gate = [i for i, r in enumerate(runs)
            if re.search(r"pe_imports\.py\s+--forbid-vcruntime\s+\S*planning-platform\.exe", r)]
    assert gate, "no step runs scripts/pe_imports.py --forbid-vcruntime on planning-platform.exe"
    assert gate[0] > build, "the import gate must run after the release build"
    release = [i for i, s in enumerate(steps) if "action-gh-release" in str(s.get("uses", ""))]
    assert all(gate[0] < r for r in release), "the import gate must run before any release step"
    assert not steps[gate[0]].get("continue-on-error"), "the import gate must be able to fail the job"
