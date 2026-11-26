<!-- SPDX-License-Identifier: GPL-3.0-only -->
# wirescape-headless

The headless **Wirescape Player** for Raspberry Pi 5: the unchanged `wirescape-engine` plus a small
Player service, a documented **Player API** and a replaceable reference UI (5" 800×480 touch to
start). Patches are built in Wirescape Studio (the full UI, in
[`kalharbi11/wirescape-lab`](https://github.com/kalharbi11/wirescape-lab)) and run here unchanged.

**Status (2026-11-26): skeleton.** The architecture, API, file formats and repo rules are decided by
the Fable design run 2 (brief: lab `docs/context/fable/`). Until then this repo holds requirements and
examples only. Nothing here is a decision yet.

```
Studio (full UI) ── builds ──► bundle: patches/ + player.json + scripts/ + presets/
                                  │ copy
                                  ▼
                 Player service (this repo) ── engine protocol v0 ──► wirescape-engine (lab build)
                       │  Player API
                       ▼
                 any UI: reference UI now, your own later
```

| Path | What |
|---|---|
| `docs/REQUIREMENTS.md` | owner requirements for the Player (functions and stability) |
| `examples/patches/` | a few bundled Studio patches copied from the lab at `LAB_PIN` (test material) |
| `examples/scripts/generative_ws.py` | stdlib-only Python generative script: OSC triggers, notes and CV |
| `examples/osc_in_script_rows.json` | the OSC In rows that script expects (unverified against the engine) |
| `LAB_PIN` | the lab commit this repo builds against |

Rules for agents: [AGENTS.md](AGENTS.md). Licence: GPL-3.0-only (`LICENSE`); MIT where a file says so.
