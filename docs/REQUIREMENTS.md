<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Player requirements (owner, 2026-11-26)

Source: lab `docs/context/fable/01_OWNER_WANTS.md` §B.2–B.3. Fable design run 2 turns these into the
design; this file lists *what*, not *how*.

## Functions
- Play any patch built in Studio, unchanged, with every Wirescape module.
- A setlist of patches; switch from the UI, a controller or MIDI Program Change.
- Live control of exposed parameters, including modulation amounts. Every parameter must be
  mappable; there is no limit on how many are exposed.
- **Macros** (global knobs with per-target ranges, built in Studio) are the main way to expose
  controls. Physical knobs and menu slots map to macros or raw parameters in an editable mapping file,
  like a game-controller config.
- MIDI in and out; OSC in and out (network controllers by IP).
- Controllers are any MIDI or OSC device; the owner writes the board code. Feedback (LEDs, servos)
  through MIDI or OSC out.
- Python scripts run in the Player (supervised); their declared controls appear like any control.
- Limited variations: a module's own settings exposed as controls → sibling patches with a fade →
  snapshots.
- Patches with sequencers play as they are. Graphical sequencer editing comes later (skip it if
  it needs a lot of testing).
- A reference UI with every menu and parameter, separate and replaceable, plus a **UI design guide** so
  the owner can build custom interfaces quickly against a fake player.

## Stability (required, gated by tests)
1. The engine restarts with growing delays and never gives up, then reloads the current patch and
   control values; a heartbeat detects a hang, not only a crash.
2. A UI crash or a script crash never stops audio; each restarts on its own.
3. Boot to the last bundle and patch with no input; a systemd watchdog covers the service.
4. Atomic saves; a power cut never corrupts the bundle or settings.
5. Patch switching: fade, no stuck notes or gates, OSC routes listening again quickly (lab OB-h3).
6. Long Pi soaks (4–12 h): flat memory, flat CPU in silence, zero OSC drops.
7. A bundle check before copying (lab OB-h6 `patch_library.py check`, extended to `player.json`).

## Already available in the lab (facts at `LAB_PIN`)
- `wirescape-engine` is a Qt-free process driven by NDJSON on stdio (lab `host/sidecar/DESIGN.md`,
  `docs/specs/ENGINE_PROTOCOL.md`). Studio is only a client.
- Patch replacement fades out, swaps and fades in (lab `host/sidecar/session.cpp`).
- MIDI Learn mappings are saved inside the patch as `midi.cc_to_cv` rows plus cables.
- The desktop app stops restarting the engine after 3 crashes in 30 s (lab `apps/desktop/main.ts:262`);
  the Player must not copy that policy.

Signed: claude-architect, 2026-11-26
