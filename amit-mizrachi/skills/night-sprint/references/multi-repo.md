# Multi-repo sprints

Read this at kickoff when the tickets name more than one repo, or the invocation does. One
feature, several repos, and the sprint ends with **one branch and one PR per repo**, each PR
linking the others and carrying its own manual steps.

Everything in `SKILL.md` still holds unless this file changes it: the runner, reviving, the
context rungs, asking nothing, the full suite never running locally, `advance.sh` owning the
chain. A multi-repo sprint is a single-repo sprint run once per repo for worktrees, reviews, CI
and PRs, and once for the whole sprint for the chain, the golden path and the report.

## 1. Each ticket names exactly one repo

Every frozen ticket in `<WS>/tickets/` carries a line `**Repo:** <key>`, and every ticket tag
gets `state/T<NN>.repo` holding that key. Settle the key from, in order:

1. a `**Repo:**` line already in the ticket (`to-tickets` writes one when the work spans repos);
2. a repo tag in the title - `# 03: [shapes-platform] ...` - matched to a key by repo name;
3. the ticket's content, as a call you log under `## Decided without asking`.

A ticket that names several repos (`[all three]`) is two cases. **It only verifies** (boots the
stack, walks a path, writes results into the PRs): it is the golden path, not a ticket - fold it
into PLAN.md section 4 and the TEST session, and turn a test session on if the invocation set
none. **It writes code in several repos**: split it at kickoff into one ticket per repo, keeping
its edges (the parts block whatever it blocked, and the consumer side blocks on the provider
side). Log either call.

Keys are short, lower case letters and digits, no hyphen: `machina`, `platform`, `internal`.
They end tag names (`CI-machina`), and the runner finds a tag's sessions by name prefix plus `-`,
so `shapes` beside `shapes-internal` would read as one tag.

## 2. Facts: one file per repo

`facts.env` carries the sprint, and nothing per repo:

    MULTI_REPO=1
    REPOS=<key> <key> ...          # the FIRST is home to the tags with no repo: TEST, FIX-TEST
    SLUG, USER, WS, CONTEXT_WINDOW, WARN_AT_USED, RELAY_AT_USED, CEILING_USED,
    BLITZ, MAX_PARALLEL, PERMISSION_MODE

`repos/<key>.env`, one per key, carries what a single-repo `facts.env` carries per repo:

    REPO, REPO_PATH, REPO_SLUG, WORKTREE, BRANCH, BASE, TOOLCHAIN, VERIFY, FORMAT_CHECK

`bootstrap.sh` refuses a per-repo fact in `facts.env`, a missing one in a repo file, or two
repos sharing a worktree. It derives `repos/<key>/` (the one-value files the scripts read),
`REPO_KEYS` and `REPOS.md` (the table every session reads to find a sibling's tree), appends
`REPO_KEY=<key>` to each repo file, and points the sprint's own `WORKTREE` / `BRANCH` at the
first repo. Put first the repo the golden path boots from.

## 3. One worktree and one branch per repo

Give every repo the same branch name, `<type>/<slug>`, so the PRs read as one change. For each:

    git -C <REPO_PATH> fetch origin
    git -C <REPO_PATH> worktree add --no-track -b <BRANCH> <REPO_PATH>/.claude/worktrees/<slug> origin/<base>

    git -C <REPO_PATH>/.claude/worktrees/<slug> push -u origin HEAD:<BRANCH>

`--no-track` keeps the base branch from becoming the upstream; the first push then makes the
sprint branch its own upstream, so a session's bare `git push` lands on `<BRANCH>`, never on the
base. The prompts push with `git push origin HEAD:<BRANCH>` anyway.

`launch.sh` runs a tag in its repo's worktree (`state/<TAG>.repo` -> `repos/<key>/WORKTREE`), and
cuts a blitz ticket's tree or a finder's snapshot from that repo's branch. A continuation
(`T03c2`) inherits its ticket's repo without a file of its own; `repos.sh` resolves it.

## 4. Blocking edges across repos

- **Serial**: one chain, in ticket number order, across every repo; position satisfies every
  edge, so number the tickets with each contract's provider before its consumers.
- **Blitz**: `.after` lists tags of any repo, and `schedule.sh` does not care which; a ticket
  starts once its blockers have landed on their own repos' branches. `MAX_PARALLEL` counts
  writers across all repos. `land.sh` lands a ticket on its repo's branch under that repo's own
  lock, `state/land-<key>.lock`.
- **A cross-repo blocker's code is never in the consumer's tree** - the repos share no branch.
  The implementer reads it in the sibling worktree, read only, which its prompt says.
- **A cross-repo edge is a contract.** List every one in PLAN.md section 0 with what it carries
  (an API, a schema, an event, a package). The edges decide the merge order. If they form a cycle
  between repos, each PR must be safe to merge alone (an additive contract, a flag); write how,
  and log it.

## 5. Per-repo tails: checkpoints, final review, fix, CI

| Tag | `.repo` | Started by | Wired |
|---|---|---|---|
| `REVIEW-C<n>-<key>` | key | queued + `.snapshot` | `.waits` = the last ticket of its scope in that repo (every one in blitz) |
| `REVIEW-FINAL-<key>` | key | queued | `.waits` = every ticket of EVERY repo + that repo's checkpoint finders; `.next` = `FIX-FINAL-<key>` |
| `FIX-FINAL-<key>` | key | the chain | `.next` = `CI-<key>` |
| `CI-<key>` | key | the chain | `.next` empty |
| `TEST` (opt-in) | none | queued | `.after` = every `CI-<key>`; `.next` = `FIX-TEST` or empty, the tester decides |
| `FIX-TEST` | none | the chain | `.next` empty; it `touch`es `state/CI2-<key>.queued` for each repo it pushed to |
| `CI2-<key>` | key | queued by `FIX-TEST` | `.after` = `FIX-TEST`, written at kickoff; prompt rendered at kickoff; NOT queued at kickoff |

Do not queue `CI2-<key>` yourself: a queued tag whose `FIX-TEST` never runs is `STRANDED`.

`REVIEW-FINAL-<key>` waits on every repo's tickets so it reads the finished other side of each
contract. The tails of different repos then run side by side, each in its own worktree - the one
place a serial multi-repo sprint has more than one writer, and never two in one tree.

**Cadence and lanes are per repo**, by SKILL.md's rules applied to that repo's tickets. A repo
whose diff provides or consumes a cross-repo contract earns the architecture lane.

**Render with the repo file before the tag's vars**, so its `<WORKTREE>`, `<BRANCH>`,
`<REPO_KEY>` and the rest are that repo's:

    bash <WS>/render.sh <WS> <WS>/review-find-prompt.md <WS>/prompt-REVIEW-FINAL-<key>.txt <WS>/repos/<key>.env <WS>/vars-REVIEW-FINAL-<key>.env

| Tag | vars that differ from SKILL.md's table |
|---|---|
| `T<NN>` | none - the repo file supplies the rest |
| `REVIEW-C<n>-<key>` / `REVIEW-FINAL-<key>` | `FIX_TAG=FIX-FINAL-<key>`, `NEXT_AFTER_FIX=CI-<key>`; `SCOPE` runs in that repo (`git merge-base origin/<its BASE> HEAD`, then `state/REVIEW-C<n-1>-<key>.headsha`) |
| `FIX-FINAL-<key>` | `FIND_TAG=REVIEW-FINAL-<key>`, `NEXT_TAG=CI-<key>` |
| `CI-<key>` / `CI2-<key>` | `TAG=CI-<key>` / `TAG=CI2-<key>`, `NEXT_TAG=` empty |
| `TEST` | rendered with the first repo's file; `FIND_FINAL_TAG=the REVIEW-FINAL-<key> sessions` |
| `FIX-TEST` | rendered with the first repo's file; `FIND_TAG=TEST`, `NEXT_TAG=` empty |

Verdicts per repo: `state/ACCEPTANCE-<key>.verdict` (`accept.sh <WS> <secs> "" <key>`, which
the CI prompt already runs) and `state/SETUP-<key>.verdict`. `GOLDEN.verdict` stays one file.
Manual-step blocks start with `REPO: <key | all>`.

## 6. The PRs

`NEEDS-PR <key>` arrives once per repo, after that repo's first ticket lands. Open its draft:

    gh pr create --draft -R <REPO_SLUG> --head <BRANCH> --base <base> --title ... --body-file <file>

with the three sections of PLAN.md section 0 (`## Part of a multi-repo change`, `## Merge order`,
`## Manual steps after merge`), a sibling with no PR yet marked "not opened yet". Then edit every
sibling PR already open so its first section links this one (`gh pr edit <n> -R <slug>
--body-file <file>`). At the end `FIX-FINAL-<key>` (or `REVIEW-FINAL-<key>` on SKIP) rewrites
its own body with the night's manual steps and marks it ready.

**Before the report, read every PR body once** (`gh pr view <n> -R <slug> --json body`) and fix
any sibling link still missing. It is the conductor's only PR-body edit after kickoff. A repo
whose tickets never landed has no PR: every other PR says so, and the report says why.

## 7. The morning report

SKILL.md's nine items, with these changes:

1. **The verdict** - one line per repo from `state/ACCEPTANCE-<key>.verdict`, then
   `GOLDEN.verdict`. The feature is delivered only when every repo is `PASS`.
2. **The PRs** - a table, `Repo | PR | ready or draft | CI (from CI-<key>.summary, CI2-<key>) |
   merge position`, then the merge order and why.
3. **Ticket outcomes** - grouped by repo. Name every cross-repo edge whose blocker did not land,
   and what it skipped in the other repo.
4. **The ledger** - with a `Repo` column.
9. **Turn it on** - in merge order, repo by repo: merge that PR, its manual steps after merge
   (or "nothing to set up" from `SETUP-<key>.verdict`), deploy; then the next repo.
