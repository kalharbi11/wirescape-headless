# SPDX-License-Identifier: GPL-3.0-only
"""Bundles and `player.json` v1 (lab proposals/0025 §2.7).

A bundle is a folder with `patches/`, an optional `player.json`, `scripts/` and `presets/`.
This module loads it, validates `player.json` structurally (standard library only) and
resolves control targets against a patch. The rows that need the patches and the catalogue
live in `player/check.py`.
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

FORMAT = "wirescape.player"
VERSION = 1
CONTROL_ID = re.compile(r"^[a-z0-9_-]{1,32}$")
# 0024 §3.2: modulation cables from these module types are mapping cables (Studio-only).
# If the lab marks mapping sources in the catalogue, this constant gives way to that marker.
MAPPING_SOURCES = frozenset({"essentials.macro", "midi.cc_to_cv", "osc.in"})
MACRO_MODULE = "essentials.macro"
TARGET_FORMS = ("macro", "param", "modAmount", "script")
PATCH_SPECIFIC = frozenset({"param", "modAmount"})
ACTIONS = ("next", "prev", "panic")


class BundleError(ValueError):
    """The bundle cannot be read at all (not a folder, unreadable player.json)."""


@dataclass
class Problem:
    """One structural problem in player.json: always an error."""
    where: str
    message: str


@dataclass
class Entry:
    index: int
    patch: str
    title: str
    program: int | None
    recall: str
    controls: list[dict]
    pages: list[dict]
    scripts: list[dict]


@dataclass
class Bundle:
    root: pathlib.Path
    name: str
    title: str
    config: dict
    has_player_json: bool
    entries: list[Entry] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)

    @property
    def global_controls(self) -> list[dict]:
        return self.config.get("controls", [])

    @property
    def global_pages(self) -> list[dict]:
        return self.config.get("pages", [])

    def patch_path(self, entry: Entry) -> pathlib.Path:
        return self.root / entry.patch

    def load_patch(self, entry: Entry) -> dict:
        """Read an entry's patch document. Raises OSError or ValueError."""
        with open(self.patch_path(entry), encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict) or doc.get("format") != "wirescape.native.patch":
            raise ValueError("not a wirescape.native.patch document")
        if not isinstance(doc.get("modules"), list) or not isinstance(doc.get("connections"), list):
            raise ValueError("patch has no modules or connections list")
        return doc

    def program_map(self) -> dict[int, int]:
        """Program Change n -> entry index (0025 §2.7 "Program Change")."""
        if any(e.program is not None for e in self.entries):
            return {e.program: e.index for e in self.entries if e.program is not None}
        return {e.index: e.index for e in self.entries if e.index < 128}


# --------------------------------------------------------------------------- loading


def load(root: str | pathlib.Path) -> Bundle:
    root = pathlib.Path(root)
    if not root.is_dir():
        raise BundleError(f"{root} is not a folder")
    pj = root / "player.json"
    if pj.exists():
        try:
            config = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise BundleError(f"player.json is not readable JSON: {e}") from None
        b = Bundle(root, root.name, "", config if isinstance(config, dict) else {}, True)
        if not isinstance(config, dict):
            b.problems.append(Problem("player.json", "must be a JSON object"))
            return b
        _validate(b)
    else:
        # 0025 §2.7: a bundle with no player.json plays its patches/ in name order.
        patches = sorted(p.relative_to(root).as_posix() for p in (root / "patches").glob("*.json"))
        config = {"format": FORMAT, "version": VERSION, "setlist": [{"patch": p} for p in patches]}
        b = Bundle(root, root.name, "", config, False)
        _validate(b)
    b.title = b.config.get("title") or b.name
    return b


# --------------------------------------------------------------------------- validation


def _validate(b: Bundle) -> None:
    c = b.config
    err = lambda where, msg: b.problems.append(Problem(where, msg))  # noqa: E731
    _known(b, c, "player.json", {"SPDX-License-Identifier", "format", "version", "title", "setlist", "controls", "pages",
                                 "hardware", "programChange", "osc"})
    if c.get("format") != FORMAT:
        err("format", f'must be "{FORMAT}"')
    if c.get("version") != VERSION:
        err("version", f"must be {VERSION}")
    if "title" in c and not isinstance(c["title"], str):
        err("title", "must be a string")
    setlist = c.get("setlist")
    if not isinstance(setlist, list):
        err("setlist", "must be a list")
        setlist = []

    global_ids = _controls(b, c.get("controls", []), "controls", global_scope=True)
    _pages(b, c.get("pages", []), "pages", global_ids)

    for i, raw in enumerate(setlist):
        where = f"setlist[{i}]"
        if not isinstance(raw, dict):
            err(where, "must be an object")
            continue
        _known(b, raw, where, {"patch", "title", "program", "recall", "controls", "pages", "scripts"})
        patch = raw.get("patch")
        if not isinstance(patch, str) or not _safe_rel(patch):
            err(f"{where}.patch", "must be a relative path inside the bundle")
            patch = ""
        program = raw.get("program")
        if program is not None and not _int_in(program, 0, 127):
            err(f"{where}.program", "must be an integer 0-127")
            program = None
        recall = raw.get("recall", "last")
        if recall not in ("last", "patch"):
            err(f"{where}.recall", 'must be "last" or "patch"')
        ids = _controls(b, raw.get("controls", []), f"{where}.controls", global_scope=False)
        dup = ids & global_ids
        for d in sorted(dup):
            err(f"{where}.controls", f"control id {d!r} is already a global control")
        _pages(b, raw.get("pages", []), f"{where}.pages", ids | global_ids)
        scripts = raw.get("scripts", [])
        if not isinstance(scripts, list):
            err(f"{where}.scripts", "must be a list")
            scripts = []
        for k, s in enumerate(scripts):
            sw = f"{where}.scripts[{k}]"
            if not isinstance(s, dict) or not isinstance(s.get("file"), str):
                err(sw, "must be an object with a file")
                continue
            _known(b, s, sw, {"file", "port"})
            if not _safe_rel(s["file"]) or not s["file"].startswith("scripts/"):
                err(f"{sw}.file", "must be a path inside the bundle's scripts/")
            if "port" in s and not _int_in(s["port"], 1024, 65535):
                err(f"{sw}.port", "must be an integer 1024-65535")
        title = raw.get("title")
        if title is not None and not isinstance(title, str):
            err(f"{where}.title", "must be a string")
        b.entries.append(Entry(i, patch, title or pathlib.PurePosixPath(patch).stem, program,
                               recall if recall in ("last", "patch") else "last",
                               [x for x in raw.get("controls", []) if isinstance(x, dict)]
                               if isinstance(raw.get("controls", []), list) else [],
                               [x for x in raw.get("pages", []) if isinstance(x, dict)]
                               if isinstance(raw.get("pages", []), list) else [],
                               [s for s in scripts if isinstance(s, dict)]))

    all_ids = set(global_ids)
    for e in b.entries:
        all_ids |= {x.get("id") for x in e.controls}
    _hardware(b, c.get("hardware", []), all_ids, len(b.entries))
    _program_change(b, c.get("programChange"))
    osc = c.get("osc")
    if osc is not None:
        if not isinstance(osc, dict):
            err("osc", "must be an object")
        else:
            _known(b, osc, "osc", {"controlPort"})
            port = osc.get("controlPort", 0)
            if not (port == 0 or _int_in(port, 1024, 65535)):
                err("osc.controlPort", "must be 0 or an integer 1024-65535")


def _controls(b: Bundle, controls: Any, where: str, global_scope: bool) -> set[str]:
    ids: set[str] = set()
    if not isinstance(controls, list):
        b.problems.append(Problem(where, "must be a list"))
        return ids
    for i, c in enumerate(controls):
        w = f"{where}[{i}]"
        if not isinstance(c, dict):
            b.problems.append(Problem(w, "must be an object"))
            continue
        _known(b, c, w, {"id", "label", "target"})
        cid = c.get("id")
        if not isinstance(cid, str) or not CONTROL_ID.match(cid):
            b.problems.append(Problem(f"{w}.id", "must match [a-z0-9_-]{1,32}"))
        elif cid in ids:
            b.problems.append(Problem(f"{w}.id", f"duplicate control id {cid!r}"))
        else:
            ids.add(cid)
        if "label" in c and not isinstance(c["label"], str):
            b.problems.append(Problem(f"{w}.label", "must be a string"))
        form = target_form(c.get("target"))
        if form is None:
            b.problems.append(Problem(f"{w}.target", "must be exactly one of " + ", ".join(TARGET_FORMS)
                                      + " with valid fields"))
        elif global_scope and form in PATCH_SPECIFIC:
            # 0025 §2.7 check error: a global control with a patch-specific target.
            b.problems.append(Problem(f"{w}.target",
                                      f"a global control may not use a patch-specific {form!r} target"))
    return ids


def target_form(t: Any) -> str | None:
    """The target's form name if it is structurally valid, else None."""
    if not isinstance(t, dict) or len(t) != 1:
        return None
    (form, v), = t.items()
    if not isinstance(v, dict):
        return None
    if form == "macro":
        ok = set(v) == {"page", "knob"} and _int_in(v["page"], 1, 64) and _int_in(v["knob"], 1, 8)
    elif form == "param":
        ok = set(v) == {"module", "param"} and _module_id(v["module"]) and _name(v["param"])
    elif form == "modAmount":
        f, to = v.get("from"), v.get("to")
        ok = (set(v) == {"from", "to"} and isinstance(f, dict) and isinstance(to, dict)
              and set(f) == {"module", "port"} and _module_id(f["module"]) and _name(f["port"])
              and set(to) == {"module", "param"} and _module_id(to["module"]) and _name(to["param"]))
    elif form == "script":
        ok = (set(v) == {"file", "control"} and isinstance(v["file"], str) and _safe_rel(v["file"])
              and v["file"].startswith("scripts/") and _name(v["control"]))
    else:
        ok = False
    return form if ok else None


def _pages(b: Bundle, pages: Any, where: str, ids: set[str]) -> None:
    if not isinstance(pages, list):
        b.problems.append(Problem(where, "must be a list"))
        return
    for i, p in enumerate(pages):
        w = f"{where}[{i}]"
        if not isinstance(p, dict) or not isinstance(p.get("controls", []), list):
            b.problems.append(Problem(w, "must be an object with a controls list"))
            continue
        _known(b, p, w, {"title", "controls"})
        if "title" in p and not isinstance(p["title"], str):
            b.problems.append(Problem(f"{w}.title", "must be a string"))
        for cid in p.get("controls", []):
            if cid not in ids:
                b.problems.append(Problem(f"{w}.controls", f"unknown control id {cid!r}"))


def source_key(src: dict) -> tuple | None:
    """A hashable identity for a hardware source, or None if it is malformed."""
    if not isinstance(src, dict) or len(src) != 1:
        return None
    (kind, v), = src.items()
    if not isinstance(v, dict):
        return None
    if kind == "midi":
        if set(v) - {"device", "channel", "cc", "note"}:
            return None
        dev = v.get("device", "*")
        ch = v.get("channel", "any")
        if not isinstance(dev, str) or not (ch == "any" or _int_in(ch, 1, 16)):
            return None
        has_cc, has_note = "cc" in v, "note" in v
        if has_cc == has_note:
            return None
        num = v["cc"] if has_cc else v["note"]
        if not _int_in(num, 0, 127):
            return None
        return ("midi", dev, ch, "cc" if has_cc else "note", num)
    if kind == "osc":
        if set(v) - {"address", "arg", "min", "max"}:
            return None
        addr = v.get("address")
        arg = v.get("arg", 0)
        if not isinstance(addr, str) or not addr.startswith("/") or len(addr.encode()) > 128:
            return None
        if not _int_in(arg, 0, 3):
            return None
        for k in ("min", "max"):
            if k in v and not _number(v[k]):
                return None
        return ("osc", addr, arg)
    return None


def _hardware(b: Bundle, hw: Any, ids: set[str], n_entries: int) -> None:
    if not isinstance(hw, list):
        b.problems.append(Problem("hardware", "must be a list"))
        return
    seen: dict[tuple, int] = {}
    for i, h in enumerate(hw):
        w = f"hardware[{i}]"
        if not isinstance(h, dict):
            b.problems.append(Problem(w, "must be an object"))
            continue
        _known(b, h, w, {"source", "control", "action", "takeover"})
        key = source_key(h.get("source"))
        if key is None:
            b.problems.append(Problem(f"{w}.source", "must be one midi (device, channel, cc|note) "
                                                     "or osc (address, arg, min, max) source"))
        elif key in seen:
            # 0025 §2.7 check error: the same hardware source bound twice.
            b.problems.append(Problem(f"{w}.source", f"the same source is already bound in hardware[{seen[key]}]"))
        else:
            seen[key] = i
        has_c, has_a = "control" in h, "action" in h
        if has_c == has_a:
            b.problems.append(Problem(w, "must name exactly one of control or action"))
        elif has_c and h["control"] not in ids:
            b.problems.append(Problem(f"{w}.control", f"unknown control id {h['control']!r}"))
        elif has_a:
            a = h["action"]
            if not (a in ACTIONS or (isinstance(a, dict) and set(a) == {"select"}
                                     and _int_in(a["select"], 0, max(0, n_entries - 1)))):
                b.problems.append(Problem(f"{w}.action", 'must be "next", "prev", "panic" or {"select": n}'))
        if h.get("takeover", "jump") not in ("jump", "pickup"):
            b.problems.append(Problem(f"{w}.takeover", 'must be "jump" or "pickup"'))


def _program_change(b: Bundle, pc: Any) -> None:
    if pc is None:
        return
    if not isinstance(pc, dict):
        b.problems.append(Problem("programChange", "must be an object"))
        return
    _known(b, pc, "programChange", {"enabled", "device", "channel", "debounceMs"})
    if not isinstance(pc.get("enabled", True), bool):
        b.problems.append(Problem("programChange.enabled", "must be a boolean"))
    if not isinstance(pc.get("device", "*"), str):
        b.problems.append(Problem("programChange.device", "must be a string glob"))
    ch = pc.get("channel", "any")
    if not (ch == "any" or _int_in(ch, 1, 16)):
        b.problems.append(Problem("programChange.channel", 'must be 1-16 or "any"'))
    if not _int_in(pc.get("debounceMs", 150), 0, 1000):
        b.problems.append(Problem("programChange.debounceMs", "must be an integer 0-1000"))


def _known(b: Bundle, obj: dict, where: str, keys: set[str]) -> None:
    for k in obj:
        if k not in keys:
            b.warnings.append(Problem(f"{where}.{k}", "unknown key (ignored)"))


def _int_in(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _module_id(v: Any) -> bool:
    return _int_in(v, 1, 4294967295)


def _name(v: Any) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 256


def _safe_rel(p: str) -> bool:
    pp = pathlib.PurePosixPath(p)
    return bool(p) and not pp.is_absolute() and ".." not in pp.parts and "\\" not in p


# --------------------------------------------------------------------------- resolution


def macro_module(patch: dict, page: int) -> dict | None:
    """The page-th essentials.macro module in the patch's modules array (0024 §6)."""
    macros = [m for m in patch.get("modules", []) if m.get("module") == MACRO_MODULE]
    return macros[page - 1] if 0 < page <= len(macros) else None


def find_module(patch: dict, module_id: int) -> dict | None:
    for m in patch.get("modules", []):
        if m.get("id") == module_id:
            return m
    return None


def find_mod_cable(patch: dict, frm: dict, to: dict) -> dict | None:
    for c in patch.get("connections", []):
        if (c.get("kind") == "modulation" and c.get("from") == {"module": frm["module"], "port": frm["port"]}
                and c.get("to") == {"module": to["module"], "port": to["param"]}):
            return c
    return None


def is_mapping_cable(patch: dict, cable: dict) -> bool:
    src = find_module(patch, cable["from"]["module"])
    return bool(src) and src.get("module") in MAPPING_SOURCES


def mapping_owned(patch: dict) -> set[tuple[int, str]]:
    """(module, param) pairs that a mapping cable drives."""
    owned = set()
    for c in patch.get("connections", []):
        if c.get("kind") == "modulation" and is_mapping_cable(patch, c):
            owned.add((c["to"]["module"], c["to"]["port"]))
    return owned


def resolve_param(patch: dict, target: dict) -> tuple[int, str] | None:
    """(module id, param id) for a macro or param target in this patch, else None.

    Existence of the parameter id is checked against the catalogue by the caller.
    """
    (form, v), = target.items()
    if form == "macro":
        m = macro_module(patch, v["page"])
        return (m["id"], f"knob{v['knob']}") if m else None
    if form == "param":
        return (v["module"], v["param"]) if find_module(patch, v["module"]) else None
    return None


def glob_match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value, pattern)
