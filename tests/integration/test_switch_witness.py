# SPDX-License-Identifier: GPL-3.0-only
"""PG7 through Player select, using the pinned lab's A93 capture/OSC oracles."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest

from player import bundle as B
from player.core import PlayerCore
from player.engine_proc import EngineProcess
from player.server import ApiServer
from tests import apiclient as api
from tests.helpers import TempBundle, player
from tests.test_api import V


class SwitchWitness(unittest.IsolatedAsyncioTestCase):
    async def test_pg7(self):
        lab = Path(os.environ["WIRESCAPE_LAB"])
        sys.path.insert(0, str(lab / "host" / "sidecar"))
        self.addCleanup(sys.path.remove, str(lab / "host" / "sidecar"))
        w = importlib.import_module("patch_switch_tests")
        count = int(os.environ.get("WIRESCAPE_SWITCH_COUNT", "50"))
        self.assertIn(count, (50, 200))
        tb = TempBundle(player([{"patch": "patches/witness-a.json"},
                                {"patch": "patches/witness-b.json"}]))
        self.addCleanup(tb.cleanup)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        capture = root / "switch.f32"
        patches = []
        for i, name in enumerate(("a", "b")):
            patch, address, node, out = w.patch(i)
            # Keep the authored groove running in both graphs. Relocate only
            # instance IDs and output buses in this temporary fixture.
            groove = json.loads((tb.root / "patches/basics-08-clocked-groove.json").read_text())
            for m in groove["modules"]:
                m["id"] += 100
            for c in groove["connections"]:
                c["from"]["module"] += 100
                c["to"]["module"] += 100
            for o in groove["outputs"]:
                o["module"] += 100
                o["bus_channel"] += 2
            patch["modules"] += groove["modules"]
            patch["connections"] += groove["connections"]
            patch["outputs"] += groove["outputs"]
            (tb.root / f"patches/witness-{name}.json").write_text(json.dumps(patch))
            patches.append((address, node, out))

        class CaptureEngine(EngineProcess):
            async def request(self, msg):
                reply = await super().request(msg)
                if msg["type"] == "loadGraph" and reply.get("ok"):
                    self.swap = reply
                return reply

        eng = CaptureEngine(os.environ["WIRESCAPE_ENGINE"], [
            "--null-audio", "--settings", str(root / "engine-settings.json"),
            "--rate", str(w.RATE), "--block", str(w.BLOCK),
            "--capture-null-sink", str(capture)])
        bundle = B.load(tb.root)
        core = PlayerCore({bundle.name: bundle}, lambda: eng)
        server = ApiServer(core, port=0)
        port = await server.start()
        self.addAsyncCleanup(server.close)
        self.addAsyncCleanup(core.close)
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(receiver.close)
        self.addCleanup(sender.close)
        receiver.bind(("127.0.0.1", w.PORT_OUT))
        await core.start()
        self.assertEqual(core.current["index"], 0, core.current)
        address = patches[0][0]
        marks = []

        async def wait_receive(deadline, expected):
            await asyncio.to_thread(w.receive_until, receiver, deadline, expected)

        async def offered_load():
            value = 0.0
            while True:
                sender.sendto(w.packet("/ob-h3/load", value), ("127.0.0.1", w.PORT_IN))
                value = 1.0 - value
                await asyncio.sleep(.005)

        load = asyncio.create_task(offered_load())
        try:
            # Establish that the first route actually works before starting.
            sender.sendto(w.packet(address + "/in", .5), ("127.0.0.1", w.PORT_IN))
            await wait_receive(time.monotonic() + 2, {(address + "/echo", (.5,))})
            for n in range(1, count + 1):
                held = await eng.request({"type": "noteOn", "note": 60, "velocity": .5})
                self.assertTrue(held["ok"], held)
                await wait_receive(time.monotonic() + 2, {
                    (address + "/gate", (1.0,)), (address + "/note", (60, .5, 0))})
                await asyncio.sleep(2 * w.BLOCK / w.RATE)
                target = n % 2
                cmd = {"type": "select", "index": target}
                V["command"].validate(cmd)
                async with api.Events(port) as events:
                    kind, data = await events.next()
                    V["event"].validate({"event": kind, "data": data})
                    pending = asyncio.create_task(api.command(port, cmd))
                    await asyncio.sleep(0)
                reply = await pending
                acknowledged = time.monotonic()
                V["reply"].validate(reply)
                self.assertTrue(reply["ok"], reply)
                self.assertEqual(reply["result"]["index"], target)
                old = address
                address, node, out = patches[target]
                value = n / 2048
                sender.sendto(w.packet(address + "/in", value), ("127.0.0.1", w.PORT_IN))
                # Both the new route sentinel and the old gate release must
                # actually arrive. No retry or widened deadline.
                await wait_receive(acknowledged + .050, {
                    (address + "/echo", (value,)), (old + "/gate", (0.0,))})
                swap = eng.swap
                await asyncio.to_thread(w.wait_for_swap_capture, capture, swap["re"], int(swap["gen"]), 5.0)
                marks.append((held["re"], swap["re"]))
                self.assertEqual(core.engine_info["restarts"], 0)
            self.assertEqual(core.current["index"], count % 2)
        finally:
            load.cancel()
            await asyncio.gather(load, return_exceptions=True)
            await core.close()
        # Original lab sample-level fade and gate/held-note oracle.
        w.analyze(capture, count, marks)


if __name__ == "__main__":
    unittest.main()
