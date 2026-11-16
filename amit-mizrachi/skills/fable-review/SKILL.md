---
name: fable-review
description: "Review code with one Fable subagent (the latest Fable model) running deep-review, wait for its report, then address the findings: verify each against the code, fix the confirmed ones, and re-review the fixes once. Use when the user runs /fable-review, optionally naming a PR number, a branch, or nothing (uncommitted work and the current branch)."
disable-model-invocation: true
argument-hint: "[PR number | branch | nothing for the current work]"
---

# fable-review

`deep-review` with a Fable reviewer instead of Opus, followed by acting on what it finds. One reviewer, one fix pass and one re-review of the fixes. This session does the fixing; the subagent only reviews.

Claude Code only. It needs the `Agent` tool and access to a Fable model.

## Step 1 - Pin the target in this session

Resolve exactly what gets reviewed **before** spawning anything, using `amit-mizrachi:deep-review` Step 1 (read that skill's `SKILL.md`):

- **Nothing named**: uncommitted work is snapshotted into an unreferenced commit, otherwise `HEAD`. Base is the merge-base with `origin/<default branch>` (fetch first).
- **A PR number**: `gh pr view <n> --json baseRefOid,headRefOid,headRefName,body,url`, and use exactly its base and head. If the local checkout is not on the PR's head, check it out into a new worktree (`git worktree add <dir> <headRefName>`) instead of switching branches under the user.
- **A branch**: its head, against the merge-base with the default branch.

Record `REPO` (absolute path), `BASE_SHA`, `HEAD_SHA`, and the intent, quoted verbatim per deep-review Step 2 (PR body, ticket text or plan; "none given" if there is none). If base equals head, say there is nothing to review and stop.

## Step 2 - Spawn one Fable reviewer and wait

Make exactly one `Agent` call:

- `subagent_type: general-purpose`
- `model: fable` (resolves to the latest Fable model; `claude-fable-5-2` at the time of writing)
- `effort: high`
- `description: "Fable deep-review"`
- `prompt`: the block below, with the values filled in.

```
You are the reviewer for one code review. Load the `amit-mizrachi:deep-review` skill with the Skill tool and follow it, with these fixed inputs:

- Repo: {REPO}
- BASE_SHA: {BASE_SHA}
- HEAD_SHA: {HEAD_SHA}
- Description: {ONE_LINE_WHAT_CHANGED}
- Requirements (verbatim): {INTENT}

Steps 1 and 2 are already done: use the values above and do not recompute them.
For Step 3, YOU are the single reviewer. Fill in `references/reviewer-prompt.md` and do the review yourself in this session, as the skill's Codex path describes. Do not spawn any Agent, workflow or fork.
You are read-only: no edits, commits, pushes, posted comments or network calls other than `git fetch`.
Return the Step 4 report as your final message: the verdict, the counts by severity, every finding with confidence >= 50 (file:line, what is wrong, why it matters, the fix, severity, confidence), the permission or access-control items, and the "Declined to judge" list.
```

Then **wait** for the subagent's completion notification. Tell the user it is running and roughly how long it may take (a large diff can take 30+ minutes). Do not review the diff yourself in the meantime, and do not start a second reviewer.

If the call fails because Fable is unavailable, stop and report that. Do not fall back to another model silently; offer `/amit-mizrachi:deep-review` (Opus) instead.

## Step 3 - Address the review

Follow deep-review Step 5, in this session:

1. **Verify every finding** against the code at `HEAD_SHA`. Mark each as confirmed, partly or wrong, with a one-line reason. The reviewer can be wrong, so never fix on its say-so alone.
2. **Fix the confirmed ones**, and the confirmed part of a "partly". Use the smallest change that resolves the finding, in severity order. Do not fix anything that touches permissions, access control or visibility rules: list it for a human.
3. **Check**: run the repo's formatter or lint check, its typecheck, and the tests that cover the changed code (by file name or filter). Run the full suite only when the repo's own instructions require it. If a fix cannot be made green, revert that fix and record it as not fixed, with the failure.
4. **Land the fixes in the right place**:
   - Uncommitted work: leave the fixes uncommitted in the working tree, next to the user's work.
   - A branch or PR: commit with a message that names the findings, then push to the same branch. Never force-push, never use `--no-verify`, and never push to the default branch.

## Step 4 - Re-review the fixes once

If Step 3 changed any code, run Step 2 again on the fix diff only: `BASE_SHA` is the commit before the fixes (for uncommitted work, the earlier snapshot) and `HEAD_SHA` is a fresh snapshot or the new head. Address its confirmed findings the same way. Do **not** go round a third time: report anything still open instead.

## Step 5 - Report

- The reviewer's verdict and counts by severity.
- A table with one row per finding: severity, confidence, file:line, verdict (confirmed / partly / wrong), outcome (fixed in `<sha>` / fixed, uncommitted / not fixed: reason / needs a human).
- What the re-review found.
- The checks you ran and their results.
- Anything for a human: permission changes and fixes that could not be made green.

## Never

- Never spawn more than one reviewer per round, or more than two rounds.
- Never post PR comments from this skill. To answer reviewers on GitHub, use `/amit-mizrachi:address-review`.
- Never write a code-review attestation (see deep-review "Never").
