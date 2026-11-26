# SPDX-License-Identifier: GPL-3.0-only
"""State files and atomic writes (lab proposals/0025 §2.3).

`state.json` holds the bundle, the setlist index and the live values. `state.good.json` is a
copy written after each successful boot. Every write is atomic: `<file>.tmp` in the same
directory, flush, fsync, `os.replace`, then fsync the directory. A power cut or SIGKILL
therefore leaves the old file or the new one, never a torn one.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Any

FORMAT = "wirescape.player.state"
VERSION = 1


def fsync_dir(path: pathlib.Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    fsync_dir(path.parent)


def atomic_write_json(path: pathlib.Path, doc: Any) -> None:
    # Serialise first, so a document that cannot be written never touches the disk.
    data = (json.dumps(doc, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, data)


def state_doc(bundle: str, index: int | None, values: dict[int, dict[str, float]]) -> dict:
    return {"format": FORMAT, "version": VERSION, "bundle": bundle, "index": index,
            "values": {str(i): dict(v) for i, v in sorted(values.items()) if v}}


def valid(doc: Any) -> bool:
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("version") != VERSION:
        return False
    if not isinstance(doc.get("bundle"), str):
        return False
    i = doc.get("index")
    if i is not None and (not isinstance(i, int) or isinstance(i, bool) or i < 0):
        return False
    vals = doc.get("values", {})
    if not isinstance(vals, dict):
        return False
    for k, v in vals.items():
        if not k.isdigit() or not isinstance(v, dict):
            return False
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values()):
            return False
    return True


def values_of(doc: dict) -> dict[int, dict[str, float]]:
    return {int(k): dict(v) for k, v in (doc.get("values") or {}).items()}


class StateStore:
    """The state directory's `state.json` and `state.good.json`."""

    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)

    @property
    def path(self) -> pathlib.Path:
        return self.root / "state.json"

    @property
    def good_path(self) -> pathlib.Path:
        return self.root / "state.good.json"

    def _read(self, p: pathlib.Path) -> dict | None:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        return doc if valid(doc) else None

    def load(self) -> dict | None:
        """`state.json`, else `state.good.json`, else None (0025 §2.3 "Boot")."""
        return self._read(self.path) or self._read(self.good_path)

    def save(self, doc: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, doc)

    def save_good(self, doc: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.good_path, doc)
