---
name: deep-review
description: Review code with one deep single reviewer (Opus at high effort in Claude Code, the session model in Codex) using a bundle of public review best practices - superpowers code-reviewer format, 0-100 confidence scoring, Google eng-practices checklist. Use whenever the user asks to review changes, review code, do a code review, review this branch, review a PR's code, or runs /code-review. This replaces squad-review and agent-skills:code-review for every review.
---

# deep-review

One reviewer, reading deeply, instead of a squad of narrow ones. On this team's own commits it found every High the squad found plus two more, and 93% of what it reported was real (the squad: 46%). Benchmark and sources: `references/sources.md`.

## Step 1 - Pick what to review

- **Uncommitted work** (the usual case): snapshot it in a private index, so your index, files and branch are untouched and untracked files (respecting .gitignore) are included:
  ```bash
  IDX=$(mktemp)
  GIT_INDEX_FILE=$IDX git read-tree HEAD
  GIT_INDEX_FILE=$IDX git add -A
  HEAD_SHA=$(git commit-tree "$(GIT_INDEX_FILE=$IDX git write-tree)" -p HEAD -m "deep-review: working tree snapshot")
  rm -f "$IDX"
  ```
  The snapshot is an unreferenced commit nobody pushes. If the tree holds edits unrelated to this session, say so in the report.
- **A clean branch**: `HEAD_SHA=$(git rev-parse HEAD)`.
- **Base** in both cases: `BASE_SHA=$(git merge-base origin/<default branch> "$HEAD_SHA")` (fetch first).
- **A PR handed over by review-pr**, or a PR the user names: exactly its base and head.
- No diff between base and head: say so and stop.

## Step 2 - Gather the intent, verbatim

Collect what the change is supposed to do: the Monday ticket text, the PR description, or the plan the session followed. Quote it; never write your own summary of the requirements, because a summary written by someone who already knows the problems steers the reviewer toward them. If there is none, pass "none given".

## Step 3 - Run one reviewer

Fill in `references/reviewer-prompt.md` (placeholders `{REPO}`, `{BASE_SHA}`, `{HEAD_SHA}`, `{DESCRIPTION}`, `{REQUIREMENTS}`).

- **Claude Code**: exactly one `Agent` call - `subagent_type: general-purpose`, `model: opus`, `effort: high` - with the filled prompt. Do not split the diff across agents and do not add a second reviewer. Large diffs take longer (334 files took about 34 minutes); tell the user it is running.
- **Codex**: do the review yourself in this session, following the filled prompt, with no sub-reviewers. Recommend high reasoning effort if the session is lower.

The reviewer is read-only: no edits, commits, pushes, posted comments or network calls.

## Step 4 - Present the result

Before reporting no findings, revisit removed safeguards, deleted instructions, and tests that assert permissive behavior using the replacement-flow check in `references/reviewer-prompt.md`. A passing test can encode a regression. An acknowledged limitation in the PR description remains reviewable; acknowledgment alone is not acceptance.

Validate each finding against the exact reviewed head and omit findings already fixed there. Score confidence separately from severity, as defined in the reviewer prompt.

- Summary first: ready to merge (yes / no / with fixes) and the counts by severity.
- Then every issue with confidence >= 50, sorted by severity and then confidence, each with file:line, what is wrong, why it matters and the fix. Mark those >= 80. Do not drop the 50-79 band: on the benchmark, a reproduced crash scored 55.
- Name anything that touches permissions, access control or visibility rules as needing human review (Article 9). Never "fix" those silently.
- Include the reviewer's "Declined to judge" list in one line each.

## Step 5 - When asked to investigate or fix

- Verify each finding against the code before changing anything; say per finding: confirmed / partly / wrong, with the reason.
- Fix only the confirmed ones, then run this skill again on the fix diff (`BASE_SHA` = the commit before the fixes). A bug that escaped to the PR reviewer came from an unreviewed fix.

## Never

- Never run `squad-review` or `agent-skills:code-review` from here, and never start them as a fallback. If the review cannot finish, report it as incomplete.
- Never write a code-review attestation: no `<!-- code-review: ... -->` line and no `.git/code-review-attestation` note. If a repo's `code-review-check` then fails a PR, tell the user the ways out: `/review-pr`, pasting a line from a review that did run, or the `no-review-needed` label.
