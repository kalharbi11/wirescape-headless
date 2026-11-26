<!-- SPDX-License-Identifier: GPL-3.0-only -->
# AGENTS.md — wirescape-headless (provisional, 2026-11-26)

These rules are provisional until the Planner run 2 (`claude-planner`) replaces them. The repo is meant to be
**looser than the lab**: any agent may implement and merge after one simple review by another agent
session, with CI green.

## Keep always
1. **Patches stay self-contained.** Never add a patch key the engine needs, never make a patch depend
   on this repo, a script or a preset. Player data lives in `player.json`, next to the patches.
2. **Categories, not devices.** No code path names a specific board or MIDI device. Device material
   goes in guides, presets and test-matrix rows only.
3. **The UI talks only to the Player API.** The Player service draws nothing.
4. **Python never runs inside the engine.** Scripts are separate supervised processes.
5. **Devices off in CI:** no audio/MIDI devices, no LAN (localhost is fine). Owner-only device runs
   need explicit flags.
6. **No secrets**, machine paths, user names or host names. No audio files in git.
7. SPDX header on every new file (GPL-3.0-only unless the file is meant to be MIT).
8. **Escalate, don't patch the engine.** Anything that needs a change in the engine, host, SDK or
   Studio becomes an issue in `kalharbi11/wirescape-lab` labelled `limitation found`, linked here.
   The engine comes from the lab commit in `LAB_PIN`.
9. No force-push and no history rewrite on shared branches.

Signed: claude-architect, 2026-11-26
