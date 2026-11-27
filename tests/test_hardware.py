# SPDX-License-Identifier: GPL-3.0-only
"""H-7 hardware mapping through the Player API's fake controller injection."""
import asyncio
import json

from tests.test_api import Base


class Hardware(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.core.bundle.config["hardware"] = [
            {"source": {"midi": {"device": "surface:*", "channel": 2, "cc": 11}},
             "control": "tempo", "takeover": "pickup"},
            {"source": {"osc": {"address": "/echo", "arg": 1, "min": -1, "max": 1}},
             "control": "echo"},
            {"source": {"midi": {"channel": 2, "cc": 12}}, "action": "next"},
            {"source": {"midi": {"note": 37}}, "action": "prev"},
            {"source": {"osc": {"address": "/select"}}, "action": {"select": 5}},
            {"source": {"osc": {"address": "/panic"}}, "action": "panic"},
        ]
        self.core.bundle.config["programChange"] = {"device": "surface:*", "channel": 2,
                                                   "enabled": True, "debounceMs": 150}

    async def send(self, **event):
        await self.ok(type="fake.inject", what="controller", event=event)

    async def cc(self, value, controller=11, device="surface:a", channel=2):
        await self.send(kind="cc", deviceId=device, channel=channel, controller=controller, value=value)

    async def test_pickup_and_jump(self):
        await self.ok(type="select", index=2)
        start = (await self.state())["controls"]["tempo"]["norm"]
        self.assertGreater(start, 0)
        self.assertLess(start, 1)
        await self.cc(0)
        await self.cc(max(0, int(start * 127) - 1))
        await asyncio.sleep(.1)
        self.assertEqual((await self.state())["controls"]["tempo"]["value"], 120)
        await self.cc(127, device="other")
        await self.cc(127, channel=1)
        await asyncio.sleep(.1)
        self.assertEqual((await self.state())["controls"]["tempo"]["value"], 120)
        await self.cc(127)
        await self.wait(lambda s: s["controls"]["tempo"]["norm"] == 1)
        await self.cc(0)
        await self.wait(lambda s: s["controls"]["tempo"]["norm"] == 0)
        await self.send(kind="osc", address="/echo", port=9100, args=[99, .5], matched=False)
        await self.wait(lambda s: abs(s["controls"]["echo"]["norm"] - .75) < 1e-6)

    async def test_action_edges_and_note_on(self):
        await self.ok(type="select", index=2)
        await self.cc(0, controller=12)
        await self.cc(64, controller=12)
        await self.cc(127, controller=12)
        await self.wait(lambda s: s["current"]["index"] == 3)
        await asyncio.sleep(.2)
        self.assertEqual((await self.state())["current"]["index"], 3)
        await self.send(kind="noteOff", deviceId="surface:a", channel=2, note=37, velocity=0)
        await asyncio.sleep(.2)
        self.assertEqual((await self.state())["current"]["index"], 3)
        await self.send(kind="noteOn", deviceId="surface:a", channel=2, note=37, velocity=100)
        await self.wait(lambda s: s["current"]["index"] == 2)
        await self.send(kind="osc", address="/select", port=9100, args=[], matched=False)
        await self.wait(lambda s: s["current"]["index"] == 5)
        await self.send(kind="osc", address="/panic", port=9100, args=[], matched=False)
        await asyncio.sleep(.1)
        self.assertTrue(any(c["type"] == "panic" for c in self.fake.commands))

    async def test_pc_filter_debounce_and_last_wins(self):
        before = len([c for c in self.fake.commands if c["type"] == "loadGraph"])
        await self.send(kind="pc", deviceId="other", channel=2, program=3)
        await self.send(kind="pc", deviceId="surface:a", channel=1, program=3)
        await asyncio.sleep(.2)
        self.assertEqual((await self.state())["current"]["index"], 0)
        # One ingress flush with all twenty PCs within 100ms.
        self.core.controller_events([{"kind": "pc", "deviceId": "surface:a", "channel": 2,
                                      "program": (i % 5) + 1, "t": 1000+i*4000} for i in range(20)])
        await self.wait(lambda s: s["current"]["index"] == 5)
        after = len([c for c in self.fake.commands if c["type"] == "loadGraph"])
        self.assertLessEqual(after-before, 2)
        await self.send(kind="pc", deviceId="surface:a", channel=2, program=99)
        await self.wait(lambda s: any("Program Change 99" in w for w in s["warnings"]))
        self.core.bundle.config["programChange"]["enabled"] = False
        await self.send(kind="pc", deviceId="surface:a", channel=2, program=1)
        await asyncio.sleep(.2)
        self.assertEqual((await self.state())["current"]["index"], 5)
