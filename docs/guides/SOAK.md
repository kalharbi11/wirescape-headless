<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Player v1 owner soak and facts (H-12 / PG10)

Design: lab proposals/0025 §2.8–2.10, §5.3. **Owner only.** This is a
protocol, not a result; agents must not run devices or claim Pi measurements.
The H2 hosted 200-switch workflow is complementary, not this hardware soak.

## Readiness and record

Do not start the qualification until H-14 is merged, P1-e2 is merged and the
headless pin includes it, and the owner's first
[hardware smoke](HARDWARE_SMOKE.md) has a recorded result. Follow
[INSTALL_PI.md](INSTALL_PI.md) for the pinned build and explicit hardware
consent. Keep lab #326 open/closed status in the PG10 result; an open #326
prevents the full gate from passing.

On the Pi 5, use a trusted disposable copy of a representative generative
bundle with a quiet/silent entry and an active OSC In/Out/script entry. Record
headless git SHA, full LAB_PIN, engine binary SHA-256, bundle revision/hash,
OS/kernel, architecture, Pi model/RAM, cooling, power, audio device/rate/block
and test date/time zone. Keep raw evidence outside the repo; redact device
serials, hostnames and personal paths before sharing. Use a fresh state
directory and stop any competing Player instance before the diagnostic run.
Never use a production installation or overwrite a performance bundle.

## PG10: 4–12 hours

1. Start device-off with the exact pinned binary, using a fresh state folder
   and the copied bundle. Run the diagnostic recorder below. It uses the
   ordinary Player runner with a test-only observation hook, not a replacement
   engine. Open the reference UI in a local browser if used during the soak.
   Confirm that state is running, the intended entry is loaded, and expected
   OSC routes listen on loopback. Keep the patch fixed for each measurement
   epoch: OSC counters reset on graph commits, so a reset must not be mistaken
   for zero drops.
2. After a 15-minute warm-up, record a continuous 4–12 h measurement window
   (12 h preferred for installations). Include a sustained silent period and
   an active generative period with the actual script/OSC cadence; record exact
   durations, rates and phase boundaries. For each steady phase retain a
   contiguous interval on one graph generation. Record traffic sent/received
   using a sequence-aware source/sink where possible; local UDP send success
   alone does not prove delivery. For the control route, use P1-e2 and verify
   it actually listens. Do not enable LAN or physical devices in this first run.
3. If the device-off run is clean, repeat on the intended hardware with only
   the owner-selected consent flags, the same bundle/rate/block, and a separate
   state folder/log. Keep levels safe; stop on stuck notes, audio stalls,
   excessive heat or loss of control. An interrupted run is not a pass.
4. Capture Player and engine RSS separately, process CPU as percentage of one
   core, raw audio dropouts, OSC In and Out drops and controller drop counters,
   process restarts, and any gap/reset in the log. Retain the journal or stderr
   and record thermal throttling. Check script health and UI responsiveness.
   Repeat any suspect phase with the same configuration, not a looser limit.

### Owner diagnostic recorder

From the headless checkout, after building the pin and stopping competing
services, use a fresh log path and a state folder for the disposable bundle:

```sh
python3 tools/soak_record.py --record ./pg10-device-off.jsonl -- \
  --state ./pg10-state --bundle-root ./soak-bundles \
  --engine ./wirescape-engine --engine-arg=--null-audio
```

The owner stops it with Ctrl-C/SIGTERM after the measurement window. Capture
stderr separately if desired. The recorder logs raw sidecar status (including
OSC Out and controller counters not necessarily forwarded by API v1), a
monotonic timestamp, engine session/generation and Linux /proc process samples
every ten seconds. It does not open devices or send traffic. Use the same
recorder in all PG10 comparisons. Record its diagnostic overhead; do not use
it for the H-f1 latency timing. A normal uninstrumented service repeat is
valuable if the diagnostic run shows a regression. Check free disk space
before a 12 h run and retain the file after stopping. A recording failure is
reported on stderr, disables further recording without interrupting engine
message dispatch, and returns a nonzero status when the Player stops. Treat
that run as inconclusive; stop it normally and repeat after resolving the error.

### Evaluation

- Plot RSS and one-core CPU% vs elapsed time for both processes, separately
  by phase. Compare first and last 30-minute steady-state windows, medians,
  ranges, and trend slopes. The design specifies **flat**, not a numeric
  leak threshold: report exact slopes and any sustained growth or step;
  do not invent a pass tolerance. CPU while actively playing is not the
  silence baseline.
- Zero OSC drops means zero increases in every available ingress route,
  physical listener (deduplicate per port), and outbound route drop counter
  throughout each measured epoch. Report controller fifo/latest/oversize
  independently, plus any Player controller queue warnings. A counter
  reset, missing metric, lost status interval, process exit, or route that
  never listened invalidates a zero-drop claim for that interval. Do not
  convert missing fields to zero. Use sender/receiver counts to identify
  losses outside engine counters. Never sum repeated shared listener counts.
- Unexpected restart/hang, accumulating RSS, growing CPU in silence or any
  OSC drop is a failure to investigate. Report exact time, generation,
  counters, logs and reproduction. Report inconclusive if coverage is
  missing. Do not claim PG10 until the owner run and lab #326 closure exist.

## H-f1 — mapped-knob latency (10 min)

On the Pi 5, device-off with --null-audio --scripted-midi, run the Play page
and 100 CC/s across eight independently mapped controllers for 10 minutes.
Measure each ingress event's engine steady-clock timestamp t to receipt of
the corresponding successful setParam ACK in the Player (same monotonic clock
domain must be verified). Correlate controller identity/value with each
request; count coalesced, unmapped, unacknowledged and dropped observations
separately. Do not use SSE time, UI paint time or HTTP response time as an ACK
proxy. Preserve raw pairs, sample count and p50/p95/p99/max; p99 <= 10 ms is the
budget. Hosted arm64 is diagnostic only. The P1-e scripted source at 992d599
has a continuous CC1 plus a one-shot sequence, not eight steady controllers;
the required workload and timing instrumentation must be available before
claiming H-f1. Keep the row unmeasured until then. If it fails, apply the
design's in-patch mapping warning and investigate the Player path.

## H-f2 — UI cost (30 min)

On the same Pi, patch, rate/block and workload, capture a 30-minute UI-off
baseline and a 30-minute Play page run updating at 30 Hz. Confirm actual update
cadence, keep browser/compositor settings fixed and avoid unrelated workloads.
Sample the browser process tree (including renderer/GPU children) every ten
seconds; sum RSS (report shared-memory double counting if relevant) and
compute CPU time deltas / elapsed wall time, where 100% is one core. Track
engine dropouts from raw status over each fixed-generation interval.
Pass only if UI-on dropouts equal the UI-off baseline, UI process-tree mean
CPU <= 25% of one core, and UI RSS stays <= 350 MB. Report peak RSS as well as
mean. If it fails, try the lighter web engine with the same page before
considering a native UI (0025 §2.9). Missing cadence or counters is inconclusive.

## Lab facts submission (copy once per run)

No values below are pre-filled measurements. Submit to lab facts/ with raw
evidence link, exact headless and lab commit, machine and date.

| Field | H-f1 latency | H-f2 UI cost | H-f3 PG10 soak |
|---|---|---|---|
| Status (pass/fail/inconclusive/unmeasured) | unmeasured | unmeasured | unmeasured |
| Headless SHA / LAB_PIN / binary hash | — | — | — |
| Pi model/RAM / OS/kernel / date ET | — | — | — |
| Bundle / audio config / consent flags | — | — | — |
| Duration / workload / phase boundaries | 10 min required | 30 min per condition | 4–12 h required |
| Samples / missing or rejected data | — | — | — |
| p50/p95/p99/max latency, ms; dropped events | — | n/a | n/a |
| UI-off/on dropouts; mean CPU%; peak RSS MB | n/a | — | n/a |
| Player/engine RSS first/last median, range, slope | n/a | n/a | — |
| Player/engine silent CPU first/last median, slope | n/a | n/a | — |
| OSC In/Out/listener deltas; controller drops; resets | — | — | — |
| Restarts / stalls / errors / thermal notes | — | — | — |
| lab #326 state / owner smoke / P1-e2 pin | n/a | n/a | — |
| Raw evidence / reproduction / conclusion | — | — | — |

Signed: gpt-lead, 2026-11-27
