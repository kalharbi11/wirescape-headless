# SPDX-License-Identifier: GPL-3.0-only
"""The Player core (lab proposals/0025 §2.2–§2.5).

It owns the state document, the live values, the switch arbiter and the engine supervisor,
and it answers Player API commands. It is transport-free: `player/server.py` serves it over
HTTP and SSE. The engine is reached only through an adapter (player/engine.py).

H-1 built the API surface, the state document, composition and the arbiter. H-3 adds the
Program Change debounce, state files and atomic saves (player/state.py), and drains a pending
switch after a refused load. The full §2.2–§2.4 tests are tests/test_core.py.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import pathlib
import time
from typing import Any, Callable

from . import API_VERSION, VERSION, bundle as B, state as S, taper
from .catalogue import Catalogue
from .check import check as check_bundle, ERROR, WARNING
from .engine import AdapterFactory

RESTART_INITIAL = 0.25
RESTART_MAX = 30.0
HEALTHY_RESET = 30.0
HANG_GAP = 1.0
HELLO_TIMEOUT = 10.0
VALUES_HZ = 30
STATUS_HZ = 4
QUEUE_MAX = 256
SAVE_DELAY = 2.0  # values save 2 s after the last change (0025 §2.3)
DEBOUNCE_MS = 150  # Program Change and controller switches (0025 §2.4)
log = logging.getLogger("player")
NO_BUNDLE = "no bundle installed: the engine runs with no patch"


class CommandError(Exception):
    def __init__(self, code: str, message: str, engine_code: str | None = None):
        super().__init__(message)
        self.code, self.message, self.engine_code = code, message, engine_code


class Subscriber:
    """One event-stream client. Bounded; a client that cannot keep up loses its stream."""

    def __init__(self, controller: bool):
        self.controller = controller
        self.queue: asyncio.Queue = asyncio.Queue(QUEUE_MAX)
        self.closed = False

    def put(self, event: str, data: dict) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait((event, data))
        except asyncio.QueueFull:
            self.closed = True
            self.queue = asyncio.Queue(1)
            self.queue.put_nowait(None)


class PlayerCore:
    def __init__(self, bundles: dict[str, B.Bundle], adapter_factory: AdapterFactory, *,
                 fake: bool = False, clock: Callable[[], float] = time.monotonic, control_port: int = 0,
                 store: S.StateStore | None = None, initial: dict | None = None):
        self.bundles = bundles
        self.factory = adapter_factory
        self.fake = fake
        self.clock = clock
        self.started_at = clock()
        self.rev = 0
        # No bundle installed: the engine runs with no patch and the state says so (0025 §2.3).
        self.bundle = next(iter(bundles.values())) if bundles else B.Bundle(
            pathlib.Path("."), "", "", {"format": B.FORMAT, "version": B.VERSION, "setlist": []}, False)
        self.catalogue: Catalogue | None = None
        self.engine = None
        self.engine_info: dict = {"state": "stopped", "restarts": 0, "lastExit": None, "audio": None,
                                  "capabilities": []}
        self.midi_devices: list[dict] = []
        self.osc_status: dict = {}
        self.current = {"index": None, "switching": False, "pending": None, "error": None}
        self.patch: dict | None = None  # the loaded entry's patch document (from disk)
        self.values: dict[int, dict[str, float]] = {}  # entry index -> live values (0025 §2.4)
        self.warnings: list[str] = []
        self.subscribers: set[Subscriber] = set()
        self._dirty_values: dict[str, dict] = {}
        self._status_dirty = False
        self._tasks: list[asyncio.Task] = []
        self._restart_delay = RESTART_INITIAL
        self._healthy_since: float | None = None
        self._last_status: float | None = None
        self._restart_handle: asyncio.TimerHandle | None = None
        self._stopping = False
        self._immediate_restart = False
        self._inflight: int | None = None
        self._check = {}
        self.control_port = control_port
        self.store = store
        self.initial = initial
        self._save_handle: asyncio.TimerHandle | None = None
        self._good_saved = False
        self._boot_target: int | None = None
        self._killed = None  # the engine the watchdog killed (kill once per engine)
        self._debounce: asyncio.TimerHandle | None = None
        self._debounce_target: int | None = None
        self._pc_ignored: dict[int, int] = {}
        self._recheck()

    # ================================================================ lifecycle

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._ticker()), loop.create_task(self._watchdog())]
        first = 0
        init = self.initial
        if init and init.get("bundle") in self.bundles:
            self.bundle = self.bundles[init["bundle"]]
            self._recheck()
            self.values = {i: v for i, v in S.values_of(init).items() if i < len(self.bundle.entries)}
            if isinstance(init.get("index"), int) and init["index"] < len(self.bundle.entries):
                first = init["index"]
        self._boot_target = first if self.bundle.entries else None
        await self._start_engine()

    async def close(self) -> None:
        self._stopping = True
        if self._restart_handle:
            self._restart_handle.cancel()
        if self._debounce:
            self._debounce.cancel()
            self._debounce = None
        self.save_now()
        for t in self._tasks:
            t.cancel()
        if self.engine:
            await self.engine.stop()
        for s in list(self.subscribers):
            s.put("end", {})

    async def _start_engine(self) -> None:
        self.engine_info["state"] = "starting" if self.engine_info["restarts"] == 0 else "restarting"
        self._changed()
        eng = self.factory()
        eng.on_push = self._on_push
        eng.on_exit = lambda code, sig, e=eng: self._on_exit(e, code, sig)
        self.engine = eng
        try:
            hello = await asyncio.wait_for(eng.start(), HELLO_TIMEOUT)
        except Exception:  # noqa: BLE001 - a failed start is a crash (0025 §2.2)
            self._on_exit(eng, None, "start-failed")
            try:
                await eng.kill()
            except Exception:  # noqa: BLE001
                pass
            return
        if eng is not self.engine:
            return
        self.catalogue = Catalogue(hello.get("catalogue", {}))
        self.engine_info.update(state="running", capabilities=list(hello.get("capabilities", [])),
                                audio=hello.get("audio"))
        self.midi_devices = (hello.get("midi") or {}).get("devices", [])
        now = self.clock()
        self._last_status = now
        self._healthy_since = now
        self._changed()
        # 0025 §2.2: hello -> controllerStream (when advertised, P1-e) -> loadGraph(composed).
        if "controllerStream" in self.engine_info["capabilities"]:
            await self._engine_request({"type": "controllerStream", "kinds": ["cc", "note", "osc", "pc"]})
        if self.current["index"] is not None:
            await self._load(self.current["index"], reason="restart")
        elif self._boot_target is not None:
            try:
                await self.select(self._boot_target)
            except CommandError as e:
                log.warning("boot load of entry %s failed: %s", self._boot_target, e.message)

    def _on_exit(self, eng, code, signal) -> None:
        if eng is not self.engine:
            return
        self.engine = None
        self.engine_info["lastExit"] = {"code": code, "signal": signal, "at": round(self.clock() - self.started_at, 3)}
        self._last_status = None
        self._healthy_since = None
        if self._stopping:
            self.engine_info["state"] = "stopped"
            self._changed()
            return
        self.engine_info["restarts"] += 1
        self.engine_info["state"] = "restarting"
        self._changed()
        if self._immediate_restart:
            self._immediate_restart = False
            self._schedule_restart(0.0)
            return
        delay = self._restart_delay
        self._restart_delay = min(RESTART_MAX, self._restart_delay * 2)
        self._schedule_restart(delay)

    def _schedule_restart(self, delay: float) -> None:
        loop = asyncio.get_running_loop()
        if self._restart_handle:
            self._restart_handle.cancel()
        self._restart_handle = loop.call_later(delay, lambda: loop.create_task(self._start_engine()))

    def _on_push(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "status":
            now = self.clock()
            self._last_status = now
            if self._healthy_since is not None and now - self._healthy_since >= HEALTHY_RESET:
                self._restart_delay = RESTART_INITIAL
            st = msg.get("status", {})
            self.engine_info["audio"] = st.get("audio")
            if st.get("midi"):
                self.midi_devices = st["midi"].get("devices", self.midi_devices)
            self.osc_status = st.get("osc") or {}
            if self.engine_info["state"] == "stalled":
                self.engine_info["state"] = "running"
            self._status_dirty = True
        elif t == "devices":
            self.midi_devices = msg.get("midiDevices", self.midi_devices)
            self._changed()
        elif t == "controller":
            self.controller_events(msg.get("events", []))

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if self.engine is None or self._last_status is None:
                continue
            if self.clock() - self._last_status > HANG_GAP and self._killed is not self.engine:
                self.engine_info["state"] = "stalled"
                self._changed()
                eng = self._killed = self.engine
                await eng.kill()

    async def _ticker(self) -> None:
        """Coalesces values (≤30 Hz) and status (≤4 Hz) events."""
        n = 0
        period = 1.0 / VALUES_HZ
        every = max(1, round(VALUES_HZ / STATUS_HZ))
        while True:
            await asyncio.sleep(period)
            n += 1
            if self._dirty_values:
                vals, self._dirty_values = self._dirty_values, {}
                self._broadcast("values", {"rev": self.rev, "values": vals})
            if n % every == 0 and self._status_dirty:
                self._status_dirty = False
                self._broadcast("status", self.status_doc())

    # ================================================================ events

    def subscribe(self, controller: bool = False) -> Subscriber:
        s = Subscriber(controller)
        s.put("state", self.state_doc())
        self.subscribers.add(s)
        return s

    def unsubscribe(self, s: Subscriber) -> None:
        self.subscribers.discard(s)

    def _broadcast(self, event: str, data: dict) -> None:
        for s in list(self.subscribers):
            if event == "controller" and not s.controller:
                continue
            s.put(event, data)
            if s.closed:
                self.subscribers.discard(s)

    def _changed(self) -> None:
        self.rev += 1
        self._broadcast("state", self.state_doc())

    def controller_events(self, events: list[dict]) -> None:
        """Raw controller observations (0025 §3.2). The hardware map (H-7) consumes them too."""
        if events:
            self._broadcast("controller", {"events": events})

    # ================================================================ state document

    def state_doc(self) -> dict:
        e = self._entry()
        return {
            "api": API_VERSION, "rev": self.rev,
            "player": {"version": VERSION, "uptimeS": round(self.clock() - self.started_at, 3), "fake": self.fake},
            "engine": copy.deepcopy(self.engine_info),
            "bundle": {"name": self.bundle.name, "title": self.bundle.title, "check": dict(self._check)},
            "setlist": [{"index": x.index, "title": x.title, "patch": x.patch, "program": x.program}
                        for x in self.bundle.entries],
            "current": dict(self.current),
            "pages": [{"title": p.get("title", ""), "controls": list(p.get("controls", []))}
                      for p in self.bundle.global_pages + (e.pages if e else [])],
            "controls": {c["id"]: self._control_doc(c) for c in self._controls()},
            "scripts": [{"file": s["file"], "state": "stopped", "restarts": 0, "controls": []}
                        for s in (e.scripts if e else [])],
            "midi": {"devices": copy.deepcopy(self.midi_devices)},
            "osc": {"controlPort": self.control_port, "routes": copy.deepcopy(self.osc_status.get("routes", []))},
            "warnings": ([NO_BUNDLE] if not self.bundles else []) + list(self.warnings) + [
                f"Program Change {n} has no setlist entry (ignored {k}x)" for n, k in sorted(self._pc_ignored.items())],
        }

    def status_doc(self) -> dict:
        return {"rev": self.rev,
                "engine": {k: copy.deepcopy(self.engine_info[k]) for k in ("state", "restarts", "lastExit", "audio")},
                "scripts": [], "osc": {"controlPort": self.control_port,
                                       "routes": copy.deepcopy(self.osc_status.get("routes", []))}}

    def _entry(self) -> B.Entry | None:
        i = self.current["index"]
        return self.bundle.entries[i] if i is not None and i < len(self.bundle.entries) else None

    def _controls(self) -> list[dict]:
        e = self._entry()
        return [c for c in self.bundle.global_controls if isinstance(c, dict)] + (e.controls if e else [])

    def _control_doc(self, c: dict) -> dict:
        t = c.get("target", {})
        form = B.target_form(t)
        r = self._resolve(t) if form else None
        doc = {"label": c.get("label") or self._label(t, r), "kind": form or "invalid", "target": copy.deepcopy(t),
               "min": 0, "max": 1, "step": 0, "unit": "", "taper": "linear", "choices": None,
               "value": None, "norm": None, "display": "", "resolved": r is not None}
        if r is None:
            return doc
        meta, key, value = r["meta"], r["key"], self._current_value(r)
        doc.update(min=meta["minimum"], max=meta["maximum"], step=meta.get("step", 0), unit=meta.get("unit", ""),
                   taper=meta.get("taper", "linear"), choices=meta.get("choices"), value=value,
                   norm=taper.value_to_norm(meta, value) if value is not None else None,
                   display=taper.display(meta, value) if value is not None else "")
        doc["key"] = key
        return doc

    def _label(self, t: dict, r: dict | None) -> str:
        if r and r.get("module") is not None and self.patch:
            m = B.find_module(self.patch, r["module"])
            name = (self.catalogue.module(m["module"]) or {}).get("name", m["module"]) if (m and self.catalogue) else "?"
            pname = r["meta"].get("name", r.get("param", ""))
            if r["form"] == "modAmount":
                return f"{name} {r['module']} · {pname} amount"
            return f"{name} {r['module']} · {pname}"
        if B.target_form(t) == "script":
            return t["script"]["control"]
        return "unresolved"

    # ================================================================ resolution and values

    def _resolve(self, target: dict) -> dict | None:
        """{form, key, meta, module, param, cable} for a target in the loaded patch, else None."""
        form = B.target_form(target)
        if form is None or self.patch is None:
            return None
        if form in ("macro", "param"):
            mp = B.resolve_param(self.patch, target)
            if mp is None:
                return None
            m = B.find_module(self.patch, mp[0])
            meta = self.catalogue.param(m["module"], mp[1]) if self.catalogue else None
            if meta is None:
                return None
            return {"form": form, "key": f"param:{mp[0]}:{mp[1]}", "meta": meta, "module": mp[0], "param": mp[1]}
        if form == "modAmount":
            v = target["modAmount"]
            cable = B.find_mod_cable(self.patch, v["from"], v["to"])
            if cable is None or B.is_mapping_cable(self.patch, cable):
                return None
            m = B.find_module(self.patch, v["to"]["module"])
            pmeta = (self.catalogue.param(m["module"], v["to"]["param"]) if self.catalogue and m else None) or {}
            meta = {"name": pmeta.get("name", v["to"]["param"]), "minimum": -1, "maximum": 1, "default": 1,
                    "step": 0, "unit": "", "taper": "linear", "decimals": 2}
            key = f"mod:{v['from']['module']}:{v['from']['port']}>{v['to']['module']}:{v['to']['param']}"
            return {"form": form, "key": key, "meta": meta, "module": v["to"]["module"], "param": v["to"]["param"],
                    "cable": cable}
        if form == "script":
            v = target["script"]
            e = self._entry()
            running = any(s.get("file") == v["file"] for s in (e.scripts if e else []))
            if not running:
                return None
            meta = {"name": v["control"], "minimum": 0, "maximum": 1, "default": 0, "step": 0, "unit": "",
                    "taper": "linear", "decimals": 2}
            return {"form": form, "key": f"script:{v['file']}:{v['control']}", "meta": meta, "module": None}
        return None

    def _patch_value(self, r: dict) -> float | None:
        if r["form"] in ("macro", "param"):
            m = B.find_module(self.patch, r["module"])
            v = (m.get("parameters") or {}).get(r["param"])
            return v if isinstance(v, (int, float)) else r["meta"].get("default")
        if r["form"] == "modAmount":
            return r["cable"].get("amount", 1)
        return r["meta"].get("default")

    def _current_value(self, r: dict) -> float | None:
        live = self.values.get(self.current["index"], {})
        return live.get(r["key"], self._patch_value(r))

    def compose(self, index: int) -> dict:
        """The patch document with live values written in (0025 §2.4 "Composition").

        The file on disk is never touched; the copy is what `loadGraph` receives.
        """
        e = self.bundle.entries[index]
        doc = copy.deepcopy(self.bundle.load_patch(e))
        for key, v in self.values.get(index, {}).items():
            kind, _, rest = key.partition(":")
            if kind == "param":
                mid, _, pid = rest.partition(":")
                m = B.find_module(doc, int(mid))
                if m is not None:
                    m.setdefault("parameters", {})[pid] = v
            elif kind == "mod":
                src, _, dst = rest.partition(">")
                fm, _, fp = src.partition(":")
                tm, _, tp = dst.partition(":")
                c = B.find_mod_cable(doc, {"module": int(fm), "port": fp}, {"module": int(tm), "param": tp})
                if c is not None:
                    c["amount"] = v
        return doc

    # ================================================================ switching

    async def select(self, index: int) -> dict:
        """Through the arbiter: one loadGraph in flight, a single pending target (0025 §2.4)."""
        if not 0 <= index < len(self.bundle.entries):
            raise CommandError("not-found", f"no setlist entry {index}")
        if self.current["switching"]:
            self.current["pending"] = index
            self._changed()
            return {"index": index, "queued": True}
        target: int | None = index
        err: CommandError | None = None
        while target is not None:
            try:
                await self._load(target, reason="select")
                err = None
            except CommandError as ce:
                err = ce  # a refusal keeps the previous patch; a pending target still runs
            nxt, self.current["pending"] = self.current["pending"], None
            target = nxt if nxt is not None and nxt != self.current["index"] else None
        if err is not None:
            raise err
        return {"index": self.current["index"]}

    def _requested_index(self) -> int:
        if self.current["pending"] is not None:
            return self.current["pending"]
        if self._inflight is not None:
            return self._inflight
        return self.current["index"] if self.current["index"] is not None else -1

    async def step(self, delta: int) -> dict:
        """`next` / `prev` count from the latest requested index (wrapping)."""
        n = len(self.bundle.entries)
        if n == 0:
            raise CommandError("not-found", "the setlist is empty")
        base = self._requested_index()
        return await self.select((base + delta) % n if base >= 0 else 0)

    async def _load(self, index: int, reason: str) -> None:
        e = self.bundle.entries[index]
        if reason == "select" and e.recall == "patch":
            self.values.pop(index, None)
        try:
            doc = self.compose(index)
        except (OSError, ValueError) as ex:
            self.current["error"] = f"{e.patch}: {ex}"
            self._changed()
            raise CommandError("refused", self.current["error"]) from None
        self.current["switching"] = True
        self._inflight = index
        self._changed()
        try:
            reply = await self._engine_request({"type": "loadGraph", "patch": doc})
        except CommandError as ce:
            self._inflight = None
            self.current["switching"] = False
            self.current["error"] = ce.message
            self._changed()
            raise
        self.current["switching"] = False
        self._inflight = None
        if reply.get("ok"):
            self.current.update(index=index, error=None)
            self._boot_target = None
            self.patch = self.bundle.load_patch(e)
            self._refresh_warnings()
            self.save_now()  # every switch saves (0025 §2.3)
            if not self._good_saved and self.store:
                self._good_saved = True
                self._try(self.store.save_good, self._state_file_doc())
        else:
            # A refused loadGraph keeps the previous patch (the engine leaves its graph untouched).
            self.current["error"] = f"{reply.get('code')}: {reply.get('message')}"
        self._changed()
        if not reply.get("ok"):
            raise CommandError("engine", reply.get("message", "refused"), reply.get("code"))

    # ================================================================ saves (0025 §2.3)

    def _state_file_doc(self) -> dict:
        return S.state_doc(self.bundle.name, self.current["index"], self.values)

    def _try(self, fn, *a) -> None:
        try:
            fn(*a)
        except (OSError, ValueError, TypeError) as e:
            log.error("state save failed: %s", e)

    def _save_later(self) -> None:
        if not self.store:
            return
        if self._save_handle:
            self._save_handle.cancel()
        self._save_handle = asyncio.get_running_loop().call_later(SAVE_DELAY, self.save_now)

    def save_now(self) -> None:
        if self._save_handle:
            self._save_handle.cancel()
            self._save_handle = None
        if self.store and self.current["index"] is not None:
            self._try(self.store.save, self._state_file_doc())

    # ================================================================ Program Change and debounce (0025 §2.4)

    def debounce_ms(self) -> int:
        pc = self.bundle.config.get("programChange")
        v = pc.get("debounceMs", DEBOUNCE_MS) if isinstance(pc, dict) else DEBOUNCE_MS
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1000 else DEBOUNCE_MS

    def program_change(self, program: int) -> None:
        """PC n selects the entry with `program` n, else index n (0025 §2.7), after the debounce."""
        index = self.bundle.program_map().get(program)
        if index is None:
            self._pc_ignored[program] = self._pc_ignored.get(program, 0) + 1
            self._changed()
            return
        self.debounced_select(index)

    def debounced_select(self, index: int) -> None:
        """Each event restarts the timer; when it fires, the last target wins and goes to the arbiter."""
        if not 0 <= index < len(self.bundle.entries):
            return
        self._debounce_target = index
        if self._debounce:
            self._debounce.cancel()
        loop = asyncio.get_running_loop()
        self._debounce = loop.call_later(self.debounce_ms() / 1000, self._fire_debounce)

    def debounced_step(self, delta: int) -> None:
        n = len(self.bundle.entries)
        if n == 0:
            return
        base = self._debounce_target if self._debounce is not None else self._requested_index()
        self.debounced_select((base + delta) % n if base is not None and base >= 0 else 0)

    def _fire_debounce(self) -> None:
        self._debounce = None
        target, self._debounce_target = self._debounce_target, None
        if target is None or self._stopping:
            return

        async def go():
            try:
                await self.select(target)
            except CommandError as e:
                log.warning("debounced switch to %s failed: %s", target, e.message)

        asyncio.get_running_loop().create_task(go())

    def _refresh_warnings(self) -> None:
        self.warnings = [f"control {c['id']}: target is not in the loaded patch" for c in self._controls()
                         if B.target_form(c.get("target")) and self._resolve(c["target"]) is None]

    # ================================================================ commands

    async def command(self, cmd: Any) -> dict:
        if not isinstance(cmd, dict) or not isinstance(cmd.get("type"), str):
            raise CommandError("invalid", "a command is an object with a string type")
        t = cmd["type"]
        handler = COMMANDS.get(t)
        if handler is None:
            raise CommandError("invalid", f"unknown command type {t!r}")
        return await handler(self, cmd)

    async def _engine_request(self, msg: dict) -> dict:
        if self.engine is None or self.engine_info["state"] not in ("running", "stalled"):
            raise CommandError("unavailable", "the engine is not running")
        try:
            return await self.engine.request(msg)
        except ConnectionError as ex:
            raise CommandError("unavailable", str(ex)) from None

    async def _engine_ok(self, msg: dict) -> dict:
        reply = await self._engine_request(msg)
        if not reply.get("ok"):
            raise CommandError("engine", reply.get("message", "refused"), reply.get("code"))
        return reply.get("result") or {}

    def _target_of(self, cmd: dict) -> tuple[dict, str | None]:
        if "control" in cmd:
            for c in self._controls():
                if c.get("id") == cmd["control"]:
                    return c.get("target"), c["id"]
            raise CommandError("not-found", f"no control {cmd['control']!r}")
        if "target" in cmd:
            if B.target_form(cmd["target"]) is None:
                raise CommandError("invalid", "target must be one valid macro, param, modAmount or script target")
            return cmd["target"], None
        raise CommandError("invalid", "name a control or a target")

    async def cmd_set(self, cmd: dict) -> dict:
        target, cid = self._target_of(cmd)
        r = self._resolve(target)
        if r is None:
            raise CommandError("not-found", "the target is not in the loaded patch")
        meta = r["meta"]
        if "norm" in cmd:
            n = cmd["norm"]
            if not _finite(n):
                raise CommandError("invalid", "norm must be a number")
            value = taper.norm_to_value(meta, n)
        elif "value" in cmd:
            if not _finite(cmd["value"]):
                raise CommandError("invalid", "value must be a number")
            value = taper.quantize(meta, cmd["value"])
        else:
            raise CommandError("invalid", "give value or norm")
        await self._apply(r, value)
        return {"key": r["key"], "value": value, "norm": taper.value_to_norm(meta, value)}

    async def _apply(self, r: dict, value: float) -> None:
        if r["form"] in ("macro", "param"):
            await self._engine_ok({"type": "setParam", "moduleId": r["module"], "paramId": r["param"], "value": value})
        elif r["form"] == "modAmount":
            c = r["cable"]
            await self._engine_ok({"type": "setModAmount", "amount": value,
                                   "connection": {"kind": "modulation", "from": c["from"], "to": c["to"]}})
        # script values are stored here and delivered by the runner (H-11).
        self.values.setdefault(self.current["index"], {})[r["key"]] = value
        self._dirty_values[r["key"]] = {"value": value, "norm": taper.value_to_norm(r["meta"], value)}
        self._save_later()

    async def cmd_reset(self, cmd: dict) -> dict:
        live = self.values.setdefault(self.current["index"], {})
        if "control" not in cmd and "target" not in cmd:
            keys = list(live)
            rs = [r for r in (self._resolve(c["target"]) for c in self._controls() if B.target_form(c.get("target")))
                  if r]
            by_key = {r["key"]: r for r in rs}
            for k in keys:
                r = by_key.get(k) or self._resolve_key(k)
                live.pop(k, None)
                if r:
                    await self._apply(r, self._patch_value(r))
                    live.pop(k, None)
            return {"reset": keys}
        target, _ = self._target_of(cmd)
        r = self._resolve(target)
        if r is None:
            raise CommandError("not-found", "the target is not in the loaded patch")
        v = self._patch_value(r)
        await self._apply(r, v)
        live.pop(r["key"], None)
        return {"key": r["key"], "value": v}

    def _resolve_key(self, key: str) -> dict | None:
        kind, _, rest = key.partition(":")
        if kind == "param":
            mid, _, pid = rest.partition(":")
            return self._resolve({"param": {"module": int(mid), "param": pid}})
        if kind == "mod":
            src, _, dst = rest.partition(">")
            fm, _, fp = src.partition(":")
            tm, _, tp = dst.partition(":")
            return self._resolve({"modAmount": {"from": {"module": int(fm), "port": fp},
                                                "to": {"module": int(tm), "param": tp}}})
        return None

    async def cmd_params_list(self, cmd: dict) -> dict:
        if self.patch is None:
            return {"modules": [], "cables": []}
        owned = B.mapping_owned(self.patch)
        live = self.values.get(self.current["index"], {})
        mods = []
        for m in self.patch["modules"]:
            cm = self.catalogue.module(m["module"]) if self.catalogue else None
            params = []
            for p in (cm or {}).get("parameters", []):
                key = f"param:{m['id']}:{p['id']}"
                v = live.get(key, (m.get("parameters") or {}).get(p["id"], p["default"]))
                params.append({**p, "key": key, "value": v, "norm": taper.value_to_norm(p, v),
                               "mapped": (m["id"], p["id"]) in owned})
            mods.append({"id": m["id"], "module": m["module"], "name": (cm or {}).get("name", m["module"]),
                         "parameters": params})
        cables = []
        for c in self.patch["connections"]:
            if c.get("kind") != "modulation":
                continue
            key = f"mod:{c['from']['module']}:{c['from']['port']}>{c['to']['module']}:{c['to']['port']}"
            cables.append({"from": c["from"], "to": {"module": c["to"]["module"], "param": c["to"]["port"]},
                           "key": key, "amount": live.get(key, c.get("amount", 1)),
                           "mapping": B.is_mapping_cable(self.patch, c)})
        return {"modules": mods, "cables": cables}

    async def cmd_bundle_load(self, cmd: dict) -> dict:
        name = cmd.get("name")
        if name not in self.bundles:
            raise CommandError("not-found", f"no bundle {name!r}")
        if self.bundles[name] is not self.bundle:
            self.bundle = self.bundles[name]
            self.current.update(index=None, pending=None, error=None)
            self.values = {}
            self.patch = None
            self._recheck()
            self._changed()
        return await self.select(0) if self.bundle.entries else {"index": None}

    async def cmd_bundle_check(self, cmd: dict) -> dict:
        b = self.bundles.get(cmd.get("name", self.bundle.name))
        if b is None:
            raise CommandError("not-found", f"no bundle {cmd.get('name')!r}")
        findings = check_bundle(b, self.catalogue or Catalogue.load())
        return {"name": b.name, "findings": [f.__dict__ for f in findings]}

    def _recheck(self) -> None:
        if not self.bundles:
            self._check = {"ok": True, "errors": 0, "warnings": 0}
            return
        try:
            findings = check_bundle(self.bundle, self.catalogue or Catalogue.load())
        except OSError:
            findings = []
        self._check = {"ok": not any(f.level == ERROR for f in findings),
                       "errors": sum(f.level == ERROR for f in findings),
                       "warnings": sum(f.level == WARNING for f in findings)}

    async def cmd_engine_restart(self, cmd: dict) -> dict:
        """Counted as a restart, with no backoff (0025 §2.5)."""
        eng = self.engine
        if eng is not None:
            self._immediate_restart = True
            await eng.kill()
        else:
            self._schedule_restart(0.0)
        return {"restarts": self.engine_info["restarts"]}

    async def cmd_fake_inject(self, cmd: dict) -> dict:
        if not self.fake:
            raise CommandError("unavailable", "fake.inject exists only in the fake player")
        what = cmd.get("what")
        if what == "engineCrash":
            if self.engine is None:
                raise CommandError("unavailable", "the engine is not running")
            self.engine.crash()
        elif what == "engineStall":
            if self.engine is None:
                raise CommandError("unavailable", "the engine is not running")
            self.engine.stall()
        elif what == "scriptCrash":
            raise CommandError("unavailable", "scripts arrive with H-11")
        elif what == "controller":
            ev = cmd.get("event")
            if not isinstance(ev, dict) or not isinstance(ev.get("kind"), str):
                raise CommandError("invalid", "event must be one controller event object (0025 §3.2)")
            ev = {"t": int(self.clock() * 1e6), **ev}
            self.controller_events([ev])
        else:
            raise CommandError("invalid", "what must be engineCrash, engineStall, scriptCrash or controller")
        return {"injected": what}


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


async def _select(core, cmd):
    i = cmd.get("index")
    if not isinstance(i, int) or isinstance(i, bool):
        raise CommandError("invalid", "index must be an integer")
    return await core.select(i)


async def _passthrough(core, msg):
    return await core._engine_ok(msg)


async def _audio_select(core, cmd):
    if not isinstance(cmd.get("deviceId"), str):
        raise CommandError("invalid", "deviceId must be a string")
    return await _passthrough(core, {"type": "selectAudioDevice", "deviceId": cmd["deviceId"]})


async def _audio_buffer(core, cmd):
    return await _passthrough(core, {"type": "setBufferFrames", "frames": cmd.get("frames")})


async def _audio_rate(core, cmd):
    return await _passthrough(core, {"type": "setSampleRate", "hz": cmd.get("hz")})


async def _midi_enable(core, cmd):
    if not isinstance(cmd.get("deviceId"), str) or not isinstance(cmd.get("on"), bool):
        raise CommandError("invalid", "deviceId (string) and on (boolean) are required")
    r = await _passthrough(core, {"type": "setMidiEnabled", "deviceId": cmd["deviceId"], "on": cmd["on"]})
    for d in core.midi_devices:
        if d.get("id") == cmd["deviceId"]:
            d["enabled"] = cmd["on"]
    core._changed()
    return r


async def _unavailable(core, cmd):
    raise CommandError("unavailable", f"{cmd['type']} is not available in this Player version")


async def _config_get(core, cmd):
    return {"json": copy.deepcopy(core.bundle.config)}


async def _panic(core, cmd):
    return await _passthrough(core, {"type": "panic"})


COMMANDS: dict[str, Callable] = {
    "select": _select,
    "next": lambda c, cmd: c.step(1),
    "prev": lambda c, cmd: c.step(-1),
    "set": PlayerCore.cmd_set,
    "reset": PlayerCore.cmd_reset,
    "panic": _panic,
    "params.list": PlayerCore.cmd_params_list,
    "bundle.list": lambda c, cmd: _async({"bundles": [{"name": b.name, "title": b.title} for b in c.bundles.values()],
                                          "current": c.bundle.name}),
    "bundle.load": PlayerCore.cmd_bundle_load,
    "bundle.check": PlayerCore.cmd_bundle_check,
    "audio.devices": lambda c, cmd: _passthrough(c, {"type": "listAudioDevices"}),
    "audio.select": _audio_select,
    "audio.buffer": _audio_buffer,
    "audio.rate": _audio_rate,
    "midi.devices": lambda c, cmd: _passthrough(c, {"type": "listMidiDevices"}),
    "midi.enable": _midi_enable,
    "engine.restart": PlayerCore.cmd_engine_restart,
    "script.start": _unavailable,
    "script.stop": _unavailable,
    "script.restart": _unavailable,
    "config.get": _config_get,
    "config.put": _unavailable,
    "fake.inject": PlayerCore.cmd_fake_inject,
}


async def _async(v):
    return v
