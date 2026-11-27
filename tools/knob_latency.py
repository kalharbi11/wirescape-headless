# SPDX-License-Identifier: GPL-3.0-only
"""H-16 device-off diagnostic. Run as python -m tools.knob_latency.
The production Player, including its mapping and request path, is unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import platform
import re
import subprocess
import time
from unittest.mock import patch

from player import run
from player.core import PlayerCore
from player.engine_proc import EngineProcess
from player.state import atomic_write_json

DURATION_S = 600
EXPECTED = 60_000
MAX_ROWS = 120_000
ACTIVE = ContextVar("knob_latency_event", default=None)
ROOT = Path(__file__).resolve().parents[1]


def validate_provenance(doc):
    for key, size in (("headless_sha", 40), ("lab_sha", 40), ("binary_sha256", 64)):
        if not isinstance(doc.get(key), str) or not re.fullmatch("[0-9a-f]{%d}" % size, doc[key]):
            raise ValueError("invalid " + key)
    for key, expected in (("platform", "Linux"), ("clock", "CLOCK_MONOTONIC"),
                          ("ingress_unit", "us"), ("receipt_unit", "ns")):
        if doc.get(key) != expected:
            raise ValueError("unsupported " + key)


def _uint(value):
    return type(value) is int and value >= 0


class Collector:
    def __init__(self, start_ns, duration_s=DURATION_S, expected=EXPECTED):
        self.start_ns = start_ns
        self.end_ns = start_ns + duration_s * 1_000_000_000
        self.expected = expected
        self.rows = []
        self._identity = {}
        self.engine_status = {}
        self.last_status_ns = {}
        self.sessions = set()
        self.player_dropped = 0
        self.overflow = 0

    def observe(self, msg):
        session = msg.get("session")
        if not isinstance(session, str) or not session:
            return
        self.sessions.add(session)
        if msg.get("type") == "status" and isinstance(msg.get("controller"), dict):
            self.engine_status[session] = msg["controller"]
            self.last_status_ns[session] = time.monotonic_ns()
        if msg.get("type") != "controller":
            return
        for event in msg.get("events", []):
            if not isinstance(event, dict) or event.get("kind") != "cc":
                continue
            t = event.get("t")
            if _uint(t) and not self.start_ns <= t * 1000 < self.end_ns:
                continue
            if len(self.rows) >= MAX_ROWS:
                self.overflow += 1
                continue
            # Retain the actual event object: duplicate timestamps/values are
            # not identity and an object's id cannot be reused during this run.
            row = {"event": event, "session": session, "gen": msg.get("gen"),
                   "mapped": False, "requests": []}
            self.rows.append(row)
            self._identity[id(event)] = row

    def row_for(self, event):
        return self._identity.get(id(event))


def summarize(rows, expected=EXPECTED):
    """Nearest-rank quantiles. No imputation of a missing or ambiguous ACK."""
    ids = Counter()
    for row in rows:
        for request in row["requests"]:
            reply = request.get("reply") or {}
            rid = reply.get("re")
            if isinstance(rid, str) and rid:
                ids[(row["session"], rid)] += 1
    latencies = []
    sources = Counter()
    unmatched = invalid = 0
    for row in rows:
        event = row["event"]
        source = (event.get("deviceId"), event.get("channel"), event.get("controller"))
        valid_source = (isinstance(source[0], str) and bool(source[0])
                        and _uint(source[1]) and 1 <= source[1] <= 16
                        and _uint(source[2]) and source[2] <= 127
                        and _uint(event.get("value")) and event["value"] <= 127)
        if valid_source:
            sources[source] += 1
        t = event.get("t")
        if not valid_source or not _uint(t):
            invalid += 1
            continue
        requests = row["requests"]
        if not requests:
            unmatched += 1
            continue
        if len(requests) != 1:
            invalid += 1
            continue
        req = requests[0]
        reply = req.get("reply") or {}
        ns, rid = req.get("receipt_ns"), reply.get("re")
        if (req.get("command", {}).get("type") != "setParam"
                or reply.get("ok") is not True or reply.get("session") != row["session"]
                or not isinstance(rid, str) or not rid or ids[(row["session"], rid)] != 1
                or not _uint(ns) or ns < t * 1000):
            invalid += 1
            continue
        latencies.append((ns - t * 1000) / 1_000_000)
    latencies.sort()

    def percentile(p):
        return latencies[math.ceil(len(latencies) * p) - 1] if latencies else None

    return {"expected": expected, "observed": len(rows), "paired": len(latencies),
            "source_deficit": max(0, expected - len(rows)),
            "source_excess": max(0, len(rows) - expected),
            "unmatched": unmatched, "invalid": invalid,
            "unhandled": sum(not r.get("mapped") and not r["requests"] for r in rows),
            "sources": [{"deviceId": k[0], "channel": k[1], "controller": k[2], "count": v}
                        for k, v in sorted(sources.items())],
            "p50_ms": percentile(.50), "p95_ms": percentile(.95),
            "p99_ms": percentile(.99), "max_ms": latencies[-1] if latencies else None}


class ObservedEngine(EngineProcess):
    """Stamp receipt at the adapter's dispatch boundary, before waking the waiter."""
    def __init__(self, path, args, collector):
        super().__init__(path, args)
        self.collector = collector
        self._receipts = {}

    def _dispatch(self, msg):
        now = time.monotonic_ns()
        if self.session is not None and msg.get("session") == self.session:
            if msg.get("type") in ("controller", "status"):
                self.collector.observe(msg)
            rid = msg.get("re")
            if "type" not in msg and isinstance(rid, str):
                future = self._pending.get(rid)
                if future is not None and not future.done():
                    self._receipts[rid] = now
        super()._dispatch(msg)

    async def request(self, msg):
        active = ACTIVE.get()
        row = active[0] if active and active[1] is asyncio.current_task() else None
        reply = None
        receipt = None
        try:
            reply = await super().request(msg)
            receipt = self._receipts.pop(reply.get("re"), None)
            return reply
        finally:
            if row is not None:
                row["requests"].append({"command": dict(msg), "reply": reply,
                                        "receipt_ns": receipt})


class ObservedCore(PlayerCore):
    def __init__(self, *args, collector, **kwargs):
        self.collector = collector
        super().__init__(*args, **kwargs)

    def controller_events(self, events):
        super().controller_events(events)
        self.collector.player_dropped = self._controller_dropped

    async def _map_controller(self, event):
        row = self.collector.row_for(event)
        if row is not None:
            row["mapped"] = True
        token = ACTIVE.set((row, asyncio.current_task()))
        try:
            return await super()._map_controller(event)
        finally:
            ACTIVE.reset(token)


def _git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def _revision(path):
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked checkout changes: " + str(path))
    return _git(path, "rev-parse", "HEAD")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="dedicated test state directory")
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--lab-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=30, help="seconds before fixed 600 s window")
    parser.add_argument("--api-port", type=int, default=8770)
    args = parser.parse_args(argv)
    if args.warmup < 1 or not 1024 <= args.api_port <= 65535:
        parser.error("invalid warmup or port")
    engine = args.engine.resolve(strict=True)
    pin = dict(line.split("=", 1) for line in (ROOT / "LAB_PIN").read_text().splitlines()
               if line and not line.startswith("#"))["commit"]
    clock = time.get_clock_info("monotonic")
    provenance = {"headless_sha": _revision(ROOT), "lab_sha": _revision(args.lab_checkout),
                  "binary_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
                  "platform": platform.system(), "machine": platform.machine(),
                  "clock": "CLOCK_MONOTONIC" if clock.monotonic and not clock.adjustable
                  and "CLOCK_MONOTONIC" in clock.implementation else clock.implementation,
                  "ingress_unit": "us", "receipt_unit": "ns",
                  "date_utc": datetime.now(timezone.utc).isoformat(),
                  "binary_source_attestation_required": True}
    validate_provenance(provenance)
    if provenance["lab_sha"] != pin:
        parser.error("lab checkout does not match LAB_PIN")
    if args.output.exists():
        parser.error("refusing to overwrite evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    collector = Collector(time.monotonic_ns() + args.warmup * 1_000_000_000)
    # Patch only this dedicated harness process. No production configuration or
    # mapping behavior changes; no independent engine connection or HTTP timing.
    print("Open the reference UI Play page during warmup; stop after the 600 s window.", flush=True)
    rc = 1
    try:
        with patch.object(run, "EngineProcess", lambda path, flags:
                          ObservedEngine(path, flags, collector)), patch.object(
                              run, "PlayerCore", lambda *a, **kw:
                              ObservedCore(*a, collector=collector, **kw)):
            rc = run.main(["--state", str(args.state.resolve()), "--engine", str(engine),
                           "--engine-arg=--null-audio", "--engine-arg=--scripted-midi",
                           "--api-port", str(args.api_port)])
    finally:
        stopped = time.monotonic_ns()
        report = {"format": "wirescape.knob-latency.v1", "provenance": provenance,
                  "window": {"start_ns": collector.start_ns, "end_ns": collector.end_ns,
                             "stopped_ns": stopped, "complete": stopped >= collector.end_ns},
                  "summary": summarize(collector.rows, collector.expected),
                  "engine_status": collector.engine_status,
                  "last_status_ns": collector.last_status_ns,
                  "sessions": sorted(collector.sessions),
                  "player_dropped": collector.player_dropped,
                  "collector_overflow": collector.overflow, "player_exit": rc,
                  "qualification": "unmeasured; requires owner Pi run and verified workload",
                  "rows": collector.rows}
        atomic_write_json(args.output, report)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
