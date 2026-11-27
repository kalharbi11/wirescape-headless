<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Python scripting

**Applies to:** Player v1, with momentary buttons requiring v1.1 / H-11a; record LAB_PIN.
**You need:** Python 3.11+, a trusted bundle and a Studio patch with OSC In rows.
**Time:** 20–30 minutes.

A script is an optional supervised child, never part of the engine and never required by a patch.
Only run scripts you trust: they are ordinary Python processes, not a security sandbox. The Player
does not write scripts or patches; scripts send only to the engine's loopback route by default.

## 1. Inspect the declaration without opening a socket

```sh
python -I examples/scripts/generative_ws.py --print-config
python -I examples/scripts/button_counter.py --print-config
```

**Check:** each emits exactly one JSON object, format wirescape.script version 1, with controls,
outputs and generated oscIn configs (at most eight rows each). It exits at ws.start before opening
a socket or executing the performance loop; a custom script must not do side effects before start.

## 2. Create a patch and bundle

Copy the trusted script and the MIT helper from examples/scripts into your source bundle's scripts/
folder, not into an installed bundle. For the generative example use examples/osc_in_script_rows.json
or the oscIn declaration; in Studio set port 9000 and matching rows, cable row outputs to voices,
envelopes and CV targets. For button_counter, wire /ws/press as a trigger. Export the patch into
patches/ and declare the entry's scripts and script targets as in examples/bundle/player.json.
Each script imports its adjacent ws.py explicitly because the runner uses Python isolated mode.

```sh
python -m player check PATH_TO_BUNDLE --scripts
```

**Check:** zero errors, no missing-row warning for intended outputs. A patch without matching rows
still loads, but the script cannot drive it. The Player never auto-syncs Studio-only links.

## 3. Helper API

Read the working examples in examples/scripts/. Declare outputs and controls before ws.start().

| Call | Semantics |
|---|---|
| ws.trig(name) | send() triggers without a value; optional channel |
| ws.gate(name) | on()/off() or send(1/0); held gate resent every 500 ms |
| ws.cv(name, out_min, out_max) | send normalized 0..1; generated row scales to range |
| ws.voice(name, voices, velocity) | on(voice, note, vel), off(voice), send(voice,note); notes 0..127 |
| ws.knob / slider / bounded number | numeric .value |
| ws.toggle / dropdown | bool or selected label .value; Player wire uses 0/1 or choice index |
| ws.button(name) | momentary .press_count, starts at zero per process (v1.1) |
| ws.text / notes / label / unbounded number | declarable, not mapped by Player v1; default remains local |
| ws.sleep(seconds) / ws.wait_until(perf_counter_target) | interruptible, maintains heartbeat and held gates |

Addresses are /ws/name (mono) or /ws/name/n (poly, 1-based). A voice sends pitch before gate;
a gate's generated row times out after 2000 ms with stale zero. A trigger has no argument.
Helper caps sends at 1000/s and counts drops. Do not bypass the helper for unbounded bursts.

```sh
python -I examples/scripts/generative_ws.py --print-config
```

**Check:** voice rows include pitch, gate and velocity, gate timeout 2000/stale zero, CV smoothing 5 ms.

## 4. Install and supervise, device-off first

With a disposable state directory and the engine executable at LAB_PIN:

```sh
python -m player install PATH_TO_BUNDLE --state ./script-smoke-state
python -m player run --state ./script-smoke-state --engine ./wirescape-engine --engine-arg=--null-audio
```

From another terminal define a localhost command helper and select the entry containing the script:

```sh
cmd() { curl -fsS -H 'Content-Type: application/json' -d "$1" http://127.0.0.1:8770/api/v1/command; }
curl -fsS http://127.0.0.1:8770/api/v1/state
cmd '{"type":"select","index":0}'
```

Replace index with your script entry. The runner uses one child per declared script, sends control
messages on stdin, reads declare/heartbeat from stdout, and reports script health. A stalled child
is marked after 5 s, and crash restart backs off from 250 ms to 30 s without restarting the engine.

**Check:** script shows running and resolved numeric controls; engine state remains running.
No devices or LAN are needed.

## 5. Set controls and momentary buttons

With generative_ws.py active and the example's density target:

```sh
cmd '{"type":"set","target":{"script":{"file":"scripts/generative_ws.py","control":"density"}},"norm":0.7}'
```

With the v1.1 button_counter.py active:

```sh
cmd '{"type":"set","target":{"script":{"file":"scripts/button_counter.py","control":"press"}},"value":1}'
cmd '{"type":"set","target":{"script":{"file":"scripts/button_counter.py","control":"press"}},"value":0}'
```

Each high set (≥0.5) produces exactly one press; a low set produces none. The helper's press_count
is an event counter, not .value. Keep a local handled count and handle each new event (see example).
CC mappings press once per low→high crossing, note-on presses, note-off does nothing. A press never
persists or replays; a bounded numeric value does. Unsupported control mappings appear invalid;
check --scripts warns once per unsupported declaration, without blocking installation.

**Check:** v1.1 state has momentary:true, min 0/max 1/step 1 and value/norm null for mapped buttons.
A stopped/unready child cannot accept a press. If using the older API or helper, skip the button example.

## 6. Stop and verify safety

```sh
cmd '{"type":"script.stop","file":"scripts/generative_ws.py"}'
curl -fsS http://127.0.0.1:8770/api/v1/state
cmd '{"type":"script.start","file":"scripts/generative_ws.py"}'
cmd '{"type":"script.restart","file":"scripts/generative_ws.py"}'
```

Replace file with the active script. Stop sends a stop message, waits 500 ms, terminates then kills if
needed, and the runner sends zero to every declared gate even after crashes. Held gate refresh and
the stale-zero timeout provide another guard. Keep audio muted for initial tests.

**Check:** script stops/starts/restarts independently; engine restart count does not change.
With a matching OSC In gate row and a monitor, observe gate zero on stop. A script status alone
is not a gate witness. Stop the Player with Ctrl-C when finished.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| print-config fails | import, invalid declaration, or >5 s before start | use adjacent helper and declare before start |
| Script runs but no sound | row/port/cable mismatch or null audio | check row declarations, not consent by default |
| Gate sticks | missing stale-zero timeout or wrong address | use generated row and inspect actual gate |
| Control unavailable | wrong file/id or unbounded/text type | use declared bounded control or v1.1 button |
| Press appears persistent | wrong helper/API version | copy matching helper, use press_count |
| Script repeatedly restarts | child failure | inspect stderr/journal and fix source bundle |
