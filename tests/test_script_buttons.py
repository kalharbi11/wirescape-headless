# SPDX-License-Identifier: GPL-3.0-only
import asyncio
import json
import unittest

from player import bundle as B
from player.check import check
from player.catalogue import Catalogue
from tests.helpers import TempBundle
from tests.test_player_scripts import PlayerScripts


class Buttons(PlayerScripts):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        root = self.tb.root
        path = root / "scripts/probe.py"
        body = path.read_text().replace("ws.start()", """
press = ws.button("Press")
text = ws.text("Text")
notes = ws.notes("Notes")
label = ws.label("Label")
unbounded = ws.number("Unbounded")
count = ws.cv("Count", address="/test/count")
ws.start()
""").replace("    gate.on()", "    gate.on()\n    count.send(press.press_count / 10)")
        path.write_text(body)
        cfg = self.core.bundle.config
        for cid in ("press", "text", "notes", "label", "unbounded"):
            cfg["controls"].append({"id": cid, "target": {"script": {"file": "scripts/probe.py", "control": cid}}})
        cfg["hardware"] = [
            {"source": {"midi": {"cc": 12}}, "control": "press"},
            {"source": {"midi": {"note": 36}}, "control": "press"},
        ]

    async def test_press_threshold_and_no_replay(self):
        await self.cmd(type="select", index=5)
        s = await self.wait(lambda s: s["controls"]["press"]["resolved"] and s["scripts"][0]["state"] == "running")
        c = s["controls"]["press"]
        self.assertEqual((c["min"], c["max"], c["step"], c["value"], c["norm"]), (0, 1, 1, None, None))
        for cid in ("text", "notes", "label", "unbounded"):
            self.assertEqual(s["controls"][cid]["kind"], "invalid")
        await self.cmd(type="set", control="press", value=.49)
        await self.cmd(type="set", control="press", value=.5)
        await self.receive("/test/count", .1)
        await self.cmd(type="set", control="press", norm=.5)
        await self.receive("/test/count", .2)
        script = self.core.scripts["scripts/probe.py"]
        self.assertNotIn("press", script.values)
        self.assertNotIn("script:scripts/probe.py:press", self.core.values.get(5, {}))
        await self.cmd(type="script.restart", file="scripts/probe.py")
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        await self.receive("/test/count", 0)
        await self.cmd(type="select", index=0)
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        await self.receive("/test/count", 0)

    async def test_midi_edges(self):
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        for value in (63, 64, 127, 65):
            await self.cmd(type="fake.inject", what="controller", event={"kind":"cc", "deviceId":"test",
                            "channel":1, "controller":12, "value":value})
        await self.receive("/test/count", .1)
        for value in (63, 64):
            await self.cmd(type="fake.inject", what="controller", event={"kind":"cc", "deviceId":"test",
                            "channel":1, "controller":12, "value":value})
        await self.receive("/test/count", .2)
        for kind, velocity in (("noteOff",0), ("noteOn",100), ("noteOff",0)):
            await self.cmd(type="fake.inject", what="controller", event={"kind":kind, "deviceId":"test",
                            "channel":1, "note":36, "velocity":velocity})
        await self.receive("/test/count", .3)
        # A new press after all queued events must be exactly number four.
        await self.cmd(type="set", control="press", value=1)
        await self.receive("/test/count", .4)


class Warnings(unittest.TestCase):
    def test_one_warning_per_declared_control_even_across_entries(self):
        tb = TempBundle()
        self.addCleanup(tb.cleanup)
        b = B.load(tb.root)
        controls = [{"id": k, "type": k} for k in ("text", "notes", "label", "number", "button")]
        findings = check(b, Catalogue.load(), {"scripts/generative_ws.py": {"controls": controls}})
        messages = [f.message for f in findings if f.code == "script-control-unmapped"]
        self.assertCountEqual(messages, [f"script control {k} ({k}) has no v1 Player mapping"
                                        for k in ("text", "notes", "label", "number")])
        self.assertFalse(any(f.level == "error" for f in findings))
