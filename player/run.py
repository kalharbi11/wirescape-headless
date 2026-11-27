# SPDX-License-Identifier: GPL-3.0-only
"""`python -m player run` (lab proposals/0025 §2.1–§2.3): the Player with the real engine.

    python -m player run --state DIR --engine PATH [--bundle-root DIR] [--engine-arg ARG]… [--api-port N]

The engine always gets `--settings <state>/engine-settings.json` (absolute). Device consent
(`--confirm-audio`, `--confirm-midi`, `--confirm-lan`) is never a default: only the owner's
unit passes it with `--engine-arg`. On SIGTERM the Player saves state, stops the engine
(close stdin, 2 s, SIGKILL) and exits 0. Logs go to stderr.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import signal
import sys

from .boot import boot
from .core import PlayerCore
from .engine_proc import EngineProcess
from .server import DEFAULT_PORT, ApiServer
from .state import StateStore
from .notify import notify, watchdog


def engine_argv(state: pathlib.Path, extra: list[str]) -> list[str]:
    return [*extra, "--settings", str((state / "engine-settings.json").resolve())]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m player run", description="The Player with the real engine.")
    ap.add_argument("--state", type=pathlib.Path, required=True)
    ap.add_argument("--bundle-root", type=pathlib.Path, default=None, help="default: <state>/bundles")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--engine-arg", action="append", default=[])
    ap.add_argument("--api-port", type=int, default=DEFAULT_PORT)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")
    a.state.mkdir(parents=True, exist_ok=True)
    bundles, initial = boot(a.state, a.bundle_root)
    args = engine_argv(a.state, a.engine_arg)

    async def run() -> None:
        first = bundles.get((initial or {}).get("bundle")) or next(iter(bundles.values()), None)
        osc = first.config.get("osc") if first and isinstance(first.config.get("osc"), dict) else {}
        core = PlayerCore(bundles, lambda: EngineProcess(a.engine, args), store=StateStore(a.state),
                          initial=initial, control_port=osc.get("controlPort", 0) or 0)
        server = ApiServer(core, port=a.api_port)
        port = await server.start()
        # The API listens before the engine is up, so a broken engine never hides the fault (0025 §2.2).
        print(f"player: http://127.0.0.1:{port}/  (UI at /ui/)", flush=True)
        notify("READY=1")
        heartbeat = asyncio.create_task(watchdog())
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        starter = loop.create_task(core.start())
        await stop.wait()
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        starter.cancel()
        await core.close()
        await server.close()

    asyncio.run(run())
    return 0
