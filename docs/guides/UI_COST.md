<!-- SPDX-License-Identifier: GPL-3.0-only -->
# H-f2: reference UI cost measurement (owner run)

**Applies to:** record headless commit and LAB_PIN. **You need:** installed Player, kiosk browser, owner-approved audio, one repeatable patch, process CPU/RSS sampling and engine dropout counter. **Time:** at least 60 minutes plus setup.

1. Record the machine, OS, browser/version, engine pin, patch, sample rate, buffer, and exact consent flags. Use the same workload in both runs. Capture the engine's initial dropout counter. **Check:** counters and process IDs are available.
2. Run for 30 minutes with the UI off. Record start/end dropouts, engine settings and workload. **Check:** baseline delta is known.
3. Open the reference Play page at 800 × 480, with the same patch and controls producing 30 Hz values events. Confirm actual event cadence with a localhost SSE client. Sample the browser process tree every second (sum per-process CPU time deltas and resident memory; include descendants). Record start/end dropouts. **Check:** 30 minutes of samples with the expected event rate.
4. Calculate CPU as total tree CPU seconds divided by elapsed seconds × 100 (one logical core = 100%). Record maximum tree RSS, using summed RSS consistently and noting shared pages may be counted twice. **Check:** dropout delta equals baseline, mean CPU ≤25%, maximum RSS ≤350 MB.
5. Record raw logs, commit, machine and date in lab facts H-f2; if any metric fails, try a lighter web engine with the same page first. Never treat a hosted browser run as the owner measurement.

| If it fails | Cause | Fix |
|---|---|---|
| No values events | workload not updating controls | choose a repeatable 30 Hz source, then restart both runs |
| Counter resets | engine restarted | discard run and investigate restart |
| Browser children missed | process tree changed | sample descendants again each interval |
| CPU or RSS exceeds limit | kiosk cost | test lighter web engine; native UI only as last resort |

Status: unmeasured. Agents do not run devices.
