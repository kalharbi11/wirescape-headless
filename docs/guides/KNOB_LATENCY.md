<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Knob latency evidence (H-f1)

**Status: unmeasured.** [Lab #711](https://github.com/kalharbi11/wirescape-lab/issues/711)
tracks the missing test-only eight-controller workload. H-15's P1-e2 pin supports
the controller stream and the control port, not the complete latency workload.
Do not claim H-f1 pass from this collector's synthetic tests, a shorter diagnostic,
the current scripted source, a fake Player, or hosted arm64.

## Contract

Lab proposals/0025 §§2.8, 3.2: engine ingress **t** (integer microseconds of
Linux CLOCK_MONOTONIC) to the Player receiving the corresponding successful
setParam reply (Python time.monotonic_ns(), integer nanoseconds on the same host).
Added latency = (receipt_ns - 1000 * t) / 1,000,000 ms. Nearest-rank p99 budget
**10 ms**, aggregate **100 CC/s across eight continuous controllers**, **600 s**,
reference UI Play page visible throughout, **Pi 5**. No audio/MIDI device or LAN
consent, no H2. In-patch mappings are still the low-latency path.

The diagnostic runs the normal Player and its same mapping/request/dispatch
implementation, with test-only subclasses in the dedicated tool process.
An event object (not CC value or timestamp) identifies the mapping invocation;
the mapping task's request awaits the adapter's matching request ID (re) and
session. The receipt is stamped immediately before adapter reply dispatch
(after NDJSON decode, before waking the waiter). Other-task/UI commands are
not paired. No API change, HTTP round-trip approximation, second device
listener, engine modification or production instrumentation. The probe adds
some overhead; record that fact. Rows are buffered in memory (bounded at
120,000) and written atomically after shutdown. A missing, refused, ambiguous,
non-setParam or cross-session ACK is not a latency sample.

## Owner preparation

Use a clean checkout of headless and the exact LAB_PIN lab checkout.
Build the engine by following INSTALL_PI and the lab's pinned build instructions;
the tool checks the checkout SHAs and hashes the executable but cannot prove
that the executable was built from the checked-out source. The owner must
attest that build provenance. Use a dedicated test bundle exported from Studio:
one stable entry, no scripts or PC switching, eight distinct continuous raw
parameter targets, one jump hardware binding per scripted CC identity, no
in-patch mapping on those targets. Keep the patch unchanged. Use the actual
scripted workload's device ID/channel/CC numbers; do not invent the as-yet
unavailable #711 source. A binding has this form (substitute real IDs):
    
```json
{"source":{"midi":{"device":"SCRIPTED_DEVICE_ID","channel":1,"cc":1}},
 "control":"knob1","takeover":"jump"}
```

Check the targets and setlist against docs/PLAYER_JSON.md. On the Pi, stop the
regular Player and its UI service if they conflict with the diagnostic port.
Use a new scratch state, not the live user's state; use only a trusted,
device-off bundle. The diagnostic currently passes exactly --null-audio and
--scripted-midi (plus the normal settings/control-port options); if the future
lab workload uses different flags, update this helper in scope before claiming
qualification. No alternate-pin run substitutes for the actual pin.

```sh
# From the headless checkout; supply actual local paths.
LAB=/path/to/clean/wirescape-lab
ENGINE=/path/to/engine-built-at-LAB_PIN
BUNDLE=/path/to/validated-latency-bundle
STATE=$(mktemp -d)
OUT="$STATE/knob-latency.json"
git rev-parse HEAD
git -C "$LAB" rev-parse HEAD
cat LAB_PIN
python -m player check "$BUNDLE" --lab "$LAB"
python -m player install "$BUNDLE" --state "$STATE"
# GNU timeout: signal only the foreground Player, not its engine process group.
# 30 s warmup + 600 s window + 10 s for final status/drain.
timeout --foreground --preserve-status --signal=INT --kill-after=10s 640s \
  python -m tools.knob_latency --state "$STATE" --engine "$ENGINE" \
    --lab-checkout "$LAB" --output "$OUT" --warmup 30
```

During warmup open http://127.0.0.1:8770/ui/ on the Pi, select Play, and leave it
visible and untouched until the tool stops. Do not open extra controller SSE
observers or change entries. If startup/graph load or UI readiness misses warmup,
discard the run and repeat with a longer warmup and corresponding timeout.
Inspect the evidence after clean shutdown:

```sh
python - "$OUT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for k in ("provenance", "window", "summary", "engine_status", "last_status_ns",
          "sessions", "player_dropped", "collector_overflow", "player_exit",
          "qualification"):
    print(k, json.dumps(d[k], indent=2))
PY
```

## Check and report

Keep the full raw JSON, including all event fields, graph generation, session,
setParam command, reply ID and receipt timestamp. Record exact headless/lab
SHAs, binary SHA-256, machine/date, workload version and per-source counts,
UI visibility, graph/bundle identity, and all loss/invalid counters. The tool
never emits a qualification pass: its source deficit is relative to 60,000
expected CC ingress events, not proof of how many were coalesced versus never
emitted. The engine's cumulative fifo/latest/oversize drops and the Player
queue drop counter are separate (including warmup, conservatively); use final
status after the measurement window. Coalescing can be invisible to these
counters, hence verify the source workload independently.

Refuse qualification if window incomplete, source counts not verified,
anything missing/invalid/unmatched, collector overflow, any drops, multiple
sessions or graph generations, absent/stale final controller status, or
nonzero Player exit. Require eight distinct sources and the full workload;
the guide does not assert that the present scripted source meets it. Confirm
one corresponding setParam ACK for each event. Report p50/p95/p99/max only
for valid paired observations, never substitute for missing events.
A valid complete owner run with p99 >10 ms is a fail, not a reason to relax the
budget. Escalate the design consequence via the lab (0025 §2.8); don't change
production mapping here. Hosted arm64 diagnostics remain diagnostic only.

Result template (copy to lab facts/perf H-f1 with raw evidence location):

| Item | Value |
|---|---|
| Result | unmeasured / blocked / pass / fail |
| Headless SHA / lab SHA / binary SHA-256 | |
| Pi model / OS / date UTC | |
| Workload version, rate, eight identities, duration | |
| Bundle + patch revision; Play page visible | |
| Expected / observed / paired / unmatched / invalid / deficit / excess | |
| Engine drops / Player drops / collector overflow / sessions | |
| Clock, units, probe overhead note | CLOCK_MONOTONIC; us -> ns -> ms; instrumented diagnostic |
| p50 / p95 / p99 / max (ms) | |
| Raw report path/digest and owner signature | |

No H-f1 result is established by this repository change.
