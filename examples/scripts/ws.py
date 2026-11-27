# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Wirescape contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
"""ws: the Wirescape script helper (standard library only; copy it freely).

A script declares its outputs and controls, then calls `ws.start()`:

    import ws
    kick = ws.trig("Kick")                  # /ws/kick
    cut = ws.cv("Filter", 0, 1)             # /ws/filter
    lead = ws.voice("Lead", voices=4)       # /ws/lead_pitch/*, /ws/lead_gate/*, /ws/lead_vel/*
    density = ws.knob("Density", 0, 1, 0.5)
    ws.start()
    while True:
        kick.send()
        lead.on(1, 60, 0.8)
        ws.sleep(0.25)
        lead.off(1)

Modes, chosen by a flag on the script's command line:
- `--print-config`: `ws.start()` prints the declaration as one JSON document and exits 0.
  No socket is opened (Studio and the Player run this with a 5 s timeout).
- `--ws-runner`: run under the Wirescape runner. Controls arrive as NDJSON on stdin,
  `@ws declare` and `@ws heartbeat` lines go to stdout, and a `stop` message ends the script
  with every held gate sent 0.
- no flag: run on its own, sending to 127.0.0.1 and the declared port.

The destination is `WS_OSC_HOST` / `WS_OSC_PORT` when set (the runner sets both).
Sends are capped at 1000 messages/s; drops are counted. While a gate is held, `ws.sleep`
and every send re-send it every 500 ms, so a script that hangs loses its gates to the OSC In
row timeout instead of leaving notes stuck.

`python ws.py --zero-gates HOST PORT ADDRESS...` sends 0 to each address and exits. The
runner uses it after a script stops or crashes.
"""
from __future__ import annotations

import json
import os
import re
import socket
import struct
import sys
import threading
import time
from typing import Any

FORMAT = "wirescape.script"
VERSION = 1
SEND_CAP = 1000          # messages per second
HELD_RESEND = 0.5        # seconds
HEARTBEAT = 1.0          # seconds, at most
ROWS_PER_CONFIG = 8
CONTROL_TYPES = ("knob", "slider", "toggle", "button", "dropdown", "number", "text", "notes", "label")

_outputs: list["_Output"] = []
_controls: dict[str, "Control"] = {}
_state: dict[str, Any] = {"started": False, "mode": "standalone", "decl": None}
_lock = threading.Lock()


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "out"


# ============================================================================ OSC


def _pad(b: bytes) -> bytes:
    return b + b"\0" * (4 - len(b) % 4)


def osc_message(address: str, *values: float) -> bytes:
    tags = "," + "f" * len(values)
    return _pad(address.encode()) + _pad(tags.encode()) + b"".join(struct.pack(">f", float(v)) for v in values)


class _Sender:
    """UDP to the OSC In port, with the flood cap and held-gate re-send."""

    def __init__(self, host: str, port: int):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.window = time.monotonic()
        self.in_window = 0
        self.sent = 0
        self.drops = 0
        self.held: dict[str, float] = {}   # address -> last send time

    def send(self, address: str, *values: float, resend: bool = True) -> bool:
        now = time.monotonic()
        if now - self.window >= 1.0:
            self.window, self.in_window = now, 0
        if self.in_window >= SEND_CAP:
            self.drops += 1
            return False
        self.in_window += 1
        try:
            self.sock.sendto(osc_message(address, *values), self.addr)
        except OSError:
            self.drops += 1
            return False
        self.sent += 1
        if address in self.held:
            self.held[address] = now
        if resend:
            self.resend_held(now)
        return True

    def resend_held(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for a, t in list(self.held.items()):
            if now - t >= HELD_RESEND:
                self.held[a] = now
                self.send(a, 1, resend=False)

    def zero_held(self) -> None:
        for a in list(self.held):
            self.held.pop(a, None)
            self.send(a, 0, resend=False)


_sender: _Sender | None = None


def _send(address: str, *values: float) -> None:
    if _sender is not None:
        _sender.send(address, *values)
        _maybe_heartbeat()


def _hold(address: str, on: bool) -> None:
    if _sender is None:
        return
    if on:
        _sender.held[address] = time.monotonic()
    else:
        _sender.held.pop(address, None)


# ============================================================================ outputs


def _expand(address: str, channel: int | None) -> str:
    if "*" in address:
        if channel is None:
            raise ValueError(f"{address} has a wildcard: give a channel number")
        return address.replace("*", str(int(channel)))
    return address


class _Output:
    kind = ""

    def __init__(self, name: str, address: str | None, channels: int = 1):
        if _state["started"]:
            raise RuntimeError("declare outputs before ws.start()")
        self.name = name
        self.address = address or f"/ws/{slug(name)}"
        if not self.address.startswith("/"):
            raise ValueError("an OSC address starts with /")
        self.channels = channels
        _outputs.append(self)

    def declaration(self) -> dict:
        d = {"name": self.name, "address": self.address, "kind": self.kind}
        if "*" in self.address:
            d["channels"] = self.channels
        return d


class Trigger(_Output):
    kind = "trigger"

    def send(self, channel: int | None = None) -> None:
        _send(_expand(self.address, channel))

    on = send

    def off(self, channel: int | None = None) -> None:
        """A trigger has no off; kept so every output has .send, .on and .off."""


class Gate(_Output):
    kind = "gate"

    def send(self, value: float, channel: int | None = None) -> None:
        a = _expand(self.address, channel)
        _hold(a, bool(value))
        _send(a, 1 if value else 0)

    def on(self, channel: int | None = None) -> None:
        self.send(1, channel)

    def off(self, channel: int | None = None) -> None:
        self.send(0, channel)


class CV(_Output):
    kind = "cv"

    def __init__(self, name: str, out_min: float = 0, out_max: float = 1, address: str | None = None,
                 channels: int = 1):
        super().__init__(name, address, channels)
        self.out_min, self.out_max = out_min, out_max

    def send(self, value: float, channel: int | None = None) -> None:
        _send(_expand(self.address, channel), max(0.0, min(1.0, float(value))))

    on = send

    def off(self, channel: int | None = None) -> None:
        self.send(0, channel)

    def declaration(self) -> dict:
        return {**super().declaration(), "outMin": self.out_min, "outMax": self.out_max}


class Voice(_Output):
    kind = "voice"

    def __init__(self, name: str = "", voices: int = 1, velocity: bool = True, addresses: dict | None = None):
        base = slug(name) if name else "voice"
        self.addresses = {"pitch": f"/ws/{base}_pitch/*", "gate": f"/ws/{base}_gate/*"}
        if velocity:
            self.addresses["vel"] = f"/ws/{base}_vel/*"
        if addresses:
            self.addresses.update({k: v for k, v in addresses.items() if k in self.addresses})
        super().__init__(name or "Voice", self.addresses["pitch"], voices)
        self.voices, self.velocity = voices, velocity

    def _check(self, v: int) -> int:
        if not 1 <= int(v) <= self.voices:
            raise ValueError(f"voice must be 1..{self.voices}")
        return int(v)

    def send(self, voice: int, note: float) -> None:
        """Pitch only (a MIDI note number 0..127)."""
        _send(_expand(self.addresses["pitch"], self._check(voice)), note)

    def on(self, voice: int, note: float, vel: float = 1.0) -> None:
        v = self._check(voice)
        _send(_expand(self.addresses["pitch"], v), note)  # pitch first, so the gate opens on the note
        if self.velocity:
            _send(_expand(self.addresses["vel"], v), max(0.0, min(1.0, vel)))
        g = _expand(self.addresses["gate"], v)
        _hold(g, True)
        _send(g, 1)

    def off(self, voice: int) -> None:
        g = _expand(self.addresses["gate"], self._check(voice))
        _hold(g, False)
        _send(g, 0)

    def declaration(self) -> dict:
        return {"name": self.name, "kind": "voice", "voices": self.voices, "velocity": self.velocity,
                "addresses": dict(self.addresses)}


def trig(name: str, address: str | None = None, channels: int = 1) -> Trigger:
    return Trigger(name, address, channels)


def gate(name: str, address: str | None = None, channels: int = 1) -> Gate:
    return Gate(name, address, channels)


def cv(name: str, out_min: float = 0, out_max: float = 1, address: str | None = None, channels: int = 1) -> CV:
    return CV(name, out_min, out_max, address, channels)


def voice(name: str = "", voices: int = 1, velocity: bool = True, addresses: dict | None = None) -> Voice:
    return Voice(name, voices, velocity, addresses)


# ============================================================================ controls


class Control:
    """A declared control. `.value` is updated by the runner's stdin reader thread."""

    def __init__(self, type_: str, label: str, id: str | None = None, **fields: Any):
        if _state["started"]:
            raise RuntimeError("declare controls before ws.start()")
        if type_ not in CONTROL_TYPES:
            raise ValueError(f"control type must be one of {CONTROL_TYPES}")
        self.type, self.label = type_, label
        self.id = id or slug(label)
        if self.id in _controls:
            raise ValueError(f"duplicate control id {self.id!r}")
        self.fields = {k: v for k, v in fields.items() if v is not None}
        self.value = self.fields.get("default")
        _controls[self.id] = self

    def declaration(self) -> dict:
        return {"id": self.id, "type": self.type, "label": self.label, **self.fields}


def knob(label: str, lo: float = 0, hi: float = 1, default: float | None = None, id: str | None = None) -> Control:
    return Control("knob", label, id, min=lo, max=hi, default=lo if default is None else default)


def slider(label: str, lo: float = 0, hi: float = 1, default: float | None = None, id: str | None = None) -> Control:
    return Control("slider", label, id, min=lo, max=hi, default=lo if default is None else default)


def number(label: str, lo: float | None = None, hi: float | None = None, default: float = 0,
           step: float | None = None, id: str | None = None) -> Control:
    return Control("number", label, id, min=lo, max=hi, step=step, default=default)


def toggle(label: str, default: bool = False, id: str | None = None) -> Control:
    return Control("toggle", label, id, default=bool(default))


def button(label: str, id: str | None = None) -> Control:
    return Control("button", label, id, default=False)


def dropdown(label: str, choices: list[str], default: str | None = None, id: str | None = None) -> Control:
    if not choices:
        raise ValueError("a dropdown needs choices")
    return Control("dropdown", label, id, choices=list(choices), default=choices[0] if default is None else default)


def text(label: str, default: str = "", id: str | None = None) -> Control:
    return Control("text", label, id, default=default)


def notes(label: str, steps: int = 16, rows: int = 12, default: list | None = None, id: str | None = None) -> Control:
    return Control("notes", label, id, steps=steps, rows=rows, default=default or [])


def label(text_: str, id: str | None = None) -> Control:
    return Control("label", text_, id)


# ============================================================================ declaration


def _rows_for(o: _Output) -> list[dict]:
    def row(lbl, pattern, kind, imin=0, imax=1, omin=0, omax=1, smooth=0, timeout=0, stale="hold"):
        return {"label": lbl, "pattern": pattern, "argument": 0, "kind": kind, "input_min": imin,
                "input_max": imax, "output_min": omin, "output_max": omax, "smoothing_ms": smooth,
                "timeout_ms": timeout, "stale": stale}

    if isinstance(o, CV):
        return [row(o.name, o.address, "cv", 0, 1, o.out_min, o.out_max, smooth=5)]
    if isinstance(o, Trigger):
        return [row(o.name, o.address, "trigger")]
    if isinstance(o, Gate):
        return [row(o.name, o.address, "gate", timeout=2000, stale="zero")]
    if isinstance(o, Voice):
        rows = [row(f"{o.name} pitch", o.addresses["pitch"], "cv", 0, 127, -5, 5.583333),
                row(f"{o.name} gate", o.addresses["gate"], "gate", timeout=2000, stale="zero")]
        if o.velocity:
            rows.append(row(f"{o.name} vel", o.addresses["vel"], "cv"))
        return rows
    return []


def declaration(name: str | None = None, port: int = 9000) -> dict:
    rows = [r for o in _outputs for r in _rows_for(o)]
    chunks = [rows[i:i + ROWS_PER_CONFIG] for i in range(0, len(rows), ROWS_PER_CONFIG)]
    return {"format": FORMAT, "version": VERSION,
            "name": name or os.path.splitext(os.path.basename(sys.argv[0] or "script"))[0],
            "port": port,
            "outputs": [o.declaration() for o in _outputs],
            "controls": [c.declaration() for c in _controls.values()],
            "oscIn": [{"port": port, "rows": c} for c in chunks]}


def gate_addresses(decl: dict) -> list[str]:
    """Every concrete gate address in a declaration (wildcards expanded by channel count)."""
    out: list[str] = []
    for o in decl.get("outputs", []):
        if o.get("kind") == "gate":
            a, n = o["address"], o.get("channels", 1)
            out += [a.replace("*", str(i)) for i in range(1, n + 1)] if "*" in a else [a]
        elif o.get("kind") == "voice":
            a = o.get("addresses", {}).get("gate")
            if a:
                out += [a.replace("*", str(i)) for i in range(1, o.get("voices", 1) + 1)] if "*" in a else [a]
    return out


# ============================================================================ lifecycle


_stop = threading.Event()
_last_heartbeat = [0.0]


class Stopped(SystemExit):
    """Raised inside ws.sleep / ws.wait_until when the runner asks the script to stop."""


def _emit(kind: str, doc: dict) -> None:
    with _lock:
        sys.stdout.write(f"@ws {kind} {json.dumps(doc, separators=(',', ':'))}\n")
        sys.stdout.flush()


def _maybe_heartbeat() -> None:
    if _state["mode"] != "runner":
        return
    now = time.monotonic()
    if now - _last_heartbeat[0] >= HEARTBEAT:
        _last_heartbeat[0] = now
        _emit("heartbeat", {"sent": _sender.sent if _sender else 0, "drops": _sender.drops if _sender else 0})


def _set_control(cid: str, value: Any) -> None:
    c = _controls.get(cid)
    if c is not None:
        c.value = value


def _stdin_reader() -> None:
    # A daemon blocked in TextIOWrapper.readline holds the buffered stdin lock
    # during CPython shutdown. Use raw reads so a natural script exit cannot
    # abort the interpreter while the supervisor still owns the write end.
    fd = sys.stdin.fileno()
    pending = bytearray()
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                return
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending = bytearray(rest)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "control":
                    _set_control(str(msg.get("id")), msg.get("value"))
                elif msg.get("type") == "stop":
                    return
    except OSError:
        pass
    finally:
        _stop.set()  # stop, stdin EOF or pipe failure


def start(name: str | None = None, port: int = 9000) -> None:
    """End of the declarations. With --print-config, print them and exit 0."""
    global _sender
    if _state["started"]:
        return
    decl = declaration(name, port)
    _state["decl"] = decl
    argv = sys.argv[1:]
    if "--print-config" in argv:
        sys.stdout.write(json.dumps(decl) + "\n")
        sys.stdout.flush()
        os._exit(0)  # stop here: no socket, no script body
    _state["started"] = True
    host = os.environ.get("WS_OSC_HOST", "127.0.0.1")
    dest = int(os.environ.get("WS_OSC_PORT", port))
    _sender = _Sender(host, dest)
    if "--ws-runner" in argv:
        _state["mode"] = "runner"
        _emit("declare", decl)
        threading.Thread(target=_stdin_reader, name="ws-stdin", daemon=True).start()
        _last_heartbeat[0] = time.monotonic()
    import atexit
    atexit.register(_at_exit)


def _at_exit() -> None:
    if _sender is not None:
        _sender.zero_held()


def stopping() -> bool:
    return _stop.is_set()


def _check_stop() -> None:
    if _stop.is_set():
        if _sender is not None:
            _sender.zero_held()
        raise Stopped(0)


def wait_until(t: float) -> None:
    """Sleep until `time.perf_counter()` reaches t, re-sending held gates and heartbeats."""
    while True:
        _check_stop()
        if _sender is not None:
            _sender.resend_held()
        _maybe_heartbeat()
        left = t - time.perf_counter()
        if left <= 0:
            return
        _stop.wait(min(left, 0.1))


def sleep(s: float) -> None:
    wait_until(time.perf_counter() + max(0.0, s))


# ============================================================================ CLI


def _zero_gates(argv: list[str]) -> int:
    host, port, addrs = argv[0], int(argv[1]), argv[2:]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for a in addrs:
        sock.sendto(osc_message(a, 0), (host, port))
    sock.close()
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--zero-gates"] and len(sys.argv) >= 4:
        sys.exit(_zero_gates(sys.argv[2:]))
    print(__doc__)
    sys.exit(0 if not sys.argv[1:] else 2)

