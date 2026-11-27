#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Owner-only diagnostic runner for PG10; see docs/guides/SOAK.md."""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from player import run  # noqa: E402
from player.engine_proc import EngineProcess  # noqa: E402


def process_sample(pid):
    # /proc stat comm can contain spaces or parentheses; split after final ')'.
    stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2:].split()
    hz = os.sysconf("SC_CLK_TCK")
    return {"pid": pid, "start_ticks": int(fields[19]),
            "cpu_seconds": (int(fields[11]) + int(fields[12])) / hz,
            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=pathlib.Path, required=True)
    parser.add_argument("player_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    player_args = args.player_args
    if player_args[:1] == ["--"]:
        player_args = player_args[1:]
    if not player_args:
        parser.error("pass Player run arguments after --")
    if sys.platform != "linux":
        parser.error("Linux /proc required")
    # Never overwrite evidence. No implicit consent flags.
    with args.record.open("x", encoding="utf-8", buffering=1) as log:
        def record(kind, **fields):
            log.write(json.dumps({"kind": kind, "monotonic_ns": time.monotonic_ns(),
                                  **fields}, separators=(",", ":"), allow_nan=False) + "\n")

        class RecordingEngine(EngineProcess):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.last_sample = 0

            def _dispatch(self, msg):
                super()._dispatch(msg)
                kind = msg.get("type")
                if kind == "hello":
                    record("hello", pid=self.pid, session=msg.get("session"),
                           engine=msg.get("engine"), capabilities=msg.get("capabilities"))
                elif kind == "status" and msg.get("session") == self.session:
                    status = msg.get("status", {})
                    record("status", pid=self.pid, session=self.session, gen=msg.get("gen"),
                           audio=status.get("audio"), osc=status.get("osc"),
                           controller=status.get("controller"))
                    now = time.monotonic()
                    if now - self.last_sample >= 10:
                        self.last_sample = now
                        try:
                            record("process", player=process_sample(os.getpid()),
                                   engine=process_sample(self.pid))
                        except (OSError, ValueError, IndexError) as exc:
                            record("sample_error", error=type(exc).__name__)

        record("start", player_pid=os.getpid(), wall_time_ns=time.time_ns())
        original = run.EngineProcess
        run.EngineProcess = RecordingEngine
        try:
            return run.main(player_args)
        finally:
            run.EngineProcess = original
            record("stop", wall_time_ns=time.time_ns())


if __name__ == "__main__":
    sys.exit(main())
