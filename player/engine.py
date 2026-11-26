# SPDX-License-Identifier: GPL-3.0-only
"""The engine adapter interface the Player core talks to (lab proposals/0025 §2.1, §2.6).

Two adapters implement it: `FakeEngine` (player/fake_engine.py, H-1) and the real
`wirescape-engine` stdio NDJSON client (H-3/H-4). The core never knows which it has.
Messages are lab protocol v0 objects (`docs/specs/ENGINE_PROTOCOL.md` at LAB_PIN).
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol

PushHandler = Callable[[dict], None]
ExitHandler = Callable[[int | None, str | None], None]


class EngineAdapter(Protocol):
    """One engine process (or its stand-in). A new instance per engine session."""

    on_push: PushHandler | None
    on_exit: ExitHandler | None

    async def start(self) -> dict:
        """Start the engine and return its `hello` push. Raises on failure or timeout."""

    async def request(self, msg: dict) -> dict:
        """Send one command (`type` plus fields; the adapter adds `v` and `id`) and return the reply."""

    async def kill(self) -> None:
        """SIGKILL (or equivalent). `on_exit` fires once the process is gone."""

    async def stop(self) -> None:
        """Close stdin, wait 2 s, then kill (0025 §2.2 "Stop")."""


AdapterFactory = Callable[[], EngineAdapter]
Awaitable  # re-exported for type hints in adapters
