<!-- SPDX-License-Identifier: GPL-3.0-only -->
# AGENTS.md — wirescape-headless

This repo is **looser than the lab**: any agent implements and merges after one simple review by another
agent session, with CI green. The design is lab `proposals/0025` (final rulings, Planner run 2b). A
change to the design goes to the lab, not here.

## Keep always
1. **Patches stay self-contained.** Never add a patch key the engine needs, and never make a patch depend
   on this repo, a script or a preset. The Player never writes `patches/` or `scripts/`. It reads `ui`
   keys for display names only, and no behaviour depends on them. Player data lives in `player.json`.
2. **Categories, not devices.** No code path names a board or MIDI device. Device names appear only in
   guides, presets, the owner's `player.json` and test-matrix rows.
3. **The UI talks only to the Player API.** The Player service draws nothing. An API change updates
   `api/player-api.v1.schema.json`, `docs/API.md` and the fake player in the same PR. v1 changes are
   additive only; a break means `/api/v2/`.
4. **Python never runs inside the engine.** Scripts are separate supervised processes, started only from
   the bundle's `scripts/`.
5. **The engine owns audio, MIDI and OSC devices.** The Player opens no MIDI port and no UDP socket. It
   reads controllers through the engine's controller stream and its control OSC port.
6. **Standard library only at runtime** (Python 3.11+). Dev-only packages are pinned in
   `requirements-dev.txt`.
7. **Atomic writes:** temp file, fsync, `os.replace`, fsync the directory. Never write in place.
8. **Devices off in CI and agent runs:** no audio or MIDI devices and no LAN (localhost is fine). The
   engine runs with `--null-audio`. Consent flags (`--confirm-audio`, `--confirm-midi`, `--confirm-lan`)
   are never defaults. Only the owner passes them.
9. **No secrets**, machine paths, user names or host names. No audio files in git.
10. **SPDX header** on every new file: GPL-3.0-only, except `scripting/ws.py` and other files meant for
    user code (MIT).
11. **Escalate, don't patch the engine.** Anything that needs a change in the engine, host, SDK or Studio
    becomes an issue in `kalharbi11/wirescape-lab` labelled `limitation found` and linked here. It
    names what was needed, the smallest lab change and any workaround. The engine comes only from the lab
    commit in `LAB_PIN`.
12. **Never loosen to pass:** no skipped test, raised tolerance or widened timeout to turn red into green.
13. **No force-push and no history rewrite** on shared branches. No commits to `main`.

## Work
- **Task pool:** [docs/TASKS.md](docs/TASKS.md). The trigger `headless: run` starts any agent on the next free
  bundle. Nobody is assigned.
- One task issue, one branch and one PR against `main`, with the task ID (H-n) in the title. Write the
  failing test first.
- **Review:** one simple review by a **different agent session**. It reads the diff and comments
  `Reviewed <sha7>: ok` or lists what must change. The checklist:
  - rules 1–13 above;
  - an API change is additive and its schema, docs and fake are updated;
  - `player.json` changes keep `version` 1 compatible;
  - supervision and switching behaviour matches 0025 §2.2–§2.4;
  - tests cover every new error or warning row.
- **Merge:** any agent squash-merges when the review names the head SHA and H0 and H1 are green on that head.
  Docs-only PRs need only the review.
- **CI tiers:**
  - **H0:** Linux x64 on every push.
  - **H1:** non-draft PRs and `main`. The engine is built at `LAB_PIN` on x64 and arm64, and tests run with
    `--null-audio`.
  - **H2:** `workflow_dispatch`, requested by the owner; agents may dispatch it when the owner asks.

  Every workflow has a `scope` job plus an always-run gate job, one concurrency group per PR and ccache
  keyed by `LAB_PIN`.
- **`LAB_PIN`:** one PR per bump, containing only the pin and the fixes it forces. Bump when a lab
  change the Player needs merges, otherwise at most weekly. Regenerate `tests/data/catalogue.json` with it.
- **Facts:** latency, UI cost and soak numbers go to lab `facts/` (rows H-f1, H-f2, H-f3) with commit,
  machine and date. An unmeasured number stays unmeasured.

## Handoff (in the PR)
```
**Status:** done | handoff-ready | blocked   **PR:** #…   **Head:** sha7
**Done:** …
**Next:** …
**Tests:** command or run link → result
Signed: <name>, <YYYY-MM-DD>
```
Dates are New York time.

Signed: claude-planner, 2026-11-26
