# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.make_smoke_bundle import ROOT, make


class SmokeBundle(unittest.TestCase):
    def test_new_source_bundle_and_matching_gate(self):
        stock = ROOT / "examples/bundle/patches/basics-01-first-tone.json"
        original = stock.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "smoke"
            make(dest)
            cfg = json.loads((dest / "player.json").read_text())
            first = cfg["setlist"][0]
            self.assertEqual(first["program"], 0)
            self.assertEqual(first["scripts"], [{"file": "scripts/smoke_gate.py", "port": 9002}])
            patch = json.loads((dest / first["patch"]).read_text())
            self.assertFalse(any(m["module"] == "host.keyboard" for m in patch["modules"]))
            self.assertIn({"kind": "signal", "from": {"module": 101, "port": "row1"},
                           "to": {"module": 3, "port": "gate"}}, patch["connections"])
            result = subprocess.run([sys.executable, "-m", "player", "check", str(dest), "--scripts"],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("smoke_gate.py sends", result.stdout)
            self.assertEqual((dest / "patches/basics-01-first-tone.json").read_bytes(), original)
            with self.assertRaises(ValueError):
                make(dest)
        self.assertEqual(stock.read_bytes(), original)
