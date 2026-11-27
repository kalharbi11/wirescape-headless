# SPDX-License-Identifier: GPL-3.0-only
"""Minimal systemd notification transport; never emits a heartbeat off the event loop."""
import asyncio
import logging
import os
import socket

log = logging.getLogger("player.notify")


def notify(message: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(message.encode("ascii"), address)
        return True
    except OSError as e:
        log.warning("systemd notification failed: %s", e)
        return False


async def watchdog(send=notify) -> None:
    loop = asyncio.get_running_loop()
    while True:
        due = loop.time() + 2.0
        await asyncio.sleep(2.0)
        if loop.time() - due < 2.0:
            send("WATCHDOG=1")
