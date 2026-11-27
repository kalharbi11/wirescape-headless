# SPDX-License-Identifier: GPL-3.0-only
"""Boot: recover the bundles folder, load the installed bundles and pick the start state
(lab proposals/0025 §2.3 "Boot"). Boot needs no input.

The chain: `state.json` → `state.good.json` → the first installed bundle at index 0 → no
bundle, where the engine runs with no patch and the state says so. A state naming a bundle
that is no longer installed falls through to the first bundle (PlayerCore handles that).
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil

from . import bundle as B
from .install import valid_name
from .state import StateStore, fsync_dir

log = logging.getLogger("player")


def recover(bundles: pathlib.Path) -> None:
    """Delete leftover `*.tmp-*` folders; restore `<name>.old` when `<name>` is missing."""
    if not bundles.is_dir():
        return
    changed = False
    for p in sorted(bundles.iterdir()):
        if ".tmp-" in p.name:
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            changed = True
    for p in sorted(bundles.iterdir()):
        if p.name.endswith(".old") and p.is_dir():
            dest = p.with_name(p.name[:-4])
            if dest.exists():
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.rename(p, dest)
            changed = True
    if changed:
        fsync_dir(bundles)


def load_bundles(bundles: pathlib.Path) -> dict[str, B.Bundle]:
    out: dict[str, B.Bundle] = {}
    if not bundles.is_dir():
        return out
    for p in sorted(bundles.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or not valid_name(p.name):
            continue
        try:
            out[p.name] = B.load(p)
        except B.BundleError as e:
            log.error("bundle %s skipped: %s", p.name, e)
    return out


def boot(state: pathlib.Path, bundle_root: pathlib.Path | None = None) -> tuple[dict[str, B.Bundle], dict | None]:
    state = pathlib.Path(state)
    root = pathlib.Path(bundle_root) if bundle_root else state / "bundles"
    recover(root)
    return load_bundles(root), StateStore(state).load()
