#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read the actual pinned sidecar hello and regenerate/check the fake catalogue.

Build wirescape-engine at LAB_PIN first. Use --check in H1 to detect drift;
use the same executable without --check to regenerate, then run
node tools/taper_vectors.mjs. No physical devices or LAN are enabled.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import labpin  # noqa: E402

SNAPSHOT = ROOT / "tests/data/catalogue.json"


def read_hello(binary: pathlib.Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([str(binary.resolve()), "--null-audio", "--settings",
                                 str(pathlib.Path(tmp) / "engine-settings.json")],
                                input="", text=True, capture_output=True, timeout=15, check=True)
    lines = result.stdout.splitlines()
    if not lines:
        raise ValueError("sidecar emitted no hello")
    hello = json.loads(lines[0])
    if hello.get("type") != "hello" or not isinstance(hello.get("catalogue", {}).get("modules"), list):
        raise ValueError("first sidecar frame is not a catalogue hello")
    return hello


def canonical(modules):
    return {m["id"]: m for m in modules}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("engine", type=pathlib.Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--observed", type=pathlib.Path, help="write actual hello catalogue as diagnostic JSON")
    args = ap.parse_args()
    pin = labpin.load()
    hello = read_hello(args.engine)
    modules = hello["catalogue"]["modules"]
    source = {"repo": pin["repo"], "commit": pin["commit"], "path": "hello.catalogue",
              "note": "actual pinned sidecar hello; regenerate on LAB_PIN bump with tools/catalogue.py"}
    out = {"SPDX-License-Identifier": "GPL-3.0-only", "_source": source, "modules": modules}
    encoded = json.dumps(out, indent=1) + "\n"
    if args.observed:
        args.observed.write_text(encoded, encoding="utf-8")
    if args.check:
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        assert snapshot["_source"]["commit"] == pin["commit"], "snapshot pin mismatch"
        expected, observed = canonical(snapshot["modules"]), canonical(modules)
        if len(observed) != len(modules) or observed != expected:
            print("Missing:", sorted(expected.keys() - observed.keys()))
            print("Unexpected:", sorted(observed.keys() - expected.keys()))
            print("Changed:", sorted(k for k in expected.keys() & observed.keys() if expected[k] != observed[k]))
            return 1
        print(f"Verified {len(modules)} modules against actual hello at {pin['commit'][:7]}")
    else:
        SNAPSHOT.write_text(encoded, encoding="utf-8")
        print(f"Regenerated {len(modules)} modules from actual hello at {pin['commit'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
