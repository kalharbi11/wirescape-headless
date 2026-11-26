# SPDX-License-Identifier: GPL-3.0-only
"""Player API v1 over loopback HTTP/1.1 and Server-Sent Events (lab proposals/0025 §2.5).

Standard library only (`asyncio` streams). Endpoints:
  GET  /api/v1/state     the whole state document
  POST /api/v1/command   one command -> {"ok":true,"result":…} or {"ok":false,"code","message"}
  GET  /api/v1/events    SSE: state, values, status, and controller with ?controller=1
  GET  /ui/…             the reference UI's static files (ui/)

Cross-site requests from a browser on the same machine are refused: POST needs
`Content-Type: application/json` (which a page on another origin cannot send without a
preflight this server never grants), and a present `Origin` must be this server's own.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import pathlib
import signal
import sys
import urllib.parse

from .core import CommandError, PlayerCore

DEFAULT_PORT = 8770
MAX_BODY = 4 * 1024 * 1024
UI_ROOT = pathlib.Path(__file__).resolve().parent.parent / "ui"
KEEPALIVE_S = 15.0


class ApiServer:
    def __init__(self, core: PlayerCore, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 ui_root: pathlib.Path = UI_ROOT):
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("the v1 Player API binds loopback only (0025 §2.5, §9)")
        self.core, self.host, self.port, self.ui_root = core, host, port, ui_root
        self.server: asyncio.base_events.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._client, self.host, self.port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    # -- HTTP -----------------------------------------------------------------------

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._serve_one(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _serve_one(self, reader, writer) -> None:
        line = await reader.readline()
        if not line:
            return
        try:
            method, target, _ = line.decode("latin-1").rstrip("\r\n").split(" ", 2)
        except ValueError:
            return await self._send(writer, 400, {"ok": False, "code": "invalid", "message": "bad request line"})
        headers = {}
        while True:
            h = await reader.readline()
            if h in (b"\r\n", b"\n", b""):
                break
            k, _, v = h.decode("latin-1").partition(":")
            headers[k.strip().lower()] = v.strip()
        url = urllib.parse.urlsplit(target)
        path, query = url.path, urllib.parse.parse_qs(url.query)

        origin = headers.get("origin")
        if origin and origin not in self._own_origins():
            return await self._send(writer, 403, {"ok": False, "code": "refused", "message": "cross-origin request"})

        if method == "GET" and path == "/api/v1/state":
            return await self._send(writer, 200, self.core.state_doc())
        if method == "POST" and path == "/api/v1/command":
            if headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return await self._send(writer, 415, {"ok": False, "code": "invalid",
                                                      "message": "Content-Type must be application/json"})
            n = int(headers.get("content-length", "0") or 0)
            if n > MAX_BODY:
                return await self._send(writer, 413, {"ok": False, "code": "invalid", "message": "body too large"})
            body = await reader.readexactly(n) if n else b""
            try:
                cmd = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return await self._send(writer, 400, {"ok": False, "code": "invalid", "message": "malformed JSON"})
            return await self._send(writer, 200, await self.run_command(cmd))
        if method == "GET" and path == "/api/v1/events":
            return await self._events(writer, controller=query.get("controller", ["0"])[0] == "1")
        if method == "GET" and (path == "/ui" or path.startswith("/ui/")):
            return await self._static(writer, path)
        if method == "GET" and path == "/":
            return await self._raw(writer, 302, b"", "text/plain", extra={"Location": "/ui/"})
        return await self._send(writer, 404, {"ok": False, "code": "not-found", "message": f"{method} {path}"})

    async def run_command(self, cmd) -> dict:
        try:
            return {"ok": True, "result": await self.core.command(cmd)}
        except CommandError as e:
            out = {"ok": False, "code": e.code, "message": e.message}
            if e.engine_code:
                out["engineCode"] = e.engine_code
            return out

    def _own_origins(self) -> set[str]:
        return {f"http://{h}:{self.port}" for h in ("127.0.0.1", "localhost", "[::1]")}

    async def _send(self, writer, status: int, doc: dict) -> None:
        await self._raw(writer, status, json.dumps(doc, separators=(",", ":")).encode(), "application/json")

    async def _raw(self, writer, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        reason = {200: "OK", 302: "Found", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
                  413: "Payload Too Large", 415: "Unsupported Media Type"}.get(status, "OK")
        head = [f"HTTP/1.1 {status} {reason}", f"Content-Type: {ctype}", f"Content-Length: {len(body)}",
                "Cache-Control: no-store", "Connection: close", "X-Content-Type-Options: nosniff"]
        head += [f"{k}: {v}" for k, v in (extra or {}).items()]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body)
        await writer.drain()

    async def _static(self, writer, path: str) -> None:
        rel = path[len("/ui"):].lstrip("/") or "index.html"
        root = self.ui_root.resolve()
        f = (root / rel).resolve()
        if root not in f.parents and f != root or not f.is_file():
            return await self._send(writer, 404, {"ok": False, "code": "not-found", "message": path})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        await self._raw(writer, 200, f.read_bytes(), ctype)

    async def _events(self, writer, controller: bool) -> None:
        head = ["HTTP/1.1 200 OK", "Content-Type: text/event-stream", "Cache-Control: no-store",
                "Connection: keep-alive", "X-Content-Type-Options: nosniff"]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        sub = self.core.subscribe(controller=controller)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(sub.queue.get(), KEEPALIVE_S)
                except asyncio.TimeoutError:
                    writer.write(b": keepalive\n\n")
                    await writer.drain()
                    continue
                if item is None or item[0] == "end":
                    break
                event, data = item
                writer.write(f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode())
                await writer.drain()
        finally:
            self.core.unsubscribe(sub)


# -- python -m player fake ----------------------------------------------------------------


def main_fake(argv: list[str]) -> int:
    from . import bundle as B
    from .fake_engine import FakeEngine

    ap = argparse.ArgumentParser(prog="python -m player fake",
                                 description="The Player with the fake engine (0025 §2.6).")
    default = pathlib.Path(__file__).resolve().parent.parent / "examples" / "bundle"
    ap.add_argument("--bundle", type=pathlib.Path, default=default)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    a = ap.parse_args(argv)
    try:
        b = B.load(a.bundle)
    except B.BundleError as e:
        print(f"bundle: {e}", file=sys.stderr)
        return 1

    async def run() -> None:
        osc = b.config.get("osc") if isinstance(b.config.get("osc"), dict) else {}
        core = PlayerCore({b.name: b}, FakeEngine, fake=True, control_port=osc.get("controlPort", 0))
        server = ApiServer(core, port=a.port)
        port = await server.start()
        print(f"fake player: http://127.0.0.1:{port}/api/v1/state  (UI at /ui/)", flush=True)
        await core.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        await stop.wait()
        await core.close()
        await server.close()

    asyncio.run(run())
    return 0
