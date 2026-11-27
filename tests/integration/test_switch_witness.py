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
            status_by_gen = None

            def _dispatch(self, msg):
                if msg.get('session') == self.session and msg.get('type') == 'status':
                    self.status_by_gen = (str(msg.get('gen')), msg['status'].get('osc', {}))
                super()._dispatch(msg)

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
        receiver.setblocking(False)
        # Prime the capture executor outside all timed observations. UDP receipt
        # itself stays on the loop, avoiding executor startup/dispatch latency.
        await asyncio.to_thread(lambda: None)
        await core.start()
        self.assertEqual(core.current["index"], 0, core.current)
        address = patches[0][0]
        marks = []

        async def wait_route(node, out):
            deadline = time.monotonic() + 5  # same readiness bound as lab oracle
            while time.monotonic() < deadline:
                observed = eng.status_by_gen
                if observed and observed[0] == str(eng.swap['gen']):
                    osc = observed[1]
                    routes, outputs = osc.get('routes', []), osc.get('out', [])
                    if (osc.get('enabled') and not osc.get('lan') and len(routes) == len(outputs) == 1
                            and str(routes[0].get('module')) == str(node) and routes[0].get('port') == w.PORT_IN
                            and routes[0].get('bind') == '127.0.0.1' and routes[0].get('state') == 'listening'
                            and osc.get('last_error') != 'port-busy'
                            and str(outputs[0].get('module')) == str(out) and outputs[0].get('port') == w.PORT_OUT
                            and outputs[0].get('state') == 'sending'):
                        return
                await asyncio.sleep(.005)
            self.fail(f'route not ready: gen={eng.swap["gen"]}, status={eng.status_by_gen}')

        async def wait_receive(deadline, expected, retired_gate=None, sent=None):
            pending = set(expected)
            loop = asyncio.get_running_loop()
            observed = []
            try:
                while pending:
                    remaining = deadline - time.monotonic()
                    w.require(remaining > 0, f'OSC receive deadline: {pending}')
                    payload, source = await asyncio.wait_for(loop.sock_recvfrom(receiver, 1500), remaining)
                    w.require(source[0] == '127.0.0.1', 'non-loopback packet')
                    received = w.decode(payload)
                    observed.append((round(time.monotonic(), 6), received))
                    if retired_gate is not None and received == retired_gate:
                        w.require(retired_gate in pending, 'duplicate retired OSC gate zero')
                    pending.discard(received)
                w.require(time.monotonic() <= deadline, 'OSC deadline exceeded')
            except (TimeoutError, w.SoakFailure) as exc:
                self.fail(f'{exc!r}; pending={pending}; sent={sent}; deadline={deadline}; '
                          f'now={time.monotonic()}; route={eng.status_by_gen}; packets={observed[-16:]}')

        async def offered_load():
            value = 0.0
            while True:
                sender.sendto(w.packet("/ob-h3/load", value), ("127.0.0.1", w.PORT_IN))
                value = 1.0 - value
                await asyncio.sleep(.005)

        await wait_route(patches[0][1], patches[0][2])
        load = asyncio.create_task(offered_load())
        try:
            # Establish that the first route actually works before starting.
            sent = time.monotonic()
            sender.sendto(w.packet(address + "/in", .5), ("127.0.0.1", w.PORT_IN))
            await wait_receive(sent + 2, {(address + "/echo", (.5,))}, sent=sent)
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
                sent = time.monotonic()
                sender.sendto(w.packet(address + "/in", value), ("127.0.0.1", w.PORT_IN))
                # Both the new route sentinel and the old gate release must
                # actually arrive. No retry or widened deadline.
                retired_gate = (old + "/gate", (0.0,))
                await wait_receive(acknowledged + .050, {
                    (address + "/echo", (value,)), retired_gate}, retired_gate, sent=sent)
                swap = eng.swap
                await asyncio.to_thread(w.wait_for_swap_capture, capture, swap["re"], int(swap["gen"]), 5.0)
                await asyncio.to_thread(w.assert_no_duplicate_retired_gate, receiver, retired_gate)
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
