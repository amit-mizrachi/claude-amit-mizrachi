# The agent-fix contract

agent-fix owns the orchestration: the background sessions, the fix choice and its consultants, the build, the approval request and the summary. It knows nothing about any one company's agents or eval system. That half lives in a **domain repo** as three role skills, and this file is the contract between the two halves. A domain skill implements its side in its own "Under agent-fix" section.

## The binding line

A domain repo declares its role skills in ONE line of its root `AGENTS.md` (or `CLAUDE.md`), on its default branch:

    agent-fix roles (...): diagnose `<path>` · reproduce `<path>` · prove `<path>`

The line starts with `agent-fix roles`. Each role name is followed by its skill's `SKILL.md` path in backticks, relative to the repo root. The separators between roles do not matter. A repo that also checks its doc paths in CI keeps the binding from rotting.

The front door finds the line under `REPOS_ROOT` (or in the repo `domain:` names), snapshots that repo, and passes each skill's absolute path in the snapshot to the phases as `DIAGNOSE_SKILL`, `REPRODUCE_SKILL` and `PROVE_SKILL`.

## Rules for every role

- **Unattended.** The role asks nobody. Where its skill would stop for a human, it follows its own "Under agent-fix" rule: decide and write the call in `<WS>/LOG.md`, or end with a `BLOCKED` verdict.
- **Files in, files out.** A role reads and writes the workspace files below, nothing else of agent-fix's. Paths are absolute under the run workspace `<WS>`; `<WS>/facts.env` holds `TRIALS`, `TRACKER_ITEM` and `BENCH`.
- **The verdict line is written last**, one line, in the role's verdict file. The orchestrator branches on its first word only.
- **Approvals.** Invoking agent-fix is the human "yes" for exactly the eval work the domain's reproduce and prove skills name as theirs. Nothing wider.

## The roles

| Role | Called by | Reads | Writes | Verdict file: first word |
|---|---|---|---|---|
| **diagnose** | TRIAGE, step 1 | `REPORT-SOURCE.md`, `BRIEF.md` | `ISSUE.md` with sections `What happened`, `What should happen`, `Root cause`, `Blast radius`, `Where a fix can live`; `BENCH.txt` | `state/DIAGNOSE.verdict`: `FOUND` \| `HYPOTHESIS` \| `UNKNOWN` |
| **reproduce** | TRIAGE, step 2 | `ISSUE.md`, `BENCH.txt` | `BEFORE.md` (a per-trial table) and `before/`; `CASES.txt` (one case id per line); `CASES_PR.url` (or `none`) | `state/REPRODUCE.verdict`: `RED` \| `FLAKY` \| `NOT_REPRODUCED` \| `BLOCKED` |
| **prove** | BUILD's test session | `BEFORE.md`, `CASES.txt`, `FIX-PLAN.md`, the fix branches | `build/AFTER.md` (same table shape, plus `<case>: before k/n -> after k/n` lines and the regression check) and `build/after/` | `build/state/PROVE.verdict`: `GREEN` \| `RED` \| `REGRESSED` \| `UNKNOWN` |

## What the orchestrator does with each verdict

- diagnose `UNKNOWN`: stop the run (`BLOCKED`) and notify. `HYPOTHESIS`: go on, and say "hypothesis" everywhere the root cause is reported.
- reproduce `RED` or `FLAKY`: go on. `NOT_REPRODUCED` or `BLOCKED`: stop the run and notify. No RED, no fix.
- prove `GREEN`: the approval request may go out (CI permitting). Anything else: the build still opens its PR, and SHIP holds the approval request.
