<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Examples

- `patches/`: six lab Studio patches copied at `LAB_PIN` (one uses OSC Out; none uses OSC In yet — the
  lab ships no OSC In patch). They are test material for the Player, not maintained copies.
- `scripts/generative_ws.py`: Euclidean drums (`/ws/trig/1-2`), a random-walk melody (voice 1), a Markov
  chord pad (voices 2–4) and two CVs, sent to `127.0.0.1:9000`. Stdlib only. Checked against a local UDP
  listener; not yet against the engine.
- `osc_in_script_rows.json`: the OSC In rows the script expects. Wiring: row 1 pitch, row 3 gate and row 4
  velocity → VCO and ADSR/VCA (4 voices); row 2 triggers → Poly Split → kick and hat envelopes (ADSR in
  Trigger mode); row 5 → filter cutoff; row 6 → any slow modulation.

First task once the Player exists: build an OSC In example patch from these rows and check it with lab
`tools/patch_library.py check`.
