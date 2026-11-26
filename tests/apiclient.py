# SPDX-License-Identifier: GPL-3.0-only
"""A tiny asyncio HTTP/SSE client for the Player API tests (standard library only)."""
import asyncio
import json


async def http(port: int, method: str, path: str, body: bytes = b"", headers: dict | None = None):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    h = {"Host": f"127.0.0.1:{port}", "Content-Length": str(len(body)), **(headers or {})}
    w.write((f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n").encode() + body)
    await w.drain()
    raw = await r.read()
    w.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    return status, payload


async def get_state(port: int) -> dict:
    status, body = await http(port, "GET", "/api/v1/state")
    assert status == 200, status
    return json.loads(body)


async def command(port: int, cmd: dict) -> dict:
    status, body = await http(port, "POST", "/api/v1/command", json.dumps(cmd).encode(),
                              {"Content-Type": "application/json"})
    assert status == 200, (status, body)
    return json.loads(body)


class Events:
    """An open SSE stream; `next()` returns (event, data)."""

    def __init__(self, port: int, controller: bool = False):
        self.port, self.controller = port, controller

    async def __aenter__(self):
        self.r, self.w = await asyncio.open_connection("127.0.0.1", self.port)
        q = "?controller=1" if self.controller else ""
        self.w.write(f"GET /api/v1/events{q} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await self.w.drain()
        while (await self.r.readline()) not in (b"\r\n", b""):
            pass
        return self

    async def __aexit__(self, *exc):
        self.w.close()

    async def next(self, timeout: float = 3.0):
        event, data = None, None
        while True:
            line = (await asyncio.wait_for(self.r.readline(), timeout)).decode().rstrip("\n")
            if line.startswith(":"):
                continue
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
            elif line == "" and event:
                return event, data

    async def until(self, event: str, pred=lambda d: True, timeout: float = 5.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            e, d = await self.next(max(0.05, end - loop.time()))
            if e == event and pred(d):
                return d
