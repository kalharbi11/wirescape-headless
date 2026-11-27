# SPDX-License-Identifier: GPL-3.0-only
"""`python -m player install SRC --state DIR` (lab proposals/0025 §2.3).

The steps, in order:
1. copy SRC to `bundles/<name>.tmp-<n>/` and fsync every file and folder;
2. run the bundle check (errors refuse, and the temp copy is removed);
3. rename an existing `<name>` to `<name>.old`;
4. rename the new copy to `<name>` and fsync `bundles/`;
5. delete `<name>.old`.
A power cut or kill at any point leaves the old or the new bundle, plus at most a temp or
`.old` folder that the next boot resolves (player/boot.py `recover`). SRC is only read.
"""
from __future__ import annotations

import argparse
import itertools
import os
import pathlib
import re
import shutil
import sys

from . import bundle as B
from .catalogue import SNAPSHOT, Catalogue
from .check import ERROR, check
from .state import fsync_dir

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STEPS = ("copied", "checked", "old-renamed", "new-renamed", "done")


class InstallError(Exception):
    pass


def _step(name: str) -> None:
    """A hook between steps; tests replace it to kill the process at a step."""


def _fsync_tree(root: pathlib.Path) -> None:
    for d, _, files in os.walk(root):
        for f in files:
            fd = os.open(os.path.join(d, f), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        fsync_dir(pathlib.Path(d))


def valid_name(name: str) -> bool:
    return bool(NAME.match(name)) and ".tmp-" not in name and not name.endswith(".old")


def install(src: pathlib.Path, state: pathlib.Path, catalogue: Catalogue | None = None) -> str:
    src, state = pathlib.Path(src), pathlib.Path(state)
    if not src.is_dir() or not (src / "patches").is_dir():
        raise InstallError(f"{src} is not a bundle folder (it needs patches/)")
    name = src.resolve().name
    if not valid_name(name):
        raise InstallError(f"bundle name {name!r} must match {NAME.pattern} and not end in .old or hold .tmp-")
    bundles = state / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    tmp = next(bundles / f"{name}.tmp-{n}" for n in itertools.count(os.getpid())
               if not (bundles / f"{name}.tmp-{n}").exists())
    try:
        shutil.copytree(src, tmp, symlinks=False)
        _fsync_tree(tmp)
        fsync_dir(bundles)
        _step("copied")
        try:
            b = B.load(tmp)
        except B.BundleError as e:
            raise InstallError(f"bundle check: {e}") from None
        if catalogue is None and SNAPSHOT.exists():
            catalogue = Catalogue.load()
        errors = [f for f in check(b, catalogue) if f.level == ERROR]
        if errors:
            raise InstallError("bundle check refused the install:\n" +
                               "\n".join(f"  error {f.code} {f.where}: {f.message}" for f in errors))
        _step("checked")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    dest, old = bundles / name, bundles / f"{name}.old"
    if old.exists():
        if dest.exists():
            shutil.rmtree(old)
        else:
            os.rename(old, dest)  # an earlier install died between its renames: keep that copy
    if dest.exists():
        os.rename(dest, old)
        fsync_dir(bundles)
    _step("old-renamed")
    os.rename(tmp, dest)
    fsync_dir(bundles)
    _step("new-renamed")
    shutil.rmtree(old, ignore_errors=True)
    _step("done")
    return name


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m player install", description="Install a bundle atomically (0025 §2.3).")
    ap.add_argument("src", type=pathlib.Path)
    ap.add_argument("--state", type=pathlib.Path, required=True)
    a = ap.parse_args(argv)
    try:
        name = install(a.src, a.state)
    except InstallError as e:
        print(f"install: {e}", file=sys.stderr)
        return 1
    print(f"installed {name} into {a.state / 'bundles' / name}")
    return 0
