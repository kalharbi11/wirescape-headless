<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Task pool entry

The canonical bundle queue and claim rules are in [docs/TASKS.md](docs/TASKS.md).
Read that file, [AGENTS.md](AGENTS.md), and your task issue on every run or resume.
Do not maintain a second task table here.

`headless: run` or `1:run` through `5:run` starts/resumes a builder session using the same
unassigned pool. Session numbers do not assign bundles. Check existing claims and active
PR heads, actual H0/H1 jobs/logs and review status before taking work.

Signed: codex-lead, 2026-11-27, 14:01 EST
