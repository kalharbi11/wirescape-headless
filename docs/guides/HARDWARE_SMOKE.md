<!-- SPDX-License-Identifier: GPL-3.0-only -->
# First hardware smoke (owner only)

**Applies to:** Player v1 at the checkout's LAB_PIN, H-13 / H2.
**You need:** a Pi with the installed Player, USB audio interface, a MIDI controller if available,
a trusted example bundle, local access, a backed-up disposable state directory and a way to mute audio.
**Time:** about 30 minutes after building/installing; no soak or latency measurement.

This is an owner run, not CI. Keep LAN off. Start with the interface muted and low monitoring volume.
Use the commands from the [Pi install guide](INSTALL_PI.md); all API requests are localhost.

## 1. Boot device-off

Install the example bundle using steps 1–3 of INSTALL_PI. Use the unmodified unit with
`--null-audio`. In a second terminal:

```sh
state() { curl -fsS http://127.0.0.1:8770/api/v1/state; }
cmd() { curl -fsS -H 'Content-Type: application/json' -d "$1" http://127.0.0.1:8770/api/v1/command; }
state
git rev-parse HEAD
python3 tools/labpin.py show
sha256sum ./wirescape-engine
```

**Check:** engine running, current index 0 on a fresh state, no current error, no physical audio/MIDI enabled.

## 2. Audio-only consent

Use INSTALL_PI step 5 to replace the service ExecStart with the audio-only consent override.
Connect the interface, grant the service account the necessary device permissions, and restart.
Do not add MIDI or LAN yet.

```sh
cmd '{"type":"audio.devices"}'
```

Choose the exact USB interface deviceId from the reply. Substitute it for the placeholder:

```sh
cmd '{"type":"audio.select","deviceId":"REPLACE_WITH_DEVICE_ID"}'
state
cmd '{"type":"select","index":0}'
```

**Check:** each reply has ok true; the selected device is the intended one. Unmute gently;
hear the First tone entry. If sound is unexpected, mute and restore null audio.

## 3. Entry switching

```sh
state
pgrep -a -x wirescape-engine
cmd '{"type":"select","index":2}'
cmd '{"type":"set","control":"tempo","value":135}'
cmd '{"type":"select","index":3}'
cmd '{"type":"select","index":2}'
state
pgrep -a -x wirescape-engine
```

**Check:** correct entry/audio after each switch, same engine PID and restart count, tempo 135
recalled. Observe and report any audible discontinuity (M4); a different patch is loaded,
so this is not proof that oscillator phase persists across different graphs.

## 4. MIDI Program Change and mappings

Inspect `engine.capabilities` in state. Before lab P1-e is pinned (H-14), record
**skipped: engine lacks controllerStream** for PC and controller mapping, and continue.

After H-14, the owner may add `--engine-arg=--confirm-midi` to the audio override and restart.
Use `cmd '{"type":"midi.devices"}'` and then
`cmd '{"type":"midi.enable","deviceId":"REPLACE_WITH_DEVICE_ID","on":true}'`.
Send PC 0 then PC 2 (wire values, some devices show 1 and 3).
Select entry 5 and sweep CC 74 on channel 1 across the current cutoff (pickup).

**Check:** PC selects the matching program, rapid PC presses settle on the last entry;
cutoff moves after pickup. A note-off alone does not switch entries. If the capability is absent,
do not enable MIDI for these steps.

## 5. Script lifecycle and gate zero

Select entry 5. Inspect the declared script and its state:

```sh
cmd '{"type":"select","index":5}'
state
cmd '{"type":"set","control":"dens","norm":1}'
cmd '{"type":"script.stop","file":"scripts/generative_ws.py"}'
state
```

**Check:** script runs, responds to density, stops independently of the engine. The shipped
scene has no matching OSC In rows, so it cannot witness a gate inside the graph. To verify the gate,
use a trusted Studio patch with the OSC In rows from `examples/osc_in_script_rows.json` (port 9000),
route gate rows to a visible meter or audible voice, and install that separate test bundle with
the same script declaration. Stop while a gate is held: verify it drops to zero; report the
actual observation or mark gate verification untested. Do not modify installed patches.
The H1 `test_real_script.py` test is a separate device-off witness, not owner hardware evidence.

## 6. Recovery (disposable state only)

Save a nondefault entry/value, restart normally once so `state.good.json` reflects the selection,
then check recovery. Back up the state directory while the service is stopped. With the owner
consent override removed, restart device-off. For an actual unexpected-power-loss trial use a
disposable boot medium and disconnect/mute audio first; abrupt power loss may damage the filesystem.
Alternatively use the safer simulated corruption test below (record which was done):

```sh
sudo systemctl stop wirescape-player.service
sudo cp -a /var/lib/wirescape-player /var/lib/wirescape-player-smoke-backup
printf '{' | sudo tee /var/lib/wirescape-player/state.json >/dev/null
sudo systemctl start wirescape-player.service
state
```

**Check:** Player boots using the good copy and restores the expected entry/value. If actual power
loss was tested, record whether the filesystem and state recovered; simulated corruption alone
does not demonstrate power-cut resilience.

## 7. Restore safe defaults and report

Remove the owner override and restart the null-audio unit (INSTALL_PI step 5). Paste this result
into [lab #590](https://github.com/kalharbi11/wirescape-lab/issues/590):

```text
Owner hardware smoke (H-13)
Headless commit:
LAB_PIN commit:
Engine sha256:
Machine / OS / audio interface / MIDI:
Date:
Device-off boot:
Audio device selection / entry 1:
Entry switches / same engine PID / audible observations:
PC and mapping (pass/fail/skipped: engine lacks controllerStream):
Script start/stop / gate zero (observed or untested):
Recovery method and result:
Failures / journal excerpts:
Latency, CPU, soak: unmeasured (H-12).
```

**Check:** null-audio restored; each item is pass, fail, skipped with reason, or untested.
Do not mark unobserved outcomes as pass.

## If it fails

| Symptom | Action |
|---|---|
| Build fails | Fix preflight errors and build in a fresh directory at LAB_PIN. |
| Audio device missing | Check audio-only consent and service permissions; mute before retrying. |
| No PC or CC | Verify capability, H-14 pin, consent, device ID and channel. |
| Script warning | Check trusted script's declared OSC In rows and port; no LAN needed. |
| State not restored | Save journal and both state files; stop service and restore backup. |
| Engine crashes or stalls | Record lastExit/restarts and journal; return to device-off. |
