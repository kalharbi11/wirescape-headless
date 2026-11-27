<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Examples

- `patches/`: six lab Studio patches copied at `LAB_PIN` (one uses OSC Out; none uses OSC In yet — the
  lab ships no OSC In patch). They are test material for the Player, not maintained copies.
- `scripts/generative_ws.py`: Euclidean drums (`/ws/trig/1-2`), a random-walk melody (voice 1), a Markov
  chord pad (voices 2–4) and two CVs, sent to `127.0.0.1:9000` through the `ws` helper (H-10), with a
  `density` knob as its script control. `scripts/ws.py` is a copy of `scripting/ws.py` (MIT); a test keeps
  the copies identical. Checked against a local UDP listener; not yet against the engine.
- `osc_in_script_rows.json`: the OSC In rows the script expects, generated from its `--print-config`
  declaration (a test keeps them in step). Wiring: row 1 pitch, row 2 gate and row 3 velocity → VCO and
  ADSR/VCA (4 voices); row 4 triggers → Poly Split → kick and hat envelopes (ADSR in Trigger mode);
  row 5 → filter cutoff; row 6 → any slow modulation.

First task once the Player exists: build an OSC In example patch from these rows and check it with lab
`tools/patch_library.py check`.
