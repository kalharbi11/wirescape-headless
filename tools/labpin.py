#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read, verify and fetch the lab commit named in LAB_PIN (lab proposals/0025 §5.2).

Standard library only. Written for H-0 to the wirescape-test LAB_PIN pattern (0024 §2.2);
alignment with wirescape-test tools/wstest.py is a tracked follow-up.

  python tools/labpin.py show              print repo, commit and date
  python tools/labpin.py verify [--remote] check the file's format (and that the commit exists)
  python tools/labpin.py fetch DIR         shallow-fetch the pinned commit into DIR
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN_FILE = ROOT / "LAB_PIN"
KEYS = ("repo", "commit", "pinned")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class PinError(ValueError):
    pass


def parse(text: str) -> dict[str, str]:
    """Parse LAB_PIN text: `key=value` lines, `#` comments and blank lines."""
    pin: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PinError(f"line {n}: expected key=value")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in KEYS:
            raise PinError(f"line {n}: unknown key {key!r}")
        if key in pin:
            raise PinError(f"line {n}: duplicate key {key!r}")
        pin[key] = value
    missing = [k for k in KEYS if k not in pin]
    if missing:
        raise PinError("missing " + ", ".join(missing))
    if not _REPO.match(pin["repo"]):
        raise PinError(f"repo {pin['repo']!r} is not owner/name")
    if not _SHA.match(pin["commit"]):
        raise PinError("commit must be a full 40-character lowercase SHA")
    try:
        _dt.date.fromisoformat(pin["pinned"])
    except ValueError:
        raise PinError(f"pinned {pin['pinned']!r} is not YYYY-MM-DD") from None
    return pin


def load(path: pathlib.Path = PIN_FILE) -> dict[str, str]:
    return parse(path.read_text(encoding="utf-8"))


def url(pin: dict[str, str]) -> str:
    return f"https://github.com/{pin['repo']}.git"


def _git(*args: str, cwd: pathlib.Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch(pin: dict[str, str], dest: pathlib.Path) -> None:
    """Shallow-fetch exactly the pinned commit into dest and check it out (detached)."""
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        _git("init", "-q", cwd=dest)
    _git("fetch", "-q", "--depth", "1", url(pin), pin["commit"], cwd=dest)
    _git("checkout", "-q", "--detach", pin["commit"], cwd=dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=pathlib.Path, default=PIN_FILE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    v = sub.add_parser("verify")
    v.add_argument("--remote", action="store_true", help="also fetch the commit from the lab")
    f = sub.add_parser("fetch")
    f.add_argument("dest", type=pathlib.Path)
    a = ap.parse_args(argv)
    try:
        pin = load(a.file)
    except (OSError, PinError) as e:
        print(f"LAB_PIN: {e}", file=sys.stderr)
        return 1
    if a.cmd == "show":
        print(f"{pin['repo']} {pin['commit']} {pin['pinned']}")
    elif a.cmd == "verify":
        if a.remote:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    fetch(pin, pathlib.Path(tmp))
                except subprocess.CalledProcessError:
                    print(f"LAB_PIN: commit {pin['commit']} not fetchable from {pin['repo']}", file=sys.stderr)
                    return 1
        print(f"LAB_PIN ok: {pin['repo']}@{pin['commit'][:7]} ({pin['pinned']})")
    elif a.cmd == "fetch":
        fetch(pin, a.dest)
        print(a.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
