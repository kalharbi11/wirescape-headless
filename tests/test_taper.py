# SPDX-License-Identifier: GPL-3.0-only
"""player.taper equals the lab's registry.ts maths at LAB_PIN for every catalogue parameter."""
import json
import unittest

from player import taper
from player.catalogue import Catalogue
from tests.helpers import ROOT


class TaperTests(unittest.TestCase):
    def test_matches_lab_vectors(self):
        vec = json.loads((ROOT / "tests/data/taper_vectors.json").read_text())
        cat = Catalogue.load()
        self.assertEqual(vec["_source"]["commit"], json.loads((ROOT / "tests/data/catalogue.json").read_text())["_source"]["commit"])
        self.assertGreater(len(vec["rows"]), 200)
        for row in vec["rows"]:
            p = cat.param(row["module"], row["param"])
            for n, want in row["n2v"]:
                self.assertAlmostEqual(taper.norm_to_value(p, n), want, places=9, msg=(row["module"], row["param"], n))
            for v, want in row["v2n"]:
                self.assertAlmostEqual(taper.value_to_norm(p, v), want, places=9, msg=(row["module"], row["param"], v))

    def test_display_uses_choice_labels(self):
        p = {"choices": [{"value": 0, "label": "Stop"}, {"value": 1, "label": "Run"}]}  # optional metadata, absent at this pin
        self.assertEqual(taper.display(p, 1), "Run")
