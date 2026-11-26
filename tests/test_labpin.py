# SPDX-License-Identifier: GPL-3.0-only
"""H-0: LAB_PIN parsing and the committed pin (0025 §5.2)."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import labpin  # noqa: E402

GOOD = "# comment\nrepo=kalharbi11/wirescape-lab\ncommit=" + "a" * 40 + "\npinned=2026-11-26\n"


class ParseTests(unittest.TestCase):
    def test_committed_pin_is_valid(self):
        pin = labpin.load()
        self.assertEqual(pin["repo"], "kalharbi11/wirescape-lab")

    def test_good(self):
        self.assertEqual(labpin.parse(GOOD)["commit"], "a" * 40)

    def test_rejects(self):
        bad = {
            "short sha": GOOD.replace("a" * 40, "a" * 7),
            "upper sha": GOOD.replace("a" * 40, "A" * 40),
            "missing key": GOOD.replace("pinned=2026-11-26\n", ""),
            "unknown key": GOOD + "branch=main\n",
            "duplicate": GOOD + "pinned=2026-11-27\n",
            "bad date": GOOD.replace("2026-11-26", "26/11/2026"),
            "bad repo": GOOD.replace("kalharbi11/wirescape-lab", "wirescape-lab"),
            "no equals": GOOD + "oops\n",
        }
        for name, text in bad.items():
            with self.subTest(name), self.assertRaises(labpin.PinError):
                labpin.parse(text)

    def test_cli_verify_local(self):
        self.assertEqual(labpin.main(["verify"]), 0)


if __name__ == "__main__":
    unittest.main()
