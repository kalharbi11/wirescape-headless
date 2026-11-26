#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Regenerate api/examples/ from the fake player (one request and reply per command family)."""
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from player import bundle as B  # noqa: E402
from player.core import PlayerCore  # noqa: E402
from player.fake_engine import FakeEngine  # noqa: E402
from player.server import ApiServer  # noqa: E402

CASES = [
    ("select", {"type": "select", "index": 5}),
    ("set-norm", {"type": "set", "control": "cutoff", "norm": 0.5}),
    ("set-mod-amount", {"type": "set", "control": "wob", "value": -0.25}),
    ("set-any-target", {"type": "set", "target": {"param": {"module": 6, "param": "mix"}}, "value": 0.5}),
    ("reset", {"type": "reset", "control": "cutoff"}),
    ("not-found", {"type": "select", "index": 99}),
    ("audio-devices", {"type": "audio.devices"}),
    ("bundle-list", {"type": "bundle.list"}),
]


async def main() -> None:
    b = B.load(ROOT / "examples" / "bundle")
    core = PlayerCore({b.name: b}, FakeEngine, fake=True, control_port=9100)
    server = ApiServer(core, port=0)
    await core.start()
    out = ROOT / "api" / "examples"
    out.mkdir(exist_ok=True)
    for name, cmd in CASES:
        reply = await server.run_command(cmd)
        (out / f"{name}.json").write_text(json.dumps({"SPDX-License-Identifier": "GPL-3.0-only", "request": cmd, "reply": reply}, indent=1) + "\n")
    state = {"SPDX-License-Identifier": "GPL-3.0-only", **core.state_doc()}
    state["player"]["uptimeS"] = 0.0
    state["engine"]["lastExit"] = None
    (out / "state.json").write_text(json.dumps(state, indent=1) + "\n")
    await core.close()


asyncio.run(main())
