# SPDX-License-Identifier: GPL-3.0-only
"""A stand-in engine *process* for the stdio adapter tests (lab protocol v0 framing).

It wraps `player.fake_engine.FakeEngine` behind NDJSON on stdin and stdout, the way the
real `wirescape-engine` speaks: `hello` first, one reply per command carrying `re`, `status`
pushes, and a clean exit 0 on stdin EOF. Test-only flags:
  --stderr-line TEXT   write TEXT to stderr once at start
  --no-hello           never send hello (a start timeout)
  --exit-on CMD        exit with code 3 when command type CMD arrives
Usage: python -I tests/stdio_engine.py [flags]
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from player.fake_engine import FakeEngine  # noqa: E402


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def main(argv: list[str]) -> int:
    no_hello = "--no-hello" in argv
    exit_on = argv[argv.index("--exit-on") + 1] if "--exit-on" in argv else None
    if "--stderr-line" in argv:
        print(argv[argv.index("--stderr-line") + 1], file=sys.stderr, flush=True)
    eng = FakeEngine(status_hz=20)
    eng.on_push = emit
    hello = await eng.start()
    if not no_hello:
        emit(hello)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            return 0  # stdin EOF: clean teardown, exit 0 (ENGINE_PROTOCOL §1)
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            emit({"v": 0, "session": eng.session, "re": None, "ok": False, "gen": str(eng.gen),
                  "code": "invalid", "message": "malformed line"})
            continue
        if exit_on and msg.get("type") == exit_on:
            os._exit(3)
        emit(await eng.request(msg))


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
