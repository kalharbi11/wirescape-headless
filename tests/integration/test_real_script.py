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
             "controls": [{"id": "dens", "target": {"script": {"file": "scripts/probe.py", "control": "density"}}}],
             "pages": [{"title": "Script", "controls": ["dens"]}]}])
        tb = TempBundle(config)
        self.addCleanup(tb.cleanup)
        (tb.root / "scripts/probe.py").write_text(SCRIPT)
        patch = json.loads((tb.root / "patches/basics-01-first-tone.json").read_text())
        def row(address, kind):
            return dict(pattern=address, argument=0, kind=kind, input_min=0, input_max=1,
                        output_min=0, output_max=1, smoothing_ms=0,
                        timeout_ms=2000 if kind == "gate" else 0,
                        stale="zero" if kind == "gate" else "hold")
        patch["modules"] += [
            dict(id=101, module="osc.in", config=dict(port=port_in, lan=False,
                rows=[row("/test/gate", "gate"), row("/test/value", "cv")] + [dict(enabled=False) for _ in range(6)])),
            dict(id=102, module="osc.out", config=dict(port=port_out, rate_hz=100,
                rows=[dict(address="/echo/gate", kind="gate"), dict(address="/echo/value", kind="cv", deadband=0)]
                + [dict(enabled=False) for _ in range(6)]))]
        for port in ("row1", "row2"):
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

        async def receive(address, value):
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 6
            while loop.time() < deadline:
                packet = await asyncio.wait_for(loop.sock_recv(rx, 2048), deadline - loop.time())
                if packet.startswith(address.encode() + b"\0") and abs(struct.unpack(">f", packet[-4:])[0] - value) < 1e-5:
                    return
            self.fail(f"missing real engine OSC echo {address} {value}")

        await cmd(type="select", index=1)
        pid = eng.pid
        await receive("/echo/gate", 1)
        await cmd(type="set", control="dens", value=1.5)
        await receive("/echo/value", .75)
        script = core.scripts["scripts/probe.py"]
        script.proc.kill()
        await receive("/echo/gate", 0)
        await receive("/echo/gate", 1)
        await receive("/echo/value", .75)
        self.assertGreaterEqual(script.restarts, 1)
        self.assertEqual(eng.pid, pid)
        self.assertEqual(core.engine_info["restarts"], 0)
        V["state"].validate(await api.get_state(port))
