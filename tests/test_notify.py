# SPDX-License-Identifier: GPL-3.0-only
"""PG8: watchdog messages originate on the API event loop, not a background thread."""
import asyncio
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from player.notify import notify, watchdog


class NotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_unix_datagram_and_no_environment(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as rx:
            path = str(Path(directory) / "notify")
            rx.bind(path)
            rx.setblocking(False)
            with patch.dict(os.environ, {"NOTIFY_SOCKET": path}):
                self.assertTrue(notify("READY=1"))
                self.assertEqual(await asyncio.wait_for(asyncio.get_running_loop().sock_recv(rx, 256), 1), b"READY=1")
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(notify("READY=1"))

    async def test_pg8_blocked_loop_does_not_send_late_heartbeat(self):
        observed = []
        task = asyncio.create_task(watchdog(send=lambda msg: observed.append((msg, time.monotonic()))))
        try:
            await asyncio.sleep(2.1)
            self.assertEqual(len(observed), 1)
            time.sleep(4.2)  # deliberately block the actual event loop over the 2 s lag bound
            await asyncio.sleep(.05)
            self.assertEqual(len(observed), 1, observed)
            await asyncio.sleep(2.1)
            self.assertEqual(len(observed), 2, observed)
            self.assertTrue(all(msg == "WATCHDOG=1" for msg, _ in observed))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
