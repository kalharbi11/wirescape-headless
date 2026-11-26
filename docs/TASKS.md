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
| Bundle | Tasks | Needs merged first | Notes |
|---|---|---|---|
| — | H-0 [#2](https://github.com/kalharbi11/wirescape-headless/issues/2) CI skeleton | — | in review (claude-architect) |
| **A** | H-1 [#3](https://github.com/kalharbi11/wirescape-headless/issues/3) API schema + fake · H-2 [#4](https://github.com/kalharbi11/wirescape-headless/issues/4) `player.json` + check | H-0 | **free now**; H-1 and H-2 are independent |
| **B** | H-3 [#5](https://github.com/kalharbi11/wirescape-headless/issues/5) core · H-5 [#6](https://github.com/kalharbi11/wirescape-headless/issues/6) install and boot | H-1 | |
| **C** | H-10 [#7](https://github.com/kalharbi11/wirescape-headless/issues/7) runner and helper | H-1 | runs in parallel with B and D |
| **D** | H-6 [#8](https://github.com/kalharbi11/wirescape-headless/issues/8) reference UI · H-9 [#9](https://github.com/kalharbi11/wirescape-headless/issues/9) UI guide | H-1 | runs in parallel with B and C |
| **E** | H-4 [#10](https://github.com/kalharbi11/wirescape-headless/issues/10) real engine in CI · H-11 [#11](https://github.com/kalharbi11/wirescape-headless/issues/11) scripts in the Player | H-3 (H-11 also H-10) | the first `LAB_PIN` bump |
| **F** | H-7 [#12](https://github.com/kalharbi11/wirescape-headless/issues/12) hardware map + PC · H-8 [#13](https://github.com/kalharbi11/wirescape-headless/issues/13) systemd + Pi guide | H-3, H-5 | H-7's H1 part waits on lab P1-e being pinned |
| **G** | H-12 [#14](https://github.com/kalharbi11/wirescape-headless/issues/14) soak protocol · H-G [#15](https://github.com/kalharbi11/wirescape-headless/issues/15) guides | H-7, H-10, H-11 | board pages may start any time |

**Parallelism:** after A merges, three sessions can run B, C and D at once. Bundle E needs B. Bundle F
needs B, and its real-engine part also needs lab P1-e. That makes the Player-on-hardware path
P0 → P1-e → H-7 → H-f1 (0025 §6.1).

**Labels:** `task`, `bundle/A`…`bundle/G`, `status/open` → `status/claimed` → `status/review` → closed;
`status/blocked` when a lab change is needed.

Signed: claude-architect, 2026-11-26
