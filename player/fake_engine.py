# SPDX-License-Identifier: GPL-3.0-only
"""The fake engine adapter (lab proposals/0025 §2.6).

It accepts the engine commands the Player sends and checks them the way the engine does at
LAB_PIN (module types, graph caps, parameter IDs, modulation cables). It answers with
protocol v0 replies, sends `hello` with the committed catalogue snapshot and synthetic
`status` at 10 Hz, and takes `fake.inject` faults. A behaviour that differs from the real
engine is a defect in the fake (H-4 runs the same contract suite against both).
"""
from __future__ import annotations

import asyncio
import copy
import itertools
from typing import Any

from .catalogue import Catalogue

STATUS_HZ = 10
CAPABILITIES = ["midiLearn", "telemetry.playhead", "telemetry.monitor", "setSampleRate",
                "setBufferFrames", "osc", "osc.out", "applyGraph", "configDeferred"]
FAKE_AUDIO = {"id": "Fake|Null output", "name": "Null output", "kind": "audio", "sampleRates": [44100, 48000, 96000]}
FAKE_MIDI = {"id": "Fake MIDI 1|fake:midi:0", "name": "Fake MIDI 1", "kind": "midi", "enabled": False,
             "system_name": "fake:midi:0"}
_sessions = itertools.count(1)


class Refusal(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class FakeEngine:
    """One fake engine session. The Player creates a new one for every (re)start."""

    def __init__(self, catalogue: Catalogue | None = None, status_hz: float = STATUS_HZ):
        self.catalogue = catalogue or Catalogue.load()
        self.on_push = None
        self.on_exit = None
        self.session = f"fake{next(_sessions)}"
        self.gen = 0
        self.graph: dict | None = None
        self.audio = {"state": "running", "deviceId": FAKE_AUDIO["id"], "deviceName": FAKE_AUDIO["name"],
                      "sampleRate": 48000, "bufferFrames": 256, "latencyMs": 5.3333, "cpuPercent": 3.0, "dropouts": 0}
        self.midi_devices = [dict(FAKE_MIDI)]
        self.commands: list[dict] = []  # every command received, for tests
        self._status_period = 1.0 / status_hz
        self._task: asyncio.Task | None = None
        self._stalled = False
        self._alive = False

    # -- adapter interface -------------------------------------------------------------

    async def start(self) -> dict:
        self._alive = True
        self._task = asyncio.get_running_loop().create_task(self._status_loop())
        return {"v": 0, "session": self.session, "type": "hello", "protocol": 0,
                "engine": {"version": "fake", "sha": self.catalogue_sha},
                "capabilities": list(CAPABILITIES), "catalogue": copy.deepcopy(self.catalogue.doc),
                "audio": dict(self.audio), "midi": {"devices": copy.deepcopy(self.midi_devices), "activity": {}}}

    async def request(self, msg: dict) -> dict:
        if not self._alive:
            raise ConnectionError("engine is not running")
        self.commands.append(copy.deepcopy(msg))
        await asyncio.sleep(0)
        try:
            result = self._handle(msg)
        except Refusal as r:
            return {"v": 0, "session": self.session, "re": msg.get("id"), "ok": False, "gen": str(self.gen),
                    "code": r.code, "message": r.message}
        reply = {"v": 0, "session": self.session, "re": msg.get("id"), "ok": True, "gen": str(self.gen)}
        if result is not None:
            reply["result"] = result
        return reply

    async def kill(self) -> None:
        self._exit(None, "SIGKILL")

    async def stop(self) -> None:
        self._exit(0, None)

    # -- faults (fake.inject) -----------------------------------------------------------

    def crash(self) -> None:
        self._exit(139, "SIGSEGV")

    def stall(self) -> None:
        """Stop status pushes; the engine looks hung (0025 §2.2 "Hang")."""
        self._stalled = True

    @property
    def catalogue_sha(self) -> str:
        return "snapshot"

    # -- internals -----------------------------------------------------------------------

    def _exit(self, code: int | None, signal: str | None) -> None:
        if not self._alive:
            return
        self._alive = False
        if self._task:
            self._task.cancel()
        if self.on_exit:
            self.on_exit(code, signal)

    async def _status_loop(self) -> None:
        while self._alive:
            await asyncio.sleep(self._status_period)
            if self._alive and not self._stalled and self.on_push:
                self.on_push({"v": 0, "session": self.session, "type": "status", "gen": str(self.gen),
                              "status": {"audio": dict(self.audio),
                                         "midi": {"devices": copy.deepcopy(self.midi_devices), "activity": {}},
                                         "osc": self._osc_status()}})

    def _osc_status(self) -> dict:
        routes = []
        for m in (self.graph or {}).get("modules", []):
            if m.get("module") == "osc.in":
                port = (m.get("config") or {}).get("port", 9000)
                routes.append({"module": str(m["id"]), "port": port, "bind": "127.0.0.1",
                               "state": "listening", "received": 0, "dropped": 0})
        return {"enabled": bool(routes), "bind": "127.0.0.1", "port": routes[0]["port"] if routes else 0,
                "lan": False, "routes": routes}

    def _handle(self, msg: dict) -> Any:
        t = msg.get("type")
        if t == "loadGraph":
            patch = msg.get("patch")
            self._validate_patch(patch)
            self.graph = copy.deepcopy(patch)
            self.gen += 1
            return None
        if t == "setParam":
            m = self._module(msg.get("moduleId"))
            meta = self.catalogue.param(m["module"], msg.get("paramId"))
            if meta is None:
                raise Refusal("not-found", f"parameter {msg.get('paramId')!r} not found")
            v = msg.get("value")
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise Refusal("invalid", "value must be a number")
            m.setdefault("parameters", {})[msg["paramId"]] = v
            return None
        if t == "setModAmount":
            c = msg.get("connection") or {}
            a = msg.get("amount")
            if not isinstance(a, (int, float)) or not -1 <= a <= 1:
                raise Refusal("invalid", "amount must be in [-1, 1]")
            for cable in (self.graph or {}).get("connections", []):
                if (cable.get("kind") == c.get("kind") == "modulation" and cable.get("from") == c.get("from")
                        and cable.get("to") == c.get("to")):
                    cable["amount"] = a
                    return None
            raise Refusal("not-found", "connection not found")
        if t == "panic":
            return None
        if t == "listAudioDevices":
            return {"devices": [dict(FAKE_AUDIO)]}
        if t == "selectAudioDevice":
            if msg.get("deviceId") != FAKE_AUDIO["id"]:
                raise Refusal("not-found", "audio device not found")
            return None
        if t == "setBufferFrames":
            if msg.get("frames") not in (64, 128, 256, 512, 1024):
                raise Refusal("invalid", "frames must be 64, 128, 256, 512 or 1024")
            self.audio["bufferFrames"] = msg["frames"]
            return None
        if t == "setSampleRate":
            if msg.get("hz") not in (44100, 48000, 96000):
                raise Refusal("invalid", "hz must be 44100, 48000 or 96000")
            self.audio["sampleRate"] = msg["hz"]
            return None
        if t == "listMidiDevices":
            return {"devices": copy.deepcopy(self.midi_devices)}
        if t == "setMidiEnabled":
            for d in self.midi_devices:
                if d["id"] == msg.get("deviceId"):
                    d["enabled"] = bool(msg.get("on"))
                    return None
            raise Refusal("not-found", "MIDI device not found")
        raise Refusal("invalid", f"unknown command type {t!r}")

    def _module(self, module_id: Any) -> dict:
        for m in (self.graph or {}).get("modules", []):
            if m.get("id") == module_id:
                return m
        raise Refusal("not-found", f"module {module_id} not found")

    def _validate_patch(self, patch: Any) -> None:
        if not isinstance(patch, dict) or patch.get("format") != "wirescape.native.patch" or patch.get("version") != 2:
            raise Refusal("invalid", "not a wirescape.native.patch v2 document")
        mods, cons = patch.get("modules"), patch.get("connections")
        if not isinstance(mods, list) or not isinstance(cons, list):
            raise Refusal("invalid", "modules and connections must be lists")
        if len(mods) > 64 or len(cons) > 128:
            raise Refusal("limit", "Graph capacity exceeded")
        types = {}
        for m in mods:
            if m.get("module") not in self.catalogue:
                raise Refusal("unknown-module", f"unknown module {m.get('module')!r}")
            if m.get("id") in types:
                raise Refusal("duplicate", f"duplicate module id {m.get('id')}")
            types[m.get("id")] = m["module"]
        for c in cons:
            f, to = c.get("from") or {}, c.get("to") or {}
            if f.get("module") not in types or to.get("module") not in types:
                raise Refusal("not-found", "connection endpoint module not found")
            if c.get("kind") == "modulation":
                if self.catalogue.param(types[to["module"]], to.get("port")) is None:
                    raise Refusal("not-found", f"modulation target {to.get('port')!r} not found")
                a = c.get("amount", 1)
                if not isinstance(a, (int, float)) or not -1 <= a <= 1:
                    raise Refusal("invalid", "modulation amount must be in [-1, 1]")
