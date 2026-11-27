# SPDX-License-Identifier: GPL-3.0-only
"""H-11/PG4: the Player supervises actual script children independently of audio."""
import asyncio
import json
import socket
import struct
import unittest

from player import bundle as B
from player.core import PlayerCore
from player.fake_engine import FakeEngine
from player.server import ApiServer
from tests import apiclient as api
from tests.helpers import TempBundle
from tests.test_api import V

SCRIPT = """# SPDX-License-Identifier: GPL-3.0-only
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ws
gate = ws.gate("Gate", address="/test/gate")
density = ws.knob("Density", 0, 2, 0.5)
enabled = ws.toggle("Enabled", False)
mode = ws.dropdown("Mode", ["A", "B"], "A")
number = ws.number("Number", -2, 2, 0, step=0.5)
cv = ws.cv("Value", address="/test/value", out_min=0, out_max=2)
toggle_cv = ws.cv("Toggle", address="/test/toggle")
mode_cv = ws.cv("Mode", address="/test/mode")
number_cv = ws.cv("Number", address="/test/number")
ws.start()
while True:
    gate.on()
    cv.send(density.value / 2)
    toggle_cv.send(float(enabled.value))
    mode_cv.send(float(mode.value == "B"))
    number_cv.send((number.value + 2) / 4)
    ws.sleep(.05)
"""


class PlayerScripts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))
        self.rx.setblocking(False)
        self.addCleanup(self.rx.close)
        self.tb = TempBundle()
        self.addCleanup(self.tb.cleanup)
        cfg = json.loads((self.tb.root / "player.json").read_text())
        cfg["setlist"][5]["scripts"] = [{"file": "scripts/probe.py", "port": self.rx.getsockname()[1]}]
        cfg["controls"] = [{"id": "dens", "target": {"script": {"file": "scripts/probe.py", "control": "density"}}}]
        cfg["pages"] = [{"title": "Main", "controls": ["dens"]}]
        (self.tb.root / "player.json").write_text(json.dumps(cfg))
        (self.tb.root / "scripts/probe.py").write_text(SCRIPT)
        bundle = B.load(self.tb.root)
        self.engine = FakeEngine()
        self.core = PlayerCore({bundle.name: bundle}, lambda: self.engine, fake=True)
        self.server = ApiServer(self.core, port=0)
        self.port = await self.server.start()
        self.addAsyncCleanup(self.server.close)
        self.addAsyncCleanup(self.core.close)
        await self.core.start()

    async def cmd(self, **cmd):
        V["command"].validate(cmd)
        reply = await api.command(self.port, cmd)
        V["reply"].validate(reply)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    async def state(self):
        s = await api.get_state(self.port)
        V["state"].validate(s)
        return s

    async def wait(self, predicate, seconds=6):
        end = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < end:
            s = await self.state()
            if predicate(s):
                return s
            await asyncio.sleep(.025)
        self.fail("script state condition not reached")

    async def receive(self, address, value, seconds=6):
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            packet = await asyncio.wait_for(loop.sock_recv(self.rx, 2048), end - loop.time())
            if packet.startswith(address.encode() + b"\0") and abs(struct.unpack(">f", packet[-4:])[0] - value) < 1e-5:
                return
        self.fail(f"OSC {address} {value} not received")

    async def test_pg4_restart_replays_values_and_releases_gates(self):
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["controls"]["dens"]["resolved"] and s["scripts"][0]["state"] == "running")
        await self.cmd(type="set", control="dens", value=1.5)
        await self.receive("/test/value", .75)
        await self.receive("/test/gate", 1)
        await self.cmd(type="fake.inject", what="scriptCrash")
        await self.receive("/test/gate", 0)
        await self.wait(lambda s: s["scripts"][0]["restarts"] >= 1 and s["scripts"][0]["state"] == "running")
        await self.receive("/test/value", .75)
        self.assertIs(self.core.engine, self.engine)
        self.assertEqual((await self.state())["engine"]["restarts"], 0)
        await self.cmd(type="select", index=0)
        await self.receive("/test/gate", 0)
        self.assertEqual((await self.state())["scripts"], [])
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["controls"]["dens"]["resolved"])
        await self.receive("/test/value", .75)

    async def test_explicit_script_commands(self):
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        file = "scripts/probe.py"
        await self.cmd(type="script.stop", file=file)
        await self.wait(lambda s: s["scripts"][0]["state"] == "stopped")
        await self.cmd(type="script.start", file=file)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        await self.cmd(type="script.restart", file=file)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        self.assertEqual((await self.state())["engine"]["restarts"], 0)

    async def test_typed_numeric_script_controls_and_replay(self):
        await self.cmd(type="select", index=5)
        await self.wait(lambda s: s["scripts"][0]["state"] == "running")
        file = "scripts/probe.py"
        for cid, value, expected, address in (
            ("enabled", 1, 1, "/test/toggle"),
            ("mode", 1, 1, "/test/mode"),
            ("number", 0.8, 1, "/test/number"),
        ):
            result = await self.cmd(type="set", target={"script": {"file": file, "control": cid}}, value=value)
            self.assertEqual(result["value"], expected)
            await self.receive(address, .75 if cid == "number" else 1)
        await self.cmd(type="fake.inject", what="scriptCrash")
        await self.receive("/test/gate", 0)
        await self.wait(lambda s: s["scripts"][0]["restarts"] >= 1 and s["scripts"][0]["state"] == "running")
        for address, value in (("/test/toggle", 1), ("/test/mode", 1), ("/test/number", .75)):
            await self.receive(address, value)
