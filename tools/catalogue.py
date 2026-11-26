#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Regenerate tests/data/catalogue.json from the lab at LAB_PIN (0025 §2.6, §5.2).

The engine's `hello.catalogue` uses the shape of lab `apps/studio/public/wirescape_modules.json`,
which the lab generates from native manifests and checks for drift (ENGINE_PROTOCOL.md §7).
H-4 replaces this with the real engine's `hello` once the engine is built in CI.
After running it, also run `node tools/taper_vectors.mjs`.
"""
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import labpin  # noqa: E402

SRC = "apps/studio/public/wirescape_modules.json"


def main() -> int:
    pin = labpin.load()
    with tempfile.TemporaryDirectory() as tmp:
        labpin.fetch(pin, pathlib.Path(tmp))
        doc = json.loads((pathlib.Path(tmp) / SRC).read_text(encoding="utf-8"))
    out = {"SPDX-License-Identifier": "GPL-3.0-only", "_source": {"repo": pin["repo"], "commit": pin["commit"], "path": SRC,
                       "note": "hello.catalogue shape (ENGINE_PROTOCOL.md §7); regenerate on each LAB_PIN bump with tools/catalogue.py"},
           "modules": doc["modules"]}
    (ROOT / "tests" / "data" / "catalogue.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out['modules'])} modules from {pin['repo']}@{pin['commit'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
