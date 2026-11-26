# SPDX-License-Identifier: GPL-3.0-only
"""`python -m player check BUNDLE` (lab proposals/0025 §2.7 "Bundle check", 0024 §6.5).

Exit status is non-zero only when there is an error, like lab OB-h6. Every row below has
its own test in tests/test_check.py. Row codes are stable; tools may match on them.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Iterable

from . import bundle as B
from .catalogue import Catalogue, SNAPSHOT

ERROR, WARNING, INFO = "error", "warning", "info"


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    where: str
    message: str


def check(b: B.Bundle, catalogue: Catalogue | None, declarations: dict[str, dict] | None = None) -> list[Finding]:
    """All findings for a loaded bundle.

    `declarations` maps a script path (as in player.json) to its `--print-config` document.
    Scripts without one are not checked for OSC In rows (the runner arrives with H-10).
    """
    out: list[Finding] = []
    add = lambda lvl, code, where, msg: out.append(Finding(lvl, code, where, msg))  # noqa: E731
    for p in b.problems:
        add(ERROR, "schema", p.where, p.message)
    for p in b.warnings:
        add(WARNING, "unknown-key", p.where, p.message)

    patches: dict[int, dict] = {}
    for e in b.entries:
        if not e.patch:
            continue
        if not b.patch_path(e).is_file():
            add(ERROR, "missing-patch", f"setlist[{e.index}].patch", f"{e.patch} does not exist")
            continue
        try:
            patches[e.index] = b.load_patch(e)
        except (OSError, ValueError) as ex:
            add(ERROR, "bad-patch", f"setlist[{e.index}].patch", f"{e.patch}: {ex}")
        for k, s in enumerate(e.scripts):
            if isinstance(s.get("file"), str) and B._safe_rel(s["file"]) and not (b.root / s["file"]).is_file():
                add(ERROR, "missing-script", f"setlist[{e.index}].scripts[{k}].file", f"{s['file']} does not exist")

    # Script targets name a file; it must exist too.
    for where, c in _all_controls(b):
        t = c.get("target")
        if B.target_form(t) == "script" and not (b.root / t["script"]["file"]).is_file():
            add(ERROR, "missing-script", f"{where}.target", f"{t['script']['file']} does not exist")

    programs: dict[int, int] = {}
    for e in b.entries:
        if e.program is None:
            continue
        if e.program in programs:
            add(ERROR, "duplicate-program", f"setlist[{e.index}].program",
                f"program {e.program} is already used by setlist[{programs[e.program]}]")
        else:
            programs[e.program] = e.index

    # Entry targets against their own patch.
    for e in b.entries:
        patch = patches.get(e.index)
        if patch is None:
            continue
        owned = B.mapping_owned(patch)
        for i, c in enumerate(e.controls):
            where = f"setlist[{e.index}].controls[{i}]"
            t = c.get("target")
            form = B.target_form(t)
            if form == "param":
                v = t["param"]
                m = B.find_module(patch, v["module"])
                if m is None:
                    add(ERROR, "missing-target", f"{where}.target", f"module {v['module']} is not in {e.patch}")
                elif catalogue is not None and catalogue.param(m["module"], v["param"]) is None:
                    add(ERROR, "missing-target", f"{where}.target",
                        f"module {v['module']} ({m['module']}) has no parameter {v['param']!r}")
                elif (v["module"], v["param"]) in owned:
                    add(WARNING, "mapping-owned", f"{where}.target",
                        f"{m['module']} {v['module']} · {v['param']} is driven by an in-patch mapping")
            elif form == "modAmount":
                v = t["modAmount"]
                cable = B.find_mod_cable(patch, v["from"], v["to"])
                if cable is None:
                    add(ERROR, "missing-target", f"{where}.target",
                        f"no modulation cable {v['from']['module']}:{v['from']['port']} > "
                        f"{v['to']['module']}:{v['to']['param']} in {e.patch}")
                elif B.is_mapping_cable(patch, cable):
                    add(ERROR, "mapping-cable", f"{where}.target",
                        "a modAmount target may not be a mapping cable (mapping cables stay Studio-only)")

    # Macro targets: warn when an address resolves in no patch (0024 §6.5).
    for where, c in _all_controls(b):
        t = c.get("target")
        if B.target_form(t) == "macro":
            v = t["macro"]
            if not any(B.macro_module(p, v["page"]) for p in patches.values()):
                add(WARNING, "macro-unresolved", f"{where}.target",
                    f"macro page {v['page']} knob {v['knob']} resolves in no patch of this bundle")

    # Hardware CCs that a patch also maps, and the latency hint.
    controls = _controls_by_id(b)
    for i, h in enumerate(b.config.get("hardware", []) if isinstance(b.config.get("hardware"), list) else []):
        key = B.source_key(h.get("source")) if isinstance(h, dict) else None
        if not key or key[0] != "midi" or key[3] != "cc":
            continue
        _, _dev, ch, _, num = key
        for idx, p in patches.items():
            if _patch_maps_cc(p, ch, num):
                add(WARNING, "cc-also-mapped", f"hardware[{i}].source",
                    f"CC {num} is also mapped inside {b.entries[idx].patch}")
                break
        for entry_index, c in controls.get(h.get("control"), []):
            t = c.get("target")
            if B.target_form(t) != "param" or catalogue is None:
                continue
            p = patches.get(entry_index)
            m = B.find_module(p, t["param"]["module"]) if p else None
            meta = catalogue.param(m["module"], t["param"]["param"]) if m else None
            if meta and meta.get("modulatable"):
                add(INFO, "in-patch-faster", f"hardware[{i}]",
                    f"{h['control']}: an in-patch mapping has lower latency (0025 §2.8)")

    # A patch OSC In on the control port.
    osc = b.config.get("osc") if isinstance(b.config.get("osc"), dict) else {}
    cport = osc.get("controlPort", 0)
    if cport:
        for idx, p in patches.items():
            for m in p["modules"]:
                if m.get("module") == "osc.in" and _osc_in_port(m) == cport:
                    add(ERROR, "control-port-clash", f"setlist[{idx}].patch",
                        f"{b.entries[idx].patch} module {m.get('id')} listens on osc.controlPort {cport}")

    # Script outputs with no matching OSC In row in the entries that run them (0025 §4.4).
    for e in b.entries:
        p = patches.get(e.index)
        if p is None:
            continue
        rows = {r.get("pattern") for m in p["modules"] if m.get("module") == "osc.in"
                for r in ((m.get("config") or {}).get("rows") or []) if r.get("enabled", True)}
        for s in e.scripts:
            decl = (declarations or {}).get(s.get("file"))
            for addr in _declared_addresses(decl):
                if addr not in rows:
                    add(WARNING, "script-row-missing", f"setlist[{e.index}].scripts",
                        f"{s['file']} sends {addr} but {e.patch} has no enabled OSC In row for it")
    return out


def _all_controls(b: B.Bundle) -> Iterable[tuple[str, dict]]:
    for i, c in enumerate(b.global_controls if isinstance(b.global_controls, list) else []):
        if isinstance(c, dict):
            yield f"controls[{i}]", c
    for e in b.entries:
        for i, c in enumerate(e.controls):
            yield f"setlist[{e.index}].controls[{i}]", c


def _controls_by_id(b: B.Bundle) -> dict[str, list[tuple[int | None, dict]]]:
    out: dict[str, list] = {}
    for c in b.global_controls if isinstance(b.global_controls, list) else []:
        if isinstance(c, dict):
            out.setdefault(c.get("id"), []).append((None, c))
    for e in b.entries:
        for c in e.controls:
            out.setdefault(c.get("id"), []).append((e.index, c))
    return out


def _patch_maps_cc(patch: dict, channel, controller: int) -> bool:
    for m in patch["modules"]:
        if m.get("module") != "midi.cc_to_cv":
            continue
        rows = (m.get("config") or {}).get("rows")
        if rows is None:  # module default: CC1..CC8, Omni
            rows = [{"channel": 0, "controller": n} for n in range(1, 9)]
        for r in rows:
            rch = r.get("channel", 0)
            if r.get("controller") == controller and (rch == 0 or channel == "any" or rch == channel):
                return True
    return False


def _osc_in_port(module: dict) -> int:
    cfg = module.get("config") or {}
    return cfg.get("port", 9000)


def _declared_addresses(decl: dict | None) -> list[str]:
    if not decl:
        return []
    out = []
    for o in decl.get("outputs", []):
        if "address" in o:
            out.append(o["address"])
        out.extend((o.get("addresses") or {}).values())
    return out


def print_config(script: pathlib.Path, timeout: float = 5.0) -> dict | None:
    """Run `python -I script --print-config` (0025 §4.3); None if it fails or times out."""
    try:
        r = subprocess.run([sys.executable, "-I", str(script), "--print-config"], cwd=script.parent,
                           capture_output=True, text=True, timeout=timeout)
        doc = json.loads(r.stdout) if r.returncode == 0 else None
        return doc if isinstance(doc, dict) and doc.get("format") == "wirescape.script" else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def run_lab_check(lab: pathlib.Path, patches: pathlib.Path) -> int | None:
    """Lab `tools/patch_library.py check` on patches/ (0025 §2.7), when the lab has it."""
    tool = lab / "tools" / "patch_library.py"
    if not tool.is_file():
        return None
    return subprocess.run([sys.executable, str(tool), "check", str(patches)]).returncode


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m player check", description="Check a Player bundle.")
    ap.add_argument("bundle", type=pathlib.Path)
    ap.add_argument("--lab", type=pathlib.Path, help="lab checkout: also run tools/patch_library.py check")
    ap.add_argument("--catalogue", type=pathlib.Path, help="catalogue JSON (default: the LAB_PIN snapshot)")
    ap.add_argument("--scripts", action="store_true",
                    help="run each entry script with --print-config (scripts are trusted code)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        b = B.load(a.bundle)
    except B.BundleError as e:
        print(f"error  bundle  {a.bundle}: {e}", file=sys.stderr)
        return 1
    cat = None
    cat_path = a.catalogue or SNAPSHOT
    if cat_path.is_file():
        cat = Catalogue.load(cat_path)
    decls = {}
    if a.scripts:
        for e in b.entries:
            for s in e.scripts:
                f = b.root / s.get("file", "")
                if f.is_file() and s["file"] not in decls:
                    d = print_config(f)
                    if d:
                        decls[s["file"]] = d
    findings = check(b, cat, decls)
    if cat is None:
        findings.append(Finding(WARNING, "no-catalogue", "catalogue", "no catalogue; parameter IDs were not checked"))
    lab_rc = run_lab_check(a.lab, b.root / "patches") if a.lab else None
    if a.lab and lab_rc is None:
        findings.append(Finding(INFO, "lab-check-unavailable", "--lab", "this lab has no tools/patch_library.py"))
    if a.json:
        print(json.dumps({"bundle": str(b.root), "findings": [asdict(f) for f in findings]}, indent=1))
    else:
        for f in findings:
            print(f"{f.level:<7} {f.code:<20} {f.where}: {f.message}")
        n = {lvl: sum(f.level == lvl for f in findings) for lvl in (ERROR, WARNING, INFO)}
        print(f"{b.root}: {n[ERROR]} errors, {n[WARNING]} warnings, {n[INFO]} info")
    failed = any(f.level == ERROR for f in findings) or (lab_rc not in (None, 0))
    return 1 if failed else 0
