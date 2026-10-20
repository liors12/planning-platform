"""Gate: every dependency is pinned, and CI installs only what is pinned (B-21).

Until v0.2.2 the sidecar's requirements.txt held floors only (`PyMuPDF>=1.24`),
so each build installed whatever was newest that morning. Between the July 27
and the October 19 green builds 36 of 63 Python packages changed with no change
of ours, and PyMuPDF 2.0 broke the packaged audit engine outright. A build that
passes today proved nothing about the build that ships tomorrow.

The rule now:

    requirements.in / -build.in / -dev.in   direct deps, EXACT pins (==)
    requirements-windows.txt                 full lock, packaged build (uv)
    requirements-linux.txt                   full lock, CI test suite (uv)
    package-lock.json  (npm ci)              every package.json
    Cargo.lock         (--locked)            the Tauri app
    actions @<sha>, rust 1.99.1, tauri-cli / tauri-driver @=x.y.z

Versions move only through the monthly Dependabot PR (.github/dependabot.yml),
which a person merges.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SIDECAR = ROOT / "app" / "sidecar"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

INPUTS = ("requirements.in", "requirements-build.in", "requirements-dev.in")
# lock file -> (input files it is compiled from, platform marker it serves)
LOCKS = {
    "requirements-windows.txt": (("requirements.in", "requirements-build.in"), "win32"),
    "requirements-linux.txt": (("requirements.in", "requirements-dev.in"), "linux"),
}

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]+\])?==([^\s;]+)\s*(;.*)?$")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_lines(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _pins(path: Path) -> dict[str, tuple[str, str]]:
    """name -> (version, marker) for a file whose every line is an exact pin."""
    pins = {}
    for line in _req_lines(path):
        m = PIN.match(line)
        assert m, f"{path.name}: not an exact pin: {line!r}"
        pins[_norm(m.group(1))] = (m.group(3), (m.group(4) or "").lstrip("; ").strip())
    return pins


def _marker_applies(marker: str, platform: str) -> bool:
    if not marker:
        return True
    m = re.fullmatch(r'sys_platform\s*(==|!=)\s*"([^"]+)"', marker)
    assert m, f"marker the gate does not understand: {marker!r}"
    return (m.group(2) == platform) == (m.group(1) == "==")


def test_no_floor_only_requirements_file_remains():
    assert not (SIDECAR / "requirements.txt").exists(), (
        "app/sidecar/requirements.txt is back. It held floors (>=) only; "
        "pins live in requirements*.in and the per-platform locks.")


@pytest.mark.parametrize("name", INPUTS)
def test_every_direct_dependency_is_pinned_exactly(name):
    bad = [l for l in _req_lines(SIDECAR / name) if not PIN.match(l)]
    assert not bad, (f"{name}: unpinned or loosely pinned dependencies "
                     f"(use ==, the version of the last green build):\n  "
                     + "\n  ".join(bad))


@pytest.mark.parametrize("lock", LOCKS)
def test_lock_files_pin_every_package(lock):
    _pins(SIDECAR / lock)          # asserts each line is ==


@pytest.mark.parametrize("lock", LOCKS)
def test_lock_agrees_with_its_inputs(lock):
    """A pin bumped in a .in file without re-locking is an out-of-sync lock."""
    sources, platform = LOCKS[lock]
    locked = _pins(SIDECAR / lock)
    wrong = []
    for src in sources:
        for name, (ver, marker) in _pins(SIDECAR / src).items():
            applies = _marker_applies(marker, platform)
            if applies and locked.get(name, (None,))[0] != ver:
                wrong.append(f"{src}: {name}=={ver}, {lock}: "
                             f"{locked.get(name, ('missing',))[0]}")
            if not applies and name in locked:
                wrong.append(f"{lock} carries {name}, excluded on {platform}")
    assert not wrong, ("lock out of sync with its inputs - re-run the uv "
                       "command in the lock's header:\n  " + "\n  ".join(wrong))


@pytest.mark.parametrize("lock", LOCKS)
def test_lock_regenerates_identically(lock, tmp_path):
    """The strong form of 'in sync': re-running the lock's own command, with
    the lock as uv's preference file, must reproduce it line for line. Catches
    a deleted or added package and a hand-edited pin that no longer resolves
    (starlette 1.9.0 -> 0.27.0 fails it), which the input comparison cannot see.

    Measured limit: a hand-edit to ANOTHER VALID version (anyio 4.15.1 ->
    4.15.0) passes, because uv keeps any preference that still resolves. That
    lock is consistent, just different - review the lock diff in the PR."""
    uv = shutil.which("uv")
    if not uv:
        pytest.skip("uv not installed (it is in requirements-dev.in)")
    text = (SIDECAR / lock).read_text(encoding="utf-8")
    cmd = re.search(r"^#\s+uv pip compile (.+)$", text, re.M)
    assert cmd, f"{lock}: header does not record the uv command"
    args = cmd.group(1).split()
    out = tmp_path / lock
    out.write_text(text, encoding="utf-8")
    args[args.index("-o") + 1] = str(out)
    r = subprocess.run([uv, "pip", "compile", *args, "-q"], cwd=SIDECAR,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 and ("network" in r.stderr.lower()
                              or "failed to fetch" in r.stderr.lower()):
        pytest.skip(f"no network for uv: {r.stderr.strip()[:200]}")
    assert r.returncode == 0, f"uv failed:\n{r.stderr}"
    body = lambda s: [l for l in s.splitlines() if not l.startswith("#")]
    assert body(out.read_text(encoding="utf-8")) == body(text), (
        f"{lock} is not what its own command produces - regenerate it")


def _run_lines():
    for wf in WORKFLOWS:
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue                     # a comment documents, it does not run
            code = line.split(" #", 1)[0]
            if code.strip():
                yield wf.name, i, code


def test_ci_installs_python_packages_only_from_a_lock():
    lock = r"(app/sidecar/)?requirements-(windows|linux)\.txt|/tmp/reqs\.txt"
    bad = []
    for wf, i, code in _run_lines():
        if re.search(r"\bpip install\b", code) and not re.search(
                rf"(-r|-c)\s+({lock})", code):
            bad.append(f"{wf}:{i}: {code.strip()}")
    assert not bad, ("pip install outside the locks (use -r <lock> or "
                     "-c <lock> <pkg>):\n  " + "\n  ".join(bad))


def test_reqs_tmp_file_is_cut_from_the_lock():
    """qa-suite strips sqlcipher3 into /tmp/reqs.txt; it must come from a lock."""
    for wf, i, code in _run_lines():
        if "> /tmp/reqs.txt" in code:
            assert "requirements-linux.txt" in code, f"{wf}:{i}: {code.strip()}"


def test_npm_uses_ci_never_install():
    bad = [f"{wf}:{i}: {c.strip()}" for wf, i, c in _run_lines()
           if re.search(r"\bnpm (install|i)\b", c)]
    assert not bad, "npm install in CI (use npm ci):\n  " + "\n  ".join(bad)


def test_every_package_json_has_a_committed_lock():
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                 text=True).stdout.split())
    missing = [p for p in tracked if p.endswith("package.json")
               and "node_modules" not in p
               and p.replace("package.json", "package-lock.json") not in tracked]
    assert not missing, f"package.json without a committed lock: {missing}"


def test_cargo_lock_is_committed_and_builds_use_it():
    tracked = subprocess.run(["git", "ls-files", "app/tauri/Cargo.lock"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    assert tracked, "app/tauri/Cargo.lock is not committed"
    bad = [f"{wf}:{i}: {c.strip()}" for wf, i, c in _run_lines()
           if re.search(r"cargo tauri build\b", c) and "--locked" not in c]
    assert not bad, "cargo tauri build without -- --locked:\n  " + "\n  ".join(bad)


def test_github_actions_are_pinned_to_a_commit():
    bad = [f"{wf}:{i}: {c.strip()}" for wf, i, c in _run_lines()
           if re.search(r"\buses:\s*\S+@", c)
           and not re.search(r"@[0-9a-f]{40}\b", c)]
    assert not bad, ("action pinned to a moving tag/branch (pin the commit SHA, "
                     "tag in a comment):\n  " + "\n  ".join(bad))


def test_rust_toolchain_and_cargo_tools_are_exact():
    text = (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert re.search(r"toolchain:\s*1\.\d+\.\d+\b", text), "rust toolchain not pinned"
    loose = [c.strip() for _, _, c in _run_lines()
             if re.search(r"cargo binstall\b", c)
             and not re.search(r"(tauri-cli|tauri-driver)@=", c)
             and "TAURI_CLI" not in c]
    assert not loose, "cargo binstall without an exact version:\n  " + "\n  ".join(loose)
    assert re.search(r"TAURI_CLI=\d+\.\d+\.\d+", text), "tauri-cli version not exact"
    assert '"tauri-cli@=$TAURI_CLI"' in text


def test_upgrades_arrive_as_monthly_prs_never_auto_merged():
    dep = ROOT / ".github" / "dependabot.yml"
    assert dep.exists(), ".github/dependabot.yml is missing"
    text = dep.read_text(encoding="utf-8")
    for eco in ("pip", "npm", "cargo", "github-actions"):
        assert f"package-ecosystem: {eco}" in text, f"dependabot: no {eco} entry"
    assert text.count("interval: monthly") == 4
    for wf in WORKFLOWS:
        assert "merge --auto" not in wf.read_text(encoding="utf-8"), (
            f"{wf.name}: auto-merge - upgrade PRs are merged by a person")


def test_windows_build_runs_only_on_main_tags_and_dispatch():
    """Decided 2026-10-20 (minutes): no full Windows build on pull requests.
    Dependency PRs are covered by the QA suite and this lock gate."""
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))      # PyYAML reads the bare key `on` as True
    assert "pull_request" not in on and "pull_request_target" not in on, on
    assert set(on) == {"workflow_dispatch", "push"}, set(on)
    assert on["push"]["branches"] == ["main"] and "v*" in on["push"]["tags"]
