# SPDX-License-Identifier: GPL-3.0-only
"""PG4 on a real pinned null-audio engine: script OSC reaches the graph."""
import asyncio
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest

from player import bundle as B
from player.core import PlayerCore
from player.engine_proc import EngineProcess
from player.server import ApiServer
from tests import apiclient as api
from tests.helpers import TempBundle, player
from tests.test_api import V
from tests.test_player_scripts import SCRIPT


class RealScript(unittest.IsolatedAsyncioTestCase):
    async def test_pg4(self):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(("127.0.0.1", 0))
        rx.setblocking(False)
        self.addCleanup(rx.close)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port_in = reserve.getsockname()[1]
        port_out = rx.getsockname()[1]
        config = player([
            {"patch": "patches/basics-01-first-tone.json"},
            {"patch": "patches/script-probe.json", "scripts": [{"file": "scripts/probe.py", "port": port_in}],
             "controls": [{"id": "dens", "target": {"script": {"file": "scripts/probe.py", "control": "density"}}},
                          {"id": "press", "target": {"script": {"file": "scripts/probe.py", "control": "press"}}}],
             "pages": [{"title": "Script", "controls": ["dens"]}]}])
        tb = TempBundle(config)
        self.addCleanup(tb.cleanup)
        # Independent gate witnesses the child applying the recalled control,
        # rather than requiring OSC Out to resend an unchanged CV.
        probe = SCRIPT.replace('density = ws.knob', 'replay_gate = ws.gate("Replayed", address="/test/replayed")\ndensity = ws.knob').replace('    gate.on()', '    gate.on()\n    replay_gate.send(float(density.value == 1.5))')
        probe = probe.replace("ws.start()", 'press = ws.button("Press")\npress_cv = ws.cv("Press count", address="/test/press")\nws.start()')
        probe = probe.replace("    gate.on()", "    gate.on()\n    press_cv.send(press.press_count / 4)")
        (tb.root / "scripts/probe.py").write_text(probe)
        patch = json.loads((tb.root / "patches/basics-01-first-tone.json").read_text())
        def row(address, kind):
            return dict(pattern=address, argument=0, kind=kind, input_min=0, input_max=1,
                        output_min=0, output_max=1, smoothing_ms=0,
                        timeout_ms=2000 if kind == "gate" else 0,
                        stale="zero" if kind == "gate" else "hold")
        patch["modules"] += [
            dict(id=101, module="osc.in", config=dict(port=port_in, lan=False,
                rows=[row("/test/gate", "gate"), row("/test/value", "cv"), row("/test/replayed", "gate"), row("/test/press", "cv")] + [dict(enabled=False) for _ in range(4)])),
            dict(id=102, module="osc.out", config=dict(port=port_out, rate_hz=100,
                rows=[dict(address="/echo/gate", kind="gate"), dict(address="/echo/value", kind="cv", deadband=0),
                      dict(address="/echo/replayed", kind="gate"),
                      dict(address="/echo/press", kind="cv", deadband=0)] + [dict(enabled=False) for _ in range(4)]))]
        for port in ("row1", "row2", "row3", "row4"):
            patch["connections"].append(dict(kind="signal", **{
                "from": dict(module=101, port=port), "to": dict(module=102, port=port)}))
        (tb.root / "patches/script-probe.json").write_text(json.dumps(patch))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        eng = EngineProcess(os.environ["WIRESCAPE_ENGINE"], ["--null-audio", "--settings",
                            str(Path(temp.name) / "engine-settings.json")])
        bundle = B.load(tb.root)
        core = PlayerCore({bundle.name: bundle}, lambda: eng)
        server = ApiServer(core, port=0)
        port = await server.start()
        self.addAsyncCleanup(server.close)
        self.addAsyncCleanup(core.close)
        await core.start()
        self.assertEqual(core.current["index"], 0, core.current)

        async def cmd(**c):
            V["command"].validate(c)
            reply = await api.command(port, c)
            V["reply"].validate(reply)
            self.assertTrue(reply["ok"], reply)

        loop = asyncio.get_running_loop()
        packets = []
        changed = asyncio.Event()

        async def collect():
            while True:
                packet, source = await loop.sock_recvfrom(rx, 2048)
                self.assertEqual(source[0], "127.0.0.1")
                address = packet.split(b"\0", 1)[0].decode("ascii")
                value = struct.unpack(">f", packet[-4:])[0]
                packets.append((loop.time(), address, value))
                changed.set()

        collector = asyncio.create_task(collect())

        async def stop_collector():
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)

        self.addAsyncCleanup(stop_collector)

        async def receive(address, value, start=0):
            deadline = loop.time() + 6
            cursor = start
            while True:
                if collector.done():
                    collector.result()
                while cursor < len(packets):
                    _, addr, actual = packets[cursor]
                    cursor += 1
                    if addr == address and abs(actual - value) < 1e-5:
                        return cursor
                changed.clear()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(changed.wait(), remaining)
                except TimeoutError:
                    break
            active = core.scripts.get("scripts/probe.py")
            self.fail(f"missing {address}={value}; packets={packets[-32:]}; "
                      f"script={active.doc() if active else None}; "
                      f"saved={active.values if active else None}; osc={core.osc_status}")

        await cmd(type="select", index=1)
        pid = eng.pid
        await receive("/echo/gate", 1)
        before_set = len(packets)
        await cmd(type="set", control="dens", value=1.5)
        await receive("/echo/value", .75, before_set)
        await receive("/echo/replayed", 1, before_set)
        script = core.scripts["scripts/probe.py"]
        before_press = len(packets)
        await cmd(type="set", control="press", value=.49)
        await cmd(type="set", control="press", value=.5)
        await receive("/echo/press", .25, before_press)
        before_press = len(packets)
        await cmd(type="set", control="press", norm=.5)
        await receive("/echo/press", .5, before_press)
        self.assertNotIn("press", script.values)
        self.assertNotIn("script:scripts/probe.py:press", core.values.get(1, {}))
        old_pid = script.proc.pid
        self.assertEqual(script.values["density"], 1.5)
        before_crash = len(packets)
        script.proc.kill()
        normal_zero = await receive("/echo/gate", 0, before_crash)
        replay_zero = await receive("/echo/replayed", 0, before_crash)
        await receive("/echo/gate", 1, normal_zero)
        await receive("/echo/replayed", 1, replay_zero)
        await receive("/echo/press", 0, before_crash)
        before_press = len(packets)
        await cmd(type="set", control="press", value=1)
        await receive("/echo/press", .25, before_press)
        self.assertNotIn("press", script.values)
        self.assertNotEqual(script.proc.pid, old_pid)
        self.assertEqual(script.values["density"], 1.5)
        self.assertGreaterEqual(script.restarts, 1)
        self.assertEqual(eng.pid, pid)
        self.assertEqual(core.engine_info["restarts"], 0)
        V["state"].validate(await api.get_state(port))
