# SPDX-License-Identifier: GPL-3.0-only
"""Owner smoke graph gate witness on the pinned null-audio engine."""
import asyncio
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
from tools.make_smoke_bundle import make


class RealSmokeBundle(unittest.IsolatedAsyncioTestCase):
    async def test_gate_zero_without_engine_restart(self):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(("127.0.0.1", 0))
        rx.setblocking(False)
        self.addCleanup(rx.close)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port_in = reserve.getsockname()[1]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / "smoke"
        make(dest, port_in, rx.getsockname()[1])
        bundle = B.load(dest)
        eng = EngineProcess(os.environ["WIRESCAPE_ENGINE"], ["--null-audio", "--settings",
                            str(Path(tmp.name) / "engine-settings.json")])
        core = PlayerCore({bundle.name: bundle}, lambda: eng)
        server = ApiServer(core, port=0)
        port = await server.start()
        self.addAsyncCleanup(server.close)
        self.addAsyncCleanup(core.close)
        await core.start()
        self.assertEqual(core.current["index"], 0, core.current)
        pid = eng.pid

        async def receive(value):
            loop = asyncio.get_running_loop()
            end = loop.time() + 6
            while loop.time() < end:
                packet = await asyncio.wait_for(loop.sock_recv(rx, 2048), end - loop.time())
                if packet.startswith(b"/ws/smoke_echo\0") and abs(struct.unpack(">f", packet[-4:])[0] - value) < 1e-5:
                    return
            self.fail(f"missing graph gate {value}")

        await receive(1)
        reply = await api.command(port, {"type": "script.stop", "file": "scripts/smoke_gate.py"})
        self.assertTrue(reply["ok"], reply)
        await receive(0)
        self.assertEqual(eng.pid, pid)
        self.assertEqual(core.engine_info["restarts"], 0)
