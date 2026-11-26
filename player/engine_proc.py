# SPDX-License-Identifier: GPL-3.0-only
"""The real engine adapter: `wirescape-engine` over stdio NDJSON (lab protocol v0).

One instance is one engine process (lab `docs/specs/ENGINE_PROTOCOL.md` at LAB_PIN, §1–§2):
- one JSON object per LF-terminated line each way; stdout carries protocol lines only;
- commands carry `v:0` and a fresh `id`; replies carry `re`; pushes carry `type`;
- the first line is `hello`, and its `session` is the one accepted from then on;
- stdin EOF is a clean stop (exit 0).

stdout and stderr are drained continuously (0025 §2.1). Stderr lines go to the
`player.engine` logger with an `engine:` prefix. When the process exits, pending requests
fail with ConnectionError and `on_exit(code, signal)` fires once.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import signal as _signal
from typing import Sequence

log = logging.getLogger("player.engine")
LINE_LIMIT = 2_097_152 + 1  # protocol hard cap per line, plus the LF
STOP_GRACE = 2.0


class EngineProcess:
    def __init__(self, path: str, args: Sequence[str] = ()):
        self.path, self.args = str(path), list(args)
        self.on_push = None
        self.on_exit = None
        self.proc: asyncio.subprocess.Process | None = None
        self.session: str | None = None
        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future] = {}
        self._hello: asyncio.Future | None = None
        self._tasks: list[asyncio.Task] = []
        self._exited = False

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    async def start(self) -> dict:
        loop = asyncio.get_running_loop()
        self._hello = loop.create_future()
        self.proc = await asyncio.create_subprocess_exec(
            self.path, *self.args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=LINE_LIMIT)
        self._tasks = [loop.create_task(self._read_stdout()), loop.create_task(self._read_stderr()),
                       loop.create_task(self._wait())]
        return await asyncio.shield(self._hello)

    async def request(self, msg: dict) -> dict:
        if self._exited or self.proc is None or self.proc.stdin is None or self.session is None:
            raise ConnectionError("engine is not running")
        rid = f"p{next(self._ids)}"
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        line = json.dumps({**msg, "v": 0, "id": rid}, separators=(",", ":"), allow_nan=False) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            await self.proc.stdin.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError) as e:
            self._pending.pop(rid, None)
            raise ConnectionError(f"engine stdin closed: {e}") from None
        return await fut

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        """Close stdin, wait 2 s, then SIGKILL (0025 §2.2 "Stop")."""
        if not self.proc:
            return
        if self.proc.stdin and not self.proc.stdin.is_closing():
            self.proc.stdin.close()
        try:
            await asyncio.wait_for(asyncio.shield(self._tasks[2]), STOP_GRACE)
        except asyncio.TimeoutError:
            await self.kill()
            await self._tasks[2]

    # -- internals ---------------------------------------------------------------------

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            try:
                line = await self.proc.stdout.readline()
            except ValueError:  # over the line cap: the protocol forbids it; skip the line
                log.warning("engine stdout line over the protocol cap was discarded")
                continue
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                log.warning("engine stdout line is not JSON (a protocol bug): %r", line[:200])
                continue
            if isinstance(msg, dict):
                self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        if msg.get("type") == "hello" and self.session is None:
            self.session = msg.get("session")
            if self._hello and not self._hello.done():
                self._hello.set_result(msg)
            return
        if self.session is None or msg.get("session") != self.session:
            return  # lines from a noncurrent session are ignored (ENGINE_PROTOCOL §2)
        if "re" in msg and "type" not in msg:
            fut = self._pending.pop(msg.get("re"), None) if msg.get("re") is not None else None
            if fut and not fut.done():
                fut.set_result(msg)
            return
        if self.on_push:
            self.on_push(msg)

    async def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            try:
                line = await self.proc.stderr.readline()
            except ValueError:
                continue
            if not line:
                return
            log.info("engine: %s", line.decode("utf-8", "replace").rstrip())

    async def _wait(self) -> None:
        assert self.proc
        rc = await self.proc.wait()
        await asyncio.gather(*self._tasks[:2], return_exceptions=True)
        self._exited = True
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("engine exited"))
        self._pending.clear()
        if self._hello and not self._hello.done():
            self._hello.set_exception(ConnectionError(f"engine exited before hello ({rc})"))
        code, sig = (None, _signal_name(-rc)) if rc < 0 else (rc, None)
        if self.on_exit:
            self.on_exit(code, sig)


def _signal_name(n: int) -> str:
    try:
        return _signal.Signals(n).name
    except ValueError:
        return f"SIG{n}"
