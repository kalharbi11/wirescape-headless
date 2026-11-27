# SPDX-License-Identifier: GPL-3.0-only
"""Smoke test the independent UI example against the public fake Player API."""
import tempfile
import unittest
from pathlib import Path

import test_reference
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[2]


class MinimalUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_reference.ReferenceUI.setUpClass.__func__(cls)
        with tempfile.NamedTemporaryFile(dir=ROOT / "ui", suffix=".html", delete=False) as f:
            f.write((ROOT / "examples/ui-minimal/index.html").read_bytes())
            cls.file = Path(f.name)
        cls.addClassCleanup(cls.file.unlink)

    def test_state_switch_and_panic(self):
        page = self.browser.new_page(viewport={"width": 800, "height": 480}, has_touch=True)
        self.addCleanup(page.close)
        page.goto(self.origin + "/ui/" + self.file.name)
        status = page.get_by_role("status")
        expect(status).to_contain_text("First tone")
        page.get_by_role("button", name="Next").click()
        expect(status).to_contain_text("Random melody")
        page.get_by_role("button", name="Previous").click()
        expect(status).to_contain_text("First tone")
        with page.expect_response(lambda r: r.url.endswith("/command") and r.request.post_data_json.get("type") == "panic") as reply:
            page.get_by_role("button", name="Panic").click()
        self.assertTrue(reply.value.json()["ok"])
        expect(page.get_by_role("alert")).to_be_empty()


if __name__ == "__main__":
    unittest.main()
