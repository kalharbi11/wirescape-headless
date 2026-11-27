<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Examples

- `patches/`: six lab Studio patches copied at `LAB_PIN` (one uses OSC Out; none uses OSC In yet — the
  lab ships no OSC In patch). They are test material for the Player, not maintained copies.
- `scripts/generative_ws.py`: Euclidean drums (`/ws/trig/1-2`), a random-walk melody (voice 1), a Markov
  chord pad (voices 2–4) and two CVs, sent to `127.0.0.1:9000` through the `ws` helper (H-10), with a
  `density` knob as its script control. `scripts/ws.py` is a copy of `scripting/ws.py` (MIT); a test keeps
  the copies identical. Checked against a local UDP listener; H1 separately exercises a real-engine script gate/replay witness.
- `osc_in_script_rows.json`: the OSC In rows the script expects, generated from its `--print-config`
  declaration (a test keeps them in step). Wiring: row 1 pitch, row 2 gate and row 3 velocity → VCO and
  ADSR/VCA (4 voices); row 4 triggers → Poly Split → kick and hat envelopes (ADSR in Trigger mode);
  row 5 → filter cutoff; row 6 → any slow modulation.

- `scripts/button_counter.py`: A108 momentary press example (requires Player v1.1 and matching helper); declaration is tested without opening a socket.
- `controllers/wifi_osc_knob.py` and `controllers/usb_midi_knob.py`: owner-run firmware examples for supported network and native USB MIDI categories. H0 checks the message encoders and `--print-config` without devices. `controllers/serial_midi_knob/` is the owner-compiled UART MIDI sketch; not compiled or hardware-tested in H0.

See [OSC/MIDI setup](../docs/guides/OSC_MIDI_SETUP.md), [board pages](../docs/guides/boards/) and [scripting](../docs/guides/SCRIPTING.md). The shipped scene does not contain matching OSC In rows; create and export your own trusted patch before testing script-driven sound.
