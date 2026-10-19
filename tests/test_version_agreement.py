"""Gate: the three files that carry the app version must agree.

tauri.conf.json sets the installer's version and filename, package.json the
frontend's, Cargo.toml the Rust binary's. The build-windows release job
reads tauri.conf.json, and a tag that disagrees with it is now refused - so
these three are the version, and a drift between them ships a binary whose
parts claim different versions. v0.2.2 shipped labelled "0.2.1" partly
because nothing forced the bump.

All SIX places that record the app's own version are covered. The three
lock/derived ones drifted for four releases before this gate existed:
Cargo.lock and package-lock.json still said 0.1.0, and so did the sidecar's
config.VERSION - which /health reports, so the one field we could use to
learn what Ellen runs was wrong.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(os.environ.get("VERSION_ROOT") or Path(__file__).resolve().parent.parent)
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _versions() -> dict[str, str]:
    tauri = json.loads((ROOT / "app/tauri/tauri.conf.json").read_text(encoding="utf-8"))
    pkg = json.loads((ROOT / "app/frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "app/frontend/package-lock.json").read_text(encoding="utf-8"))
    cargo = (ROOT / "app/tauri/Cargo.toml").read_text(encoding="utf-8")
    m = re.search(r'^\[package\][^\[]*?^version\s*=\s*"([^"]+)"', cargo, re.M | re.S)
    name = re.search(r'^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', cargo, re.M | re.S).group(1)
    clock = (ROOT / "app/tauri/Cargo.lock").read_text(encoding="utf-8")
    cl = re.search(r'\[\[package\]\]\nname = "%s"\nversion = "([^"]+)"' % re.escape(name), clock)
    sidecar = (ROOT / "app/sidecar/sidecar/config.py").read_text(encoding="utf-8")
    sv = re.search(r'^VERSION\s*=\s*"([^"]+)"', sidecar, re.M)
    return {
        "app/tauri/tauri.conf.json": tauri.get("version"),
        "app/frontend/package.json": pkg.get("version"),
        "app/tauri/Cargo.toml [package]": m.group(1) if m else None,
        "app/tauri/Cargo.lock [planning-platform]": cl.group(1) if cl else None,
        "app/frontend/package-lock.json (root)": lock.get("version"),
        "app/frontend/package-lock.json packages[\"\"]": lock["packages"][""].get("version"),
        "app/sidecar/sidecar/config.py VERSION (/health)": sv.group(1) if sv else None,
    }


def test_every_version_place_agrees():
    v = _versions()
    assert len(set(v.values())) == 1, (
        "app version disagrees across files:\n  "
        + "\n  ".join(f"{k}: {val}" for k, val in v.items())
    )


def test_version_is_plain_semver():
    for k, val in _versions().items():
        assert val and SEMVER.match(val), f"{k}: {val!r} is not MAJOR.MINOR.PATCH"
