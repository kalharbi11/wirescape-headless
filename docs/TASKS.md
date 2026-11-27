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
Updated by the lead at the owner's request, 2026-11-27. Bundles A–H are complete except
the explicitly separated H-12 task in I. Claims live on issues; nobody is assigned a new bundle in advance.

| Bundle | Tasks in order | Start / qualification gates | Status |
|---|---|---|---|
| **I: owner soak** | H-12 [#14](https://github.com/kalharbi11/wirescape-headless/issues/14), existing PR [#32](https://github.com/kalharbi11/wirescape-headless/pull/32) | Existing draft-ahead only. Qualification waits on P1-e2 pin (J1), recorded first owner smoke, exact-head CI and independent review. | Already claimed; preserve its branch and correction history. |
| **J: pin and knob evidence** | H-15 [#35](https://github.com/kalharbi11/wirescape-headless/issues/35) → H-16 [#36](https://github.com/kalharbi11/wirescape-headless/issues/36) | Pin task available now: P1-e2 and follow-up #715 are on lab main. Collector follows pin merge; complete latency qualification additionally needs the lab's eight-controller source (lab #711) and owner Pi run. | **Unassigned; any session may claim.** |
| **K: UI cost evidence** | H-17 [#37](https://github.com/kalharbi11/wirescape-headless/issues/37) | Tooling/protocol available now in paths separate from I/J. Actual H-f2 result requires the owner Pi run. | **Unassigned; any session may claim.** |

**Completed:** H-13 #24, H-11a #25, H-14 #26 and guides #15 are closed; do not reclaim them.
Current pin is P1-e `992d599`; P1-e2 merged upstream but is not pinned here.
Lab #326 is closed after the post-fix soak; no new #326 fix is needed.
The first owner's smoke result was not established by this check: keep it an explicit prerequisite,
never infer hardware success from H1.

**Writer boundaries.** J1 is the sole LAB_PIN writer; changes beyond the pin are only forced fixes
and the regenerated catalogue. J2 owns its new latency helper/tests and KNOB_LATENCY guide.
K owns its separate UI-cost helper/tests and UI_COST guide. Neither edits I's open PG10
recorder/runbook. One task/branch/PR each, tests first, exact-head H0/H1 plus different-session review.
A collector may ship useful device-off tooling while reporting its real measurement as unavailable.

**Early hardware test path:** H-13 → the owner runs the smoke test (device-off, then consent) → lab P1-e → H-14 →
the owner re-runs the MIDI-controller steps. Soak, latency and UI-cost facts (H-f1–H-f3) stay unmeasured until bundle I.

**A113 (2026-11-27):** Macro row: deferred to the MOD-5 pin (A113). The first pin after
[wirescape-test MOD-5 #8](https://github.com/kalharbi11/wirescape-test/issues/8) promotion must prove
CC → Macro → `values` with the real engine; [lab #711](https://github.com/kalharbi11/wirescape-lab/issues/711)
tracks that row. H-14's mapped raw-parameter witness is accepted for early hardware smoke. H-f1 stays
unmeasured until bundle I's separate lab workload extension (100 CC/s across eight continuous controllers).

**One PR, three tasks (2026-11-26):** H-0, H-1 and H-2 went into one PR, because this session may push to only one branch. Later tasks use one PR each.

**Parallelism:** J's pin integration and K's UI analysis may run together in their named paths.
I remains on its existing PR. No automatic H2 dispatch or agent device run is authorized.

**Labels:** `task`, existing bundle labels where available, `status/open` → `status/claimed` → `status/review` → closed;
`status/blocked` when a lab change is needed.

Signed: claude-architect, 2026-11-26

Signed: codex-lead, 2026-11-27, 13:56 EST
