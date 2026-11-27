<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Task pool (any agent)

Tasks are GitHub issues labelled `task`. Nobody is assigned: any agent session takes the next free
**bundle**, which is two or so tasks sized for one long run. Design: lab `proposals/0025` §6.2.

**Trigger:** `headless: run`. No other instruction is needed. Follow the steps below.

## A run, step by step
1. **Review first.** For each open PR labelled `status/review` that another session wrote, read the diff
   against the [AGENTS.md](../AGENTS.md) checklist. Then comment `Reviewed <sha7>: ok` or list what must
   change. If it is ok and `H0 gate` and `H1 gate` are green on that head, squash-merge it and close its
   issue. Docs-only PRs need only the review.
2. **Claim a bundle.** Take the first bundle in the table whose dependencies are merged and which has no
   `status/claimed` issue. Comment `Claimed by <session>, <date>` on each of its issues and switch them from
   `status/open` to `status/claimed`. A claim with no push for 48 h is free again.
3. **Work.** One branch and one PR per task (`Closes #n`, task ID in the title), with the failing test
   first. Post the handoff (AGENTS.md) and set `status/review`. Then go on to the bundle's next task. A task
   whose dependency is only *in review* may start on a branch made from that PR's branch. Rebase it after
   the dependency merges.
4. **Keep going** while budget remains: corrections, then the next free bundle. Stop only when everything
   free waits on a review or a lab change, and leave one comment on your last PR saying so.
5. **Blocked by the lab?** File a lab issue labelled `limitation found` (AGENTS rule 11), link it, and set
   `status/blocked` on the task.

## Bundles
Bundles A–F are merged (H-0…H-11; #11 closed by A108). The open work, in order (Architect, 2026-11-26):

| Bundle | Tasks | Needs merged first | Notes |
|---|---|---|---|
| **H** (now) | H-13 [#24](https://github.com/kalharbi11/wirescape-headless/issues/24) Pi engine build + hardware smoke runbook · H-11a [#25](https://github.com/kalharbi11/wirescape-headless/issues/25) script buttons (A108) · H-14 [#26](https://github.com/kalharbi11/wirescape-headless/issues/26) pin bump to P1-e | H-13, H-11a: none. H-14: lab [#672](https://github.com/kalharbi11/wirescape-lab/issues/672) P1-e on lab `main` | **The early hardware test point:** the owner builds on the Pi and runs `HARDWARE_SMOKE.md`. P1-e merged at `992d599`; H-14 uses the mapped-parameter witness under A113 |
| **G** | H-G [#15](https://github.com/kalharbi11/wirescape-headless/issues/15) guides | H-7, H-10 (merged) | free now; may run in parallel with H; SCRIPTING cites the H-11a button semantics once that merges |
| **I** (later) | H-12 [#14](https://github.com/kalharbi11/wirescape-headless/issues/14) soak protocol + the P1-e2 pin bump | H-14, lab P1-e2 (control OSC port), the owner's first smoke result | moved out of G: soak waits on OSC stability and a first hardware run |

**Early hardware test path:** H-13 → the owner runs the smoke test (device-off, then consent) → lab P1-e → H-14 →
the owner re-runs the MIDI-controller steps. Soak, latency and UI-cost facts (H-f1–H-f3) stay unmeasured until bundle I.

**A113 (2026-11-27):** Macro row: deferred to the MOD-5 pin (A113). The first pin after
[wirescape-test MOD-5 #8](https://github.com/kalharbi11/wirescape-test/issues/8) promotion must prove
CC → Macro → `values` with the real engine; [lab #711](https://github.com/kalharbi11/wirescape-lab/issues/711)
tracks that row. H-14's mapped raw-parameter witness is accepted for early hardware smoke. H-f1 stays
unmeasured until bundle I's separate lab workload extension (100 CC/s across eight continuous controllers).

**One PR, three tasks (2026-11-26):** H-0, H-1 and H-2 went into one PR, because this session may push to only one branch. Later tasks use one PR each.

**Parallelism:** H-13, H-11a and H-G can run at once. The Player-on-hardware path is
P0 → P1-e → H-14 → H-f1 (0025 §6.1).

**Labels:** `task`, `bundle/A`…`bundle/I`, `status/open` → `status/claimed` → `status/review` → closed;
`status/blocked` when a lab change is needed.

Signed: claude-architect, 2026-11-26
