# SPDX-License-Identifier: GPL-3.0-only
"""wsrun: the Wirescape script runner (lab proposals/0025 §4.3, §4.5).

A library (the Player imports it) and a CLI:

    python -I wsrun.py print-config SCRIPT        # the declaration, 5 s timeout
    python -I wsrun.py run SCRIPT [--port N]      # supervise one script in the foreground
    python -I wsrun.py serve --root DIR           # NDJSON on stdio (Studio desktop)

Per script: one process, `python -I -u <script> --ws-runner`, with its folder as working
directory and only `WS_OSC_HOST=127.0.0.1` and `WS_OSC_PORT=<port>` added to the
environment. stdin carries NDJSON controls and `stop`; stdout lines starting with `@ws `
are `declare` and `heartbeat`, every other line is log.

- Stop: send `stop`, wait 500 ms, terminate, wait 2 s, kill. Then 0 goes to every declared
  gate address, from the declaration received, even after a crash. The zeros are sent by a
  short-lived `python -I ws.py --zero-gates` child, so the process that imports this
  module opens no UDP socket (headless AGENTS rule 5).
- Restart: 250 ms doubling to 30 s, never giving up, reset after 30 s up; the count is kept.
- Stalled: 5 s without a heartbeat marks the script `stalled`; it is not killed.
- Only files inside the given root (the bundle's `scripts/`) are started.
- Control values are kept and re-sent after a restart.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import time
from typing import Any, Callable

HERE = pathlib.Path(__file__).resolve().parent
WS_HELPER = HERE / "ws.py"
PRINT_CONFIG_TIMEOUT = 5.0
STOP_WAIT = 0.5
TERM_WAIT = 2.0
RESTART_INITIAL = 0.25
RESTART_MAX = 30.0
HEALTHY_RESET = 30.0
STALL_AFTER = 5.0
OSC_HOST = "127.0.0.1"

log = logging.getLogger("player.script")


class ScriptError(Exception):
    pass


def resolve_script(root: pathlib.Path, rel: str) -> pathlib.Path:
    """`rel` inside `root`, as an existing .py file; never a path that leaves `root`."""
    root = pathlib.Path(root).resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise ScriptError(f"{rel}: scripts must live inside {root.name}/")
    if p.suffix != ".py" or not p.is_file():
        raise ScriptError(f"{rel}: not a .py file")
    return p


def print_config(script: pathlib.Path, timeout: float = PRINT_CONFIG_TIMEOUT) -> dict:
    """`python -I script --print-config` in the script's folder; raises ScriptError."""
    script = pathlib.Path(script)
    try:
        r = subprocess.run([sys.executable, "-I", str(script), "--print-config"], cwd=script.parent,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ScriptError(f"{script.name}: --print-config took over {timeout:g} s") from None
    if r.returncode != 0:
        raise ScriptError(f"{script.name}: --print-config exited {r.returncode}: {r.stderr.strip()[-300:]}")
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        raise ScriptError(f"{script.name}: --print-config did not print one JSON document") from None
    if not isinstance(doc, dict) or doc.get("format") != "wirescape.script" or doc.get("version") != 1:
        raise ScriptError(f"{script.name}: not a wirescape.script v1 declaration")
    return doc


def gate_addresses(decl: dict | None) -> list[str]:
    out: list[str] = []
    for o in (decl or {}).get("outputs", []):
        if not isinstance(o, dict):
            continue
        if o.get("kind") == "gate":
            a, n = o.get("address", ""), o.get("channels", 1)
        elif o.get("kind") == "voice":
            a, n = (o.get("addresses") or {}).get("gate", ""), o.get("voices", 1)
        else:
            continue
        if not isinstance(a, str) or not a.startswith("/"):
            continue
        out += [a.replace("*", str(i)) for i in range(1, int(n) + 1)] if "*" in a else [a]
    return out


async def zero_gates(port: int, addresses: list[str], host: str = OSC_HOST) -> None:
    if not addresses:
        return
    p = await asyncio.create_subprocess_exec(sys.executable, "-I", str(WS_HELPER), "--zero-gates", host,
                                             str(port), *addresses, stdout=asyncio.subprocess.DEVNULL)
    await p.wait()


class Script:
    """One supervised script process. States: running, stalled, stopped, crashed, restarting."""

    def __init__(self, path: pathlib.Path, port: int, *, on_change: Callable[["Script"], None] | None = None,
                 on_log: Callable[[str], None] | None = None, clock: Callable[[], float] = time.monotonic):
        self.path = pathlib.Path(path)
        self.port = port
        self.on_change = on_change
        self.on_log = on_log
        self.clock = clock
        self.state = "stopped"
        self.restarts = 0
        self.declaration: dict | None = None
        self.values: dict[str, Any] = {}
        self.last_exit: int | None = None
        self.drops = 0
        self.proc: asyncio.subprocess.Process | None = None
        self.delays: list[float] = []
        self._delay = RESTART_INITIAL
        self._want = False
        self._task: asyncio.Task | None = None
        self._started_at = 0.0
        self._heartbeat = 0.0
        self._watch: asyncio.Task | None = None
        self._spawning: asyncio.Task | None = None
        self._declared = False

    # -- public --------------------------------------------------------------------

    async def start(self) -> None:
        if self._want:
            return
        self._want = True
        self._task = asyncio.get_running_loop().create_task(self._supervise())

    async def stop(self) -> None:
        self._want = False
        if self._task:
            if self._spawning is not None:
                try:
                    await asyncio.shield(self._spawning)
                except OSError:
                    pass
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._stop_proc()
        self._set("stopped")

    async def restart(self) -> None:
        await self.stop()
        self._delay = RESTART_INITIAL
        await self.start()

    async def control(self, cid: str, value: Any) -> None:
        self.values[cid] = value
        if self._declared:
            await self._write({"type": "control", "id": cid, "value": value})

    def doc(self) -> dict:
        return {"state": self.state, "restarts": self.restarts, "controls": (self.declaration or {}).get("controls", [])}

    # -- internals -----------------------------------------------------------------

    def _set(self, state: str) -> None:
        if state != self.state:
            self.state = state
            if self.on_change:
                self.on_change(self)

    async def _write(self, msg: dict) -> None:
        p = self.proc
        if p is None or p.stdin is None or p.returncode is not None:
            return
        try:
            p.stdin.write((json.dumps(msg) + "\n").encode())
            await p.stdin.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError):
            pass

    async def _spawn(self) -> asyncio.subprocess.Process:
        env = dict(os.environ, WS_OSC_HOST=OSC_HOST, WS_OSC_PORT=str(self.port))
        return await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-u", str(self.path), "--ws-runner", cwd=self.path.parent, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        while self._want:
            self._declared = False
            self._spawning = loop.create_task(self._spawn())
            try:
                self.proc = await asyncio.shield(self._spawning)
            except OSError as exc:
                self.proc = None
                self.last_exit = None
                log.warning("%s: spawn failed: %s", self.path.name, exc)
                if not self._want:
                    return
                self.restarts += 1
                self._set("crashed")
                delay, self._delay = self._delay, min(RESTART_MAX, self._delay * 2)
                self.delays.append(delay)
                self._set("restarting")
                await asyncio.sleep(delay)
                continue
            finally:
                self._spawning = None
            self._started_at = self._heartbeat = self.clock()
            self._set("running")
            self._watch = loop.create_task(self._watch_stall())
            try:
                await self._read(self.proc)
                rc = await self.proc.wait()
            finally:
                self._watch.cancel()
                await asyncio.gather(self._watch, return_exceptions=True)
            self._declared = False
            self.last_exit = rc
            if self.proc.stdin is not None:
                self.proc.stdin.close()
            await zero_gates(self.port, gate_addresses(self.declaration))
            if not self._want:
                return
            if self.clock() - self._started_at >= HEALTHY_RESET:
                self._delay = RESTART_INITIAL
            self.restarts += 1
            self._set("crashed")
            delay, self._delay = self._delay, min(RESTART_MAX, self._delay * 2)
            self.delays.append(delay)
            self._set("restarting")
            await asyncio.sleep(delay)

    async def _read(self, p: asyncio.subprocess.Process) -> None:
        assert p.stdout
        while True:
            line = await p.stdout.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\n")
            if text.startswith("@ws "):
                kind, _, body = text[4:].partition(" ")
                try:
                    doc = json.loads(body)
                except ValueError:
                    doc = None
                if kind == "declare" and isinstance(doc, dict):
                    self.declaration = doc
                    self._heartbeat = self.clock()
                    self._declared = True
                    # Replay only after the child has declared its controls. Values
                    # changed during backoff or startup are included in the snapshot.
                    for cid, v in list(self.values.items()):
                        await self._write({"type": "control", "id": cid, "value": v})
                    if self.on_change:
                        self.on_change(self)
                    continue
                if kind == "heartbeat" and isinstance(doc, dict):
                    self._heartbeat = self.clock()
                    self.drops = int(doc.get("drops", 0) or 0)
                    if self.state == "stalled":
                        self._set("running")
                    continue
            if self.on_log:
                self.on_log(text)
            else:
                log.info("%s: %s", self.path.name, text)

    async def _watch_stall(self) -> None:
        while True:
            await asyncio.sleep(min(0.25, STALL_AFTER / 4))
            if self.state == "running" and self.clock() - self._heartbeat > STALL_AFTER:
                self._set("stalled")

    async def _stop_proc(self) -> None:
        p = self.proc
        if p is None:
            return
        if p.returncode is None:
            await self._write({"type": "stop"})
            if not await _wait(p, STOP_WAIT):
                try:
                    p.terminate()
                except ProcessLookupError:
                    pass
                if not await _wait(p, TERM_WAIT):
                    try:
                        p.kill()
                    except ProcessLookupError:
                        pass
                    await p.wait()
        self.last_exit = p.returncode
        self.proc = None
        await zero_gates(self.port, gate_addresses(self.declaration))


async def _wait(p: asyncio.subprocess.Process, t: float) -> bool:
    try:
        await asyncio.wait_for(p.wait(), t)
        return True
    except asyncio.TimeoutError:
        return False


# ============================================================================ CLI


def _emit(doc: dict) -> None:
    sys.stdout.write(json.dumps(doc, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def _serve(root: pathlib.Path) -> int:
    """NDJSON on stdio: start, stop, restart, control, printConfig. Events: state, log, reply."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    scripts: dict[str, Script] = {}

    def changed(s: Script, rel: str) -> None:
        _emit({"type": "state", "file": rel, **s.doc()})

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
            t, rel = msg.get("type"), msg.get("file", "")
            if t == "printConfig":
                _emit({"type": "reply", "re": msg.get("id"), "ok": True,
                       "result": print_config(resolve_script(root, rel))})
                continue
            if t == "start":
                if rel not in scripts:
                    scripts[rel] = Script(resolve_script(root, rel), int(msg.get("port", 9000)),
                                          on_change=lambda s, r=rel: changed(s, r),
                                          on_log=lambda text, r=rel: _emit({"type": "log", "file": r, "line": text}))
                await scripts[rel].start()
            elif t == "stop" and rel in scripts:
                await scripts.pop(rel).stop()
            elif t == "restart" and rel in scripts:
                await scripts[rel].restart()
            elif t == "control" and rel in scripts:
                await scripts[rel].control(str(msg.get("id")), msg.get("value"))
            elif t not in ("stop", "restart", "control"):
                raise ScriptError(f"unknown type {t!r}")
            _emit({"type": "reply", "re": msg.get("id"), "ok": True})
        except (ValueError, ScriptError, AttributeError) as e:
            _emit({"type": "reply", "re": msg.get("id") if isinstance(msg, dict) else None, "ok": False,
                   "message": str(e)})
    for s in scripts.values():
        await s.stop()
    return 0


async def _run(script: pathlib.Path, port: int) -> int:
    s = Script(script, port, on_change=lambda s: print(f"[{s.state}] restarts={s.restarts}", file=sys.stderr),
               on_log=print)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await s.start()
    await stop.wait()
    await s.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wsrun.py", description="Wirescape script runner (0025 §4.5).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("print-config")
    pc.add_argument("script", type=pathlib.Path)
    rn = sub.add_parser("run")
    rn.add_argument("script", type=pathlib.Path)
    rn.add_argument("--port", type=int, default=None)
    sv = sub.add_parser("serve")
    sv.add_argument("--root", type=pathlib.Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "print-config":
            _emit(print_config(a.script))
            return 0
        if a.cmd == "run":
            port = a.port if a.port is not None else print_config(a.script).get("port", 9000)
            return asyncio.run(_run(a.script.resolve(), port))
        return asyncio.run(_serve(a.root))
    except ScriptError as e:
        print(f"wsrun: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
