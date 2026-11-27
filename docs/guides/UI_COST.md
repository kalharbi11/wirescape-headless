<!-- SPDX-License-Identifier: GPL-3.0-only -->
# H-f2: reference UI cost measurement (owner run)

Design: lab proposals/0025 §2.9. Status: **unmeasured** until the owner records a Pi 5 result.
The hosted tests validate analysis only. Do not run devices or dispatch H2 for this task.

## 1. Prepare a paired run

Use a Raspberry Pi 5, the exact headless checkout and engine built from its LAB_PIN, a local graphical
session and the installed kiosk user unit (see [INSTALL_PI.md](INSTALL_PI.md)). Use the same trusted
patch, workload, sample rate, buffer, audio device, browser version and consent settings in both runs.
Record the OS, screen configuration (800 × 480), build/binary provenance and patch digest. Verify that
the installed Player/UI files match the checkout and that the engine is the recorded pin. Only the owner
may select hardware and grant consent. Device-off preparation is the default; it is not an audio
dropout qualification by itself. Both timed qualification windows require the real Player
(`player.fake: false`), a running audio output (`engine.audio.state: running`), and a nonempty
actual device identifier. Fake, null-audio, stopped, starting, lost, stalled or unknown output is
inconclusive even if a numeric dropout counter is present.

Choose a reproducible workload that drives the reference Play page at 30 Hz for 30 minutes, without
switching patches. Record the exact source, configuration and commands and repeat it with the kiosk off
as well as on. The Player API coalesces values at **up to** 30 Hz; a visible Play page, an idle graph or
a nominal input rate is not proof of the required update rate. Record actual event cadence and evidence
that the Play page updates at that rate for the full window. The helper does not instrument rendering
or create a workload. If a qualifying workload or observation is unavailable, leave the result
inconclusive. Do not substitute a fake Player, hosted browser or a shorter run.

Run the collector from the headless checkout as the kiosk's desktop user, with access to its own
systemd user unit and /proc entries, and with cgroup v2 mounted at /sys/fs/cgroup. Python 3.11+ and
systemctl are sufficient for the helper. Do not run the browser as root.

Create a private evidence directory outside the checkout. Example metadata (replace placeholders;
date is the actual run date, browser is the actual version):

```json
{
  "machine": "Raspberry Pi 5",
  "date": "YYYY-MM-DD",
  "patch_sha256": "replace with full lowercase SHA-256",
  "workload": "exact repeatable workload commands and configuration reference",
  "browser": "Chromium version",
  "consent": "exact owner-selected flags",
  "play_30hz_observed": false
}
```

Get the patch digest with `sha256sum "$PATCH"` using the actual patch file, and record
`git rev-parse HEAD`, `python tools/labpin.py show`, `chromium --version`, `uname -srmo` and
the installed engine's SHA-256 in the run notes. The collector fills in the full headless and lab SHAs
from the checkout. Keep raw records private if they contain machine-specific paths or identifiers.
Make two metadata files identical apart from the UI observation; never predeclare success.

## 2. Collect 30 minutes per condition

In both phases, wait for the Player and selected graph to be stable before starting the timed workload.
Keep workload running before the first and through the last sample. Do not restart the Player, engine,
kiosk or change the patch or audio settings mid-window. Keep other machine activity comparable.

```sh
# Owner, from the checkout; replace EVIDENCE with your chosen private directory.
systemctl --user stop wirescape-ui.service
# Start the documented repeatable workload.
python tools/ui_cost.py collect baseline "$EVIDENCE/baseline-meta.json" "$EVIDENCE/baseline.json"

systemctl --user start wirescape-ui.service
# Open Play, stabilize, repeat the identical workload.
python tools/ui_cost.py collect ui "$EVIDENCE/ui-meta.json" "$EVIDENCE/ui.json"
```

Use the same observation overhead in both conditions. For example, in another local terminal during
each phase capture a timestamped SSE values-event trace (start before collection and stop afterward):

```sh
curl --no-buffer --silent --show-error http://127.0.0.1:8770/api/v1/events |
  python3 -u -c 'import sys,time; [print(time.monotonic(), line.strip(), flush=True) for line in sys.stdin if line.strip() == "event: values"]' \
  > "$EVIDENCE/values-times.txt"
```

Use separate trace files for baseline and UI; observe continuity, cadence and the actual visible Play
page updates. SSE cadence alone is insufficient to establish rendering cadence. Record how the owner
verified the update rate (and retain the underlying evidence). Only after confirming the whole UI
window, set `play_30hz_observed` to true in the UI evidence JSON (keep the original raw capture and
record the attestation separately; the analysis input may be a copy). The tool trusts this explicit
owner attestation rather than inventing a rate tolerance or claiming a browser trace it did not collect.

## 3. Analyze and inspect

```sh
python tools/ui_cost.py analyze "$EVIDENCE/baseline.json" "$EVIDENCE/ui.json"
```

Exit 0 = thresholds pass with complete supplied evidence; 1 = a measured limit fails; 2 =
inconclusive. A complete record includes sample timestamps (monotonic seconds), UI active state,
kiosk invocation identity, cumulative CPU microseconds, PID/start-time/RSS rows, engine running state,
engine restart count, explicit Player identity, audio state, patch index, audio settings and
cumulative dropout counter. Example single
sample structure, **illustrative only** (not a complete run):

```json
{
  "t": 100.0,
  "engine_running": true,
  "player_fake": false,
  "audio_state": "running",
  "engine_restarts": 0,
  "patch_index": 0,
  "audio_settings": {"sampleRate": 48000, "bufferFrames": 256, "deviceId": "example"},
  "dropouts": 10,
  "ui_active": true,
  "invocation": "example-invocation:123",
  "cpu_usec": 1234567,
  "processes": [
    {"pid": 100, "start": 12, "rss_bytes": 100000000},
    {"pid": 101, "start": 13, "rss_bytes": 150000000}
  ]
}
```

- Sample at one-second targets; both windows must span at least 1800 seconds, with at most 1.5 s
  between observations and at most 1.5 s overrun. This is a sampling completeness check, not a
  change to the 30-minute workload or performance limits. Missing or raced observations are not zero.
- Use the dedicated kiosk service's **entire cgroup subtree** (including subprocesses in child cgroups).
  CPU is cumulative cgroup v2 usage_usec, including processes that exit between samples. Divide the
  interval delta by elapsed microseconds × 100: one logical core is 100%, not 100% of the Pi.
  Do not normalize by core count or average instantaneous percentages.
- Sum all member RSS in bytes from /proc/PID/stat, using PID plus process start time to detect
  reuse during sampling. The peak is the largest observed sum (shared pages can be counted twice).
  This is sampled RSS, not a continuous upper bound between observations; retain the raw trace and
  note that limitation. Membership races invalidate the run rather than omit a process. A kiosk
  invocation/cgroup change invalidates the run. Do not put unrelated tasks in the kiosk unit.
- Use the engine's cumulative audio.dropouts exposed by the localhost Player state; missing,
  noninteger, declining counters, engine restarts, unavailable audio settings or mismatched
  conditions are inconclusive. Each sample must explicitly show `player_fake: false` and
  `audio_state: "running"` with a nonempty string `audio_settings.deviceId`. The device ID,
  sample rate and buffer must stay identical throughout and between both windows. A zero is
  valid only if the real, running output explicitly reports zero. Older captures missing these
  identity fields cannot qualify; recollect rather than infer them.
  Retain service logs and invalidate the run if the Player or engine restarted even if sampled
  counters happen to match.

Unchanged design limits: mean CPU ≤ 25% of one core, sampled peak tree RSS ≤ 350 MB
(350,000,000 bytes), and **equal** engine dropout deltas, UI-off versus UI-on. No requirement
that the baseline counter itself be zero. Do not replace equality with a different acceptance rule.
If cost fails, try a lighter web engine with the same page first; native UI is the last resort.

## 4. Owner result template (lab facts H-f2)

| Field | Record |
|---|---|
| Headless / lab full SHA, engine binary hash | |
| Machine kind, OS, date, browser/version, display | |
| Patch digest, workload commands, consent flags, audio settings | |
| Baseline and UI durations, raw evidence filenames | |
| Actual Play update cadence, observation method and raw trace | |
| Baseline dropout start/end/delta | |
| UI dropout start/end/delta | |
| UI mean CPU (% one core), sampled peak tree RSS (bytes) | |
| Restarts, missing samples, measurement limitations | |
| Result: pass / fail / inconclusive; owner | |

Do not write a lab facts pass based on this tool's synthetic tests, absent counters or unavailable
workload. Record the owner result with commit, machine and date; H-f2 remains unmeasured until then.
