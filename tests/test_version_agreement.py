"""Gate: the three files that carry the app version must agree.

tauri.conf.json sets the installer's version and filename, package.json the
frontend's, Cargo.toml the Rust binary's. The build-windows release job
reads tauri.conf.json, and a tag that disagrees with it is now refused - so
these three are the version, and a drift between them ships a binary whose
parts claim different versions. v0.2.2 shipped labelled "0.2.1" partly
because nothing forced the bump.

Not covered, deliberately: Cargo.lock and package-lock.json record the app's
own version too, and both still say 0.1.0 - drifted since before 0.1.1.
Builds do not run --locked, so it has never broken anything; see the release
report before tightening this gate to include them.
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
    cargo = (ROOT / "app/tauri/Cargo.toml").read_text(encoding="utf-8")
    m = re.search(r'^\[package\][^\[]*?^version\s*=\s*"([^"]+)"', cargo, re.M | re.S)
    return {
        "app/tauri/tauri.conf.json": tauri.get("version"),
        "app/frontend/package.json": pkg.get("version"),
        "app/tauri/Cargo.toml [package]": m.group(1) if m else None,
    }


def test_the_three_version_files_agree():
    v = _versions()
    assert len(set(v.values())) == 1, (
        "app version disagrees across files:\n  "
        + "\n  ".join(f"{k}: {val}" for k, val in v.items())
    )


def test_version_is_plain_semver():
    for k, val in _versions().items():
        assert val and SEMVER.match(val), f"{k}: {val!r} is not MAJOR.MINOR.PATCH"
