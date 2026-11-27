<!-- SPDX-License-Identifier: GPL-3.0-only -->
# wirescape-headless

The headless **Wirescape Player** for Raspberry Pi 5. It runs the unchanged lab `wirescape-engine`, a
small Player service, a documented **Player API v1** and a replaceable reference UI (5" 800 × 480 touch
first). Patches are built in Wirescape Studio
([`kalharbi11/wirescape-lab`](https://github.com/kalharbi11/wirescape-lab)) and run here unchanged.

**Design:** lab [`proposals/0025`](https://github.com/kalharbi11/wirescape-lab/blob/main/proposals/0025-player-osc-scripts-tools.md)
(Planner run 2b, final). Macros and mapping come from lab `proposals/0024` §3 and §6.
**Status:** see [`TASKS.md`](TASKS.md) → [`docs/TASKS.md`](docs/TASKS.md) for the active tasks and pinned-engine limitations.

```
Studio (full UI) ── bundle export ──► bundle: patches/ + player.json + scripts/ + presets/
                                         │ python -m player install
                                         ▼
  any UI ── Player API v1 (HTTP + SSE, loopback) ──► Player service ── engine protocol v0 ──► wirescape-engine
  (reference UI, or your own)                          │                                     (lab build at LAB_PIN)
                                                       └── one supervised process per script (OSC to the engine)
```

## Agent runs

Read [AGENTS.md](AGENTS.md), [TASKS.md](TASKS.md) and your task issue on every start or resume.
`headless: run` and numbered builder-session triggers use the same unassigned bundle pool.
Resume an existing claim before taking new work; one task/branch/PR and one open PR per bundle.

Use connected GitHub tools to publish and Actions for routine tests, even if shell clone/DNS fails.
Check actual current-head H0/H1 jobs/logs: a draft's green gate may mean skipped tests.
Use an appropriate Codex checkout for live reference-UI, screenshot and alternate-pin evidence.
H2 and hardware runs remain owner-requested/owner-run under AGENTS.md.

## What each part does
- **Player service** (`player/`, Python 3.11+, standard library only):
  - supervises the engine: restarts it with a growing delay and never gives up, and kills it on a hang;
  - loads a bundle and switches patches through one arbiter, with Program Change debounce;
  - keeps live values and writes them into the document it loads, so nothing jumps;
  - runs scripts and reads MIDI and OSC controllers through the engine's controller stream;
  - serves the Player API. It draws nothing.
- **Player API v1** (`api/`, `docs/API.md`): `GET /api/v1/state`, `POST /api/v1/command`, and
  `GET /api/v1/events` (Server-Sent Events). It is versioned and schema-checked.
- **Fake player:** `python -m player fake` runs the same service with a fake engine. Build a UI against it
  on any computer.
- **`player.json`** (`docs/PLAYER_JSON.md`) holds the setlist, controls, pages, hardware map and Program
  Change rule. Control targets: a macro (page and knob), a parameter, an ordinary modulation cable's
  amount, or a script control.
- **Reference UI** (`ui/`): a kiosk web page with every menu and parameter. Build your own with
  `docs/UI_GUIDE.md`.
- **Scripts** (`scripting/`): the runner `wsrun.py` and the helper `ws.py` (MIT). One process per script,
  normal user rights, all gates to 0 on stop.

## Commands (devices off unless you pass consent flags)
```
python -m player fake --bundle examples/bundle            # API and UI at http://127.0.0.1:8770/ui/
python -m player check path/to/bundle [--lab LABDIR]      # bundle check; non-zero only on errors
python -m player install path/to/bundle --state DIR      # atomic; refuses on check errors
python -m player run --state DIR --engine PATH [--bundle-root DIR] [--engine-arg=--confirm-audio …]
python -m unittest                                        # H0 tests
```

## Guides
- [OSC and MIDI setup](docs/guides/OSC_MIDI_SETUP.md)
- [Python scripting](docs/guides/SCRIPTING.md)
- [Board setup](docs/guides/boards/): board-specific firmware, ADC and MIDI/OSC examples
- [Player installation](docs/guides/INSTALL_PI.md)
- [UI design](docs/UI_GUIDE.md)

## Layout
| Path | What |
|---|---|
| `player/` | the Player service (core, engine client, fake engine, API server, check, install) |
| `api/` | `player-api.v1.schema.json` (the contract) and examples |
| `ui/` | the reference UI (static HTML, CSS and JS; no build step) |
| `scripting/` | script runner and helper library |
| `systemd/` | `wirescape-player.service`, `wirescape-ui.service` |
| `tools/labpin.py` | fetches and verifies the lab commit in `LAB_PIN` |
| `tests/` | H0 unit and contract tests; `tests/integration/` runs the real engine (H1) |
| `docs/` | `REQUIREMENTS.md`, `API.md`, `PLAYER_JSON.md`, `UI_GUIDE.md`, `guides/` (OSC/MIDI setup, boards, scripting, Pi install) |
| `examples/` | `bundle/`, six lab patches, `scripts/generative_ws.py`, the OSC In rows it expects |
| `LAB_PIN` | the lab commit this repo builds the engine from |

Folders appear with the tasks that create them (0025 §6.2).

## CI
- **H0:** Linux x64 on every push. Unit, contract and fake-player tests, plus the UI when it changes.
- **H1:** ready PRs and `main`. The engine is built at `LAB_PIN` on x64 and arm64, then the integration,
  contract and switch tests run with `--null-audio`.
- **H2:** on the owner's request. The 200-switch test. Pi soaks and latency facts are the owner's device
  runs.

Rules for agents: [AGENTS.md](AGENTS.md). Licence: GPL-3.0-only (`LICENSE`); MIT where a file says so
(`scripting/ws.py`).
