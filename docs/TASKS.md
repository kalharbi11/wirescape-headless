<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Task pool (any agent)

Tasks are GitHub issues labelled `task`. Nobody is assigned: any agent session takes the next free
**bundle**, which is two or so tasks sized for one long run. Design: lab `proposals/0025` §6.2.

**Triggers:** `headless: run`, or `1:run` through `5:run` for the corresponding builder session.
All sessions use this same pool; numbers do not assign bundles. Follow the steps below.

## A run, step by step
1. **Read and resume first.** Read AGENTS.md, this queue and your task issue. Check your active
   PR's current head, actual H0/H1 jobs/logs, review and latest handoff before taking more work.
   Use connected GitHub tools and Actions; shell clone/DNS failure alone is not a blocker.
2. **Review first when practical.** For an eligible `status/review` PR another session wrote,
   use the AGENTS checklist and comment `Reviewed <sha7>: ok` or required corrections.
   Merge only under the existing H0/H1 and independent-review rules; docs-only needs the review.
3. **Claim one free bundle.** Verify dependencies and writer paths first. Comment
   `Claimed: <session>; <date>; branch: <branch>` on its next open task issue and change
   `status/open` to `status/claimed`. No permanent assignment. Before taking over an old claim,
   inspect its branch, PR and latest handoff; 48 h without a push is a reason to check, not permission
   to overwrite active work.
4. **One open PR per bundle.** One task issue, one branch and one PR, task ID in title and
   `Closes #N` in body; tests first. Start the next task from current main after its predecessor
   merges. Draft-ahead only when explicitly authorized on the issue; existing H-12 #32 is a
   bounded exception. Stay in your named paths; serialize LAB_PIN bumps and overlapping files.
5. **Verify and hand off.** Post the AGENTS handoff with exact head and actual job evidence;
   set `status/review` only when ready. A green draft H1 gate may mean skipped engine/UI jobs.
   Correct failures on the same PR, then continue your bundle as its gates permit.
   H2 only on owner request; no hardware result is inferred from hosted CI.
6. **Lab dependency or stop.** Follow AGENTS rule 11 for a lab gap; reuse an existing issue when it
   covers the gap and link it here. On stopping, leave `handoff-ready` or `blocked: <dependency>`
   plus exact next actions; remove your claim and return to `status/open` or `status/blocked`.
   Preserve branch/PR history and never create a competing implementation.


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
the owner re-runs the MIDI-controller steps. Soak, latency and UI-cost facts (H-f1–H-f3) stay unmeasured until their respective owner runs.

**A113 (2026-11-27):** Macro row: deferred to the MOD-5 pin (A113). The first pin after
[wirescape-test MOD-5 #8](https://github.com/kalharbi11/wirescape-test/issues/8) promotion must prove
CC → Macro → `values` with the real engine; [lab #711](https://github.com/kalharbi11/wirescape-lab/issues/711)
tracks that row. H-14's mapped raw-parameter witness is accepted for early hardware smoke. H-f1 stays
unmeasured until J's collector, the separate lab workload extension and the owner run are ready (100 CC/s across eight continuous controllers).

**One PR, three tasks (2026-11-26):** H-0, H-1 and H-2 went into one PR, because this session may push to only one branch. Later tasks use one PR each.

**Parallelism:** J's pin integration and K's UI analysis may run together in their named paths.
I remains on its existing PR. No automatic H2 dispatch or agent device run is authorized.

**Labels:** `task`, existing bundle labels where available, `status/open` → `status/claimed` → `status/review` → closed;
`status/blocked` when a lab change is needed.

Signed: claude-architect, 2026-11-26

Signed: codex-lead, 2026-11-27, 13:56 EST

Run/claim guidance aligned with the workshop; H0/H1/H2 remain unchanged.
Signed: codex-lead, 2026-11-27, 14:01 EST
