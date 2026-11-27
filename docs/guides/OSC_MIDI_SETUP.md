<!-- SPDX-License-Identifier: GPL-3.0-only -->
# OSC and MIDI setup

**Applies to:** Player v1 at this checkout's LAB_PIN; controllerStream requires H-14, control OSC port requires P1-e2 and the later pin bump.
**You need:** a trusted bundle, the Player, a local terminal, a MIDI or OSC controller (optional for device-free checks).
**Time:** 15–25 minutes.

The engine, not the Player or its UI, owns devices. Choose an in-patch mapping for lowest latency,
or a Player hardware binding for patch-independent actions, script controls and setParam-only parameters.
Keep the Player HTTP API loopback-only.

## 1. Validate the bundle without devices

From the checkout:

```sh
python -m player check examples/bundle --scripts
python -m player fake
```

In a second terminal:

```sh
curl -fsS http://127.0.0.1:8770/api/v1/state
curl -fsS -N 'http://127.0.0.1:8770/api/v1/events?controller=1'
```

**Check:** check reports zero errors (warnings about the example script's missing OSC In rows are expected);
the fake API returns state and the stream begins with state. Ctrl-C the stream/fake after checking.
The fake does not prove actual MIDI/OSC reception.

## 2. Configure in-patch OSC

In Studio, add OSC In, set its port (e.g. 9000) and enable a row with a unique address
`/ws/knob/1`, argument 0, kind CV, input/output 0..1, smoothing 5 ms. Wire row1 to a parameter's
modulation path; export the patch unchanged into a new bundle. A mono address is `/ws/<name>`,
a poly address is `/ws/<name>/<n>` (1-based, number last). Names are lower-case slugs:
replace runs of non-ASCII-alphanumeric characters by underscores, strip leading/trailing underscores,
max 32 characters. Use notes 0..127, CV 0..1, gates 0/1, triggers without an argument.
For a named voice use name_pitch, name_gate and optionally name_vel before the channel number.

```sh
python -m player check PATH_TO_BUNDLE --scripts
```

**Check:** no errors; in Studio use the OSC route status and row indicator (when supported at your lab pin)
to confirm that the intended row is receiving. Never change a saved patch from the Player.

## 3. Choose local or LAN ingress

For a local script use host 127.0.0.1 and the row's port. For a separate controller on a trusted
LAN, the owner must enable LAN on the OSC In module and add the explicit engine
`--engine-arg=--confirm-lan` consent to the service override (see INSTALL_PI). Keep audio and MIDI
off unless separately consented. Discover the receiver's address on its own terminal:

```sh
hostname -I
ss -lun
```

Use the intended LAN IPv4 address and configured UDP port on the controller; never expose the
Player API or forward its ports to the internet. The owner alone changes firewall rules.

**Check:** the engine reports the expected bind, row receives advance, and only the intended
interface/controller can reach it. If the row is disabled or port busy, correct the patch/port first.

## 4. MIDI and in-patch mapping

With audio muted, the owner grants MIDI consent by adding `--engine-arg=--confirm-midi` to the service
override. For hardware mapping/PC, first verify `controllerStream` in the actual engine capabilities.
Send commands locally:

```sh
cmd() { curl -fsS -H 'Content-Type: application/json' -d "$1" http://127.0.0.1:8770/api/v1/command; }
cmd '{"type":"midi.devices"}'
cmd '{"type":"midi.enable","deviceId":"REPLACE_WITH_DEVICE_ID","on":true}'
```

Choose the ID from the device list. For in-patch controls use a MIDI CC to CV row with the chosen
channel and CC; save/export in Studio. For Player mapping, edit a source bundle's `player.json` using
the example's hardware row for CC 74 / channel 1 and choose a resolved control. `jump` is immediate;
`pickup` waits until the controller crosses the current value. Notes fire on note-on; PC uses the
entry program (or zero-based index if no programs are assigned). Check the full syntax in PLAYER_JSON.

```sh
python -m player check PATH_TO_BUNDLE --scripts
curl -fsS -N 'http://127.0.0.1:8770/api/v1/events?controller=1'
```

**Check:** with H-14 pinned, raw controller events appear, a mapped value changes or PC selects
the matching entry after debounce. Before H-14 the Player mapping/PC check is blocked; in-patch MIDI
is separate. Without real hardware use the fake's documented injection command, not device consent.

## 5. Patch-independent OSC (future capability)

Use a separate control port (e.g. 9100) in `player.json` and do not place any patch OSC In on it.
The engine design uses launch flag `--control-osc-port 9100`, default off; it needs P1-e2 and a pinned
Player integration. It binds loopback unless both `--confirm-lan` and `--control-osc-lan` are passed
by the owner. No runtime port change. This is not supported at the initial pin; do not pass unknown
flags or claim it works because `player.json` accepts the key.

```sh
curl -fsS http://127.0.0.1:8770/api/v1/state
```

**Check:** only after the later pin/integration, confirm capability `controllerStream.controlPort`,
an actual control route and an SSE event with matched:false; confirm a mapped action on a different
entry. Otherwise record blocked (P1-e2).

## 6. Return to device-off

Remove the owner consent override and restart the service according to INSTALL_PI.

```sh
sudo systemctl restart wirescape-player.service
curl -fsS http://127.0.0.1:8770/api/v1/state
```

**Check:** null audio and no consent; the Player remains locally reachable.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| No OSC | address/argument/port mismatch | compare configured row and sender; inspect the engine route |
| No LAN ingress | owner consent, route LAN flag or network isolation | verify both flags and intended network |
| No PC or mapping | capability absent, MIDI disabled, ID/channel mismatch | check H-14 and the device list |
| Knob not moving | pickup or unmapped target | cross current value; inspect resolved control |
| Control port unavailable | P1-e2 not pinned | use in-patch OSC; do not start a second Player socket |
| Bundle check rejects port | patch OSC In shares control port | use distinct ports |
