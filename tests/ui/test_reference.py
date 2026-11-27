# SPDX-License-Identifier: GPL-3.0-only
"""Browser contract tests; run explicitly with python -m unittest tests.ui.test_reference."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


class ReferenceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "player", "fake", "--port", "0"],
            cwd=ROOT, stdout=subprocess.PIPE, text=True,
        )
        cls.addClassCleanup(cls.proc.stdout.close)
        cls.addClassCleanup(cls.proc.wait, 10)
        cls.addClassCleanup(cls.proc.terminate)
        cls.origin = cls.proc.stdout.readline().split()[2].split("/api/")[0]
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 800, "height": 480}, has_touch=True)
        self.addCleanup(self.page.close)
        self.page.goto(self.origin + "/ui/")
        expect(self.page.get_by_role("status")).to_contain_text("Connected")

    def command(self, command):
        result = self.page.request.post(self.origin + "/api/v1/command", data=command).json()
        self.assertTrue(result["ok"], result)
        return result

    def menu(self, name):
        self.page.get_by_role("button", name=name, exact=True).click()
        expect(self.page.get_by_role("heading", name=name, exact=True)).to_be_visible()

    def test_navigation_and_touch_targets(self):
        for name in ("Play", "Setlist", "Parameters", "Scripts", "Devices", "Status", "System"):
            self.menu(name)
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= 800"))
        for b in self.page.get_by_role("button").all():
            if b.is_visible():
                box = b.bounding_box()
                self.assertGreaterEqual(box["height"], 48)
                self.assertGreaterEqual(box["width"], 48)

    def test_switch_and_parameter_write(self):
        self.menu("Setlist")
        self.page.get_by_role("button", name="Clocked groove").click()
        expect(self.page.get_by_role("status")).to_contain_text("Clocked groove")
        self.menu("Play")
        tempo = self.page.get_by_role("slider", name="Tempo")
        expect(tempo).to_be_enabled()
        with self.page.expect_response(lambda r: r.url.endswith("/command") and r.request.post_data_json.get("type") == "set") as response:
            tempo.press("ArrowRight")
        self.assertTrue(response.value.json()["ok"])
        self.menu("Parameters")
        expect(self.page.get_by_role("slider").first).to_be_visible()
        self.menu("Setlist")
        self.page.get_by_role("button", name="Next", exact=True).click()
        expect(self.page.get_by_role("status")).to_contain_text("OSC out")

    def test_devices_system_and_recovery(self):
        self.menu("Devices")
        self.page.get_by_label("Sample rate").select_option("48000")
        self.page.get_by_label("Buffer frames").select_option("256")
        self.menu("System")
        expect(self.page.get_by_role("button", name="Restart engine")).to_be_enabled()
        self.menu("Status")
        expect(self.page.get_by_text("Bundle check", exact=True)).to_be_visible()
        before = self.page.request.get(self.origin + "/api/v1/state").json()["engine"]["restarts"]
        self.command({"type": "fake.inject", "what": "engineCrash"})
        expect(self.page.locator("pre[data-detail=Engine]")).to_contain_text(f'"restarts": {before + 1}', timeout=10000)
        expect(self.page.get_by_role("status")).to_contain_text("running", timeout=10000)

    def test_script_restart_is_available(self):
        self.command({"type": "select", "index": 5})
        expect(self.page.get_by_role("status")).to_contain_text("Black ice choir")
        self.menu("Scripts")
        with self.page.expect_response(lambda r: r.url.endswith("/command") and r.request.post_data_json.get("type") == "script.restart") as reply:
            self.page.get_by_role("button", name="Restart script").click()
        self.assertTrue(reply.value.json()["ok"])
        expect(self.page.locator("#error")).to_be_empty()


if __name__ == "__main__":
    unittest.main()
