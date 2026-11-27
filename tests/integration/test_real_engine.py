# SPDX-License-Identifier: GPL-3.0-only
"""H-4 real-engine acceptance, explicitly invoked by H1/H2, never by H0."""
import asyncio
import os
import pathlib
import tempfile
import unittest

from player import bundle as B
from player.core import PlayerCore
from player.engine_proc import EngineProcess
from player.server import ApiServer
from player.state import StateStore
from tests import apiclient as api
from tests.helpers import TempBundle
from tests.test_api import V


class RealEngine(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        binary = pathlib.Path(os.environ["WIRESCAPE_ENGINE"]).resolve()
        self.assertTrue(binary.is_file(), binary)
        self.bundle_dir = TempBundle()
        self.addCleanup(self.bundle_dir.cleanup)
        self.state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        self.bundle = B.load(self.bundle_dir.root)
        self.store = StateStore(pathlib.Path(self.state_dir.name))
        self.engines = []
        self.binary = binary

        class RecordingEngine(EngineProcess):
            def __init__(eng):
                super().__init__(str(binary), ["--null-audio", "--settings",
                    str(pathlib.Path(self.state_dir.name) / "engine-settings.json")])
                eng.commands = []

            async def request(eng, msg):
                eng.commands.append(msg)
                return await super().request(msg)

        def factory():
            engine = RecordingEngine()
            self.engines.append(engine)
            return engine

        self.factory = factory
        await self.start_player()

    async def start_player(self):
        self.core = PlayerCore({self.bundle.name: self.bundle}, self.factory,
                               store=self.store, initial=self.store.load())
        self.server = ApiServer(self.core, port=0)
        self.port = await self.server.start()
        self.addAsyncCleanup(self.server.close)
        self.addAsyncCleanup(self.core.close)
        await self.core.start()
        state = await self.state()
        self.assertEqual(state["engine"]["state"], "running")
        self.assertIsNotNone(state["current"]["index"], state)
        self.assertIsNone(state["current"]["error"], state)

    async def state(self):
        doc = await api.get_state(self.port)
        V["state"].validate(doc)
        return doc

    async def ok(self, **cmd):
        V["command"].validate(cmd)
        reply = await api.command(self.port, cmd)
        V["reply"].validate(reply)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    async def until(self, predicate, timeout=10):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if predicate(await self.state()):
                return
            await asyncio.sleep(0.05)
        self.fail("real engine did not reach the expected state")

    async def test_real_contract_commands_and_events(self):
        async with api.Events(self.port) as events:
            kind, data = await events.next()
            V["event"].validate({"event": kind, "data": data})
            self.assertEqual(kind, "state")
            await self.ok(type="select", index=2)
            await self.ok(type="set", control="tempo", value=138)
            seen = set()
            for _ in range(60):
                kind, data = await events.next()
                V["event"].validate({"event": kind, "data": data})
                seen.add(kind)
                if {"state", "values", "status"} <= seen:
                    break
            self.assertTrue({"state", "values", "status"} <= seen, seen)
        await self.ok(type="params.list")
        await self.ok(type="reset", control="tempo")
        await self.ok(type="panic")
        await self.ok(type="bundle.list")
        await self.ok(type="bundle.check", name=self.bundle.name)
        await self.ok(type="config.get")
        await self.ok(type="audio.devices")
        await self.ok(type="midi.devices")
        for cmd in ({"type": "select", "index": 999},
                    {"type": "fake.inject", "what": "engineCrash"},
                    {"type": "config.put", "json": {}}):
            V["command"].validate(cmd)
            reply = await api.command(self.port, cmd)
            V["reply"].validate(reply)
            self.assertFalse(reply["ok"], reply)

    async def test_pg1_restart_reloads_composed_values(self):
        await self.ok(type="select", index=2)
        result = await self.ok(type="set", control="tempo", value=140)
        old = self.engines[-1]
        await old.kill()
        await self.until(lambda s: s["engine"]["restarts"] == 1 and
                         s["engine"]["state"] == "running" and not s["current"]["switching"] and
                         len(self.engines) == 2 and any(c["type"] == "loadGraph" for c in self.engines[-1].commands))
        requests = self.engines[-1].commands
        expected = ["controllerStream", "loadGraph"] if "controllerStream" in self.core.engine_info["capabilities"] else ["loadGraph"]
        self.assertEqual([c["type"] for c in requests], expected)
        patch = requests[-1]["patch"]
        self.assertEqual(B.find_module(patch, 1)["parameters"]["bpm"], result["value"])
        self.assertEqual((await self.state())["current"]["index"], 2)

    async def test_pg3_and_pg7_api_switches_with_sse_disconnect(self):
        count = int(os.environ.get("WIRESCAPE_SWITCH_COUNT", "50"))
        self.assertIn(count, (50, 200))
        await self.ok(type="select", index=2)
        pid = self.engines[-1].pid
        for i in range(count):
            # Repeatedly leave and return to the running clocked groove.
            target = 3 if i % 2 == 0 else 2
            async with api.Events(self.port) as events:
                kind, data = await events.next()
                V["event"].validate({"event": kind, "data": data})
                switch = asyncio.create_task(self.ok(type="select", index=target))
                await asyncio.sleep(0)
            self.assertEqual((await switch)["index"], target)
            self.assertEqual((await self.state())["current"]["index"], target)
            self.assertEqual(self.engines[-1].pid, pid)
        self.assertEqual((await self.state())["engine"]["restarts"], 0)

    async def test_pg5_saved_and_good_state_restore(self):
        await self.ok(type="select", index=2)
        result = await self.ok(type="set", control="tempo", value=135)
        await self.core.close()
        await self.server.close()
        await self.start_player()
        self.assertEqual((await self.state())["current"]["index"], 2)
        self.assertEqual((await self.state())["controls"]["tempo"]["value"], result["value"])
        await self.core.close()
        await self.server.close()
        good = self.store.good_path.read_bytes()
        self.store.path.write_text("{")
        await self.start_player()
        self.assertEqual((await self.state())["current"]["index"], 2)
        self.assertEqual(self.store.good_path.read_bytes(), good)


if __name__ == "__main__":
    unittest.main()
