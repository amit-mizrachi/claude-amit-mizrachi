<REPO> - night sprint <SLUG>: <CHECKPOINT> - FIND

AUTONOMOUS NIGHT RUN. <USER> is ASLEEP and will NOT answer. Never ask a question - judge each finding yourself and record it. Never run `rm` or `mv` as a shell command: some org policies make them ask for confirmation even in auto mode, and nobody is there to answer. Use `git rm` / `git mv` for files in a repo, and the workspace scripts for the run's own state. ASCII only, no em/en dashes.

Repo: <REPO_PATH> (<REPO_SLUG>). Toolchain: <TOOLCHAIN>.
Workspace: <WS>. You are tag <TAG>. Every finding of this sprint is fixed once, at the end, by <FIX_TAG>.

DO NOT RUN TESTS. THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT - PR CI RUNS IT, AND THE ASYNC CI TICKET FIXES WHAT IS RED. A finder never runs any test, at any checkpoint. Find by reading the diff.

YOU FIND. YOU DO NOT FIX - not one file, not the verify command, not a commit, even when a fix looks like a one-liner. The fixing is a separate step because a session that consolidates reviews AND edits code spends its window twice and dies mid-triage, losing the triage.

WORK HERE - DO NOT CREATE A WORKTREE OR BRANCH:
  cd "$(cat <WS>/state/<TAG>.cwd 2>/dev/null || echo <WORKTREE>)"

REVIEWS IN THIS SPRINT ARE ASYNC. A checkpoint review (REVIEW-C<n>) does not stop the sprint: you
were launched in a read-only SNAPSHOT worktree, detached at the tip of <BRANCH> as it stood when
you started, while the next tickets keep building elsewhere. Review that snapshot as it is -
never pull, check out, commit or push in it. Nothing you find is fixed now; you write it down,
REVIEW-FINAL carries what is still true forward, and <FIX_TAG> fixes all of it at the end. That
is what lets nobody wait on a review. REVIEW-FINAL itself runs in <WORKTREE> on <BRANCH>, after
every ticket and every checkpoint review has ended, and only reads it too. Never rebase,
force-push, or merge.

THE PR NUMBER IS NOT IN THIS PROMPT, because the draft PR does not exist at kickoff when this
prompt is written. Discover it once, at the start, and use it everywhere below. Name the branch:
a snapshot worktree is detached, and a bare `gh pr view` there finds nothing:

  PR="$(gh pr view <BRANCH> --json number -q .number)"

If that comes back empty the PR has not been opened yet. Say so in your summary, write the
manifest anyway, and skip only the posting step - the manifest is the deliverable.

READ FIRST: <WS>/PLAN.md (goal + tickets), <WS>/LOG.md (what landed, and what the sprint already deferred on purpose - never re-raise a conscious deferral), and `git log --oneline` on the branch.

SCOPE: <SCOPE>. Review it as one body of work.
{{#MULTI_REPO}}

THIS SPRINT SPANS SEVERAL REPOS, AND YOU REVIEW ONE: <REPO_KEY> (<REPO_SLUG>) - its branch <BRANCH>, its PR, its tickets (the ones whose <WS>/state/T<NN>.repo says <REPO_KEY>). <WS>/REPOS.md lists the others. A defect inside another repo is that repo's reviewer's. The contract BETWEEN repos is yours from this side: where this repo calls, or is called by, code another repo's tickets built, read that side in its worktree (read only) and post a mismatch here as a finding. Name those sibling worktrees, and which calls cross between them, in the DESCRIPTION you give deep-review, so its one reviewer reads both sides of the contract. Two names change for you below:
- the checkpoint manifests REVIEW-FINAL carries forward are `<WS>/state/REVIEW-C*-<REPO_KEY>.findings.md`, never another repo's;
- the setup verdict is `<WS>/state/SETUP-<REPO_KEY>.verdict`, never `SETUP.verdict`, and it covers the <WS>/state/*.manual blocks for this repo: `REPO: <REPO_KEY>` or `all`, or, with no REPO line, a block written by a tag whose <WS>/state/<TAG>.repo is <REPO_KEY>.
On the SKIP route, the PR description you bring up to date carries the multi-repo sections the Repos section of <WS>/PLAN.md lists (sibling PRs, merge order, manual steps after merge).
{{/MULTI_REPO}}

## STEP 1 - REVIEW WITH THE ROSTER IN <WS>/REVIEWERS.md

Read <WS>/REVIEWERS.md first. Each table row is one reviewer: an ID, an ENGINE (`claude` or `codex`), a MODEL, an EFFORT and a SKILL. Most sprints have the default roster, one row - `R1 | claude | opus | high | deep-review` - and then this step is exactly one `deep-review` run, as it always was.

The roster is the user's choice, made at kickoff from the invocation or an AGENTS.md line. Run every row, and only the rows: never add, drop or swap a reviewer yourself, and never run `code-review`, `squad-review` or a set of specialist lanes beside the roster or as a fallback. If no reviewer can finish, say the review is incomplete in your summary and write the manifest from what you have.

Run the `deep-review` skill (it ships with this plugin as `amit-mizrachi:deep-review`; a user-level `deep-review` is the same skill) for its Steps 1 and 2 and to fill its reviewer prompt. Its reviewer covers design, functionality, security and privacy, complexity, tests, naming and production readiness in one pass. Feed it this sprint's inputs, not the ones its Step 1 would pick for an interactive session:
- **BASE_SHA / HEAD_SHA** - from SCOPE above: the range's two ends, resolved to full shas. HEAD_SHA is `git rev-parse HEAD` here (the snapshot, for a checkpoint). No working-tree snapshot: a finder's tree has nothing uncommitted.
- **REPO** - this worktree's path (the `cd` above).
- **REQUIREMENTS** - verbatim, never summarised: the Goal section of <WS>/PLAN.md, then the full text of every ticket in <WS>/tickets/ that SCOPE covers (REVIEW-FINAL: every ticket). deep-review explains why: a summary written by someone who knows the problems steers the reviewer toward them.
- **DESCRIPTION** - one paragraph: "night sprint <SLUG>, <TAG>, tickets <list> as landed on <BRANCH>", plus the LOG.md lines that defer something on purpose, so the reviewer does not re-raise a conscious deferral.

**deep-review's Step 3 is where the roster comes in.** In place of its single `Agent` call, start one reviewer per row, ALL IN ONE MESSAGE, so they run at the same time. deep-review's "exactly one reviewer" rule is there to stop a review being split into lanes; a roster is the user's explicit choice of whole reviewers, and it wins. Every reviewer gets the same filled reviewer prompt and reviews the same BASE_SHA..HEAD_SHA:

- **A `claude` row** - one `Agent` call: `subagent_type: general-purpose`, `model` = MODEL (an Agent model alias: `opus`, `fable`, `sonnet` or `haiku`), `effort` = EFFORT. SKILL `deep-review`: the prompt is the filled reviewer prompt. Any other SKILL: tell the agent to invoke that skill through the Skill tool on BASE_SHA..HEAD_SHA in REPO, give it REQUIREMENTS and DESCRIPTION verbatim, tell it it is read-only (no edits, commits, pushes, posted comments or network calls), and ask for the skill's full report back.
- **A `codex` row** - one `codex_start` call on the codex-bridge MCP (`amit-mizrachi` plugin): `model` = MODEL (a Codex slug such as `gpt-6-astra`), `effort` = EFFORT, `sandbox: read-only`, `approval: never`, `cwd` = this worktree, `label: ns-<TAG>-<row ID>`. SKILL `deep-review`: the prompt is the filled reviewer prompt. Any other SKILL: the same read-only instruction a claude row gets, naming the skill for Codex to use. It returns at once with a `run_id`; keep it. Put every `codex_start` FIRST in the message, so the Codex runs are already going while the `Agent` calls block.

**Wait for Codex in ten-minute checks, never one long wait.** After the `Agent` calls return, call `codex_check` with the `run_id` and `wait_seconds: 600`, again and again until the run ends. The runner reads only Claude transcripts as your activity, and a call that sits silent for 25 minutes reads as a stall and gets revived; each check that returns writes to your transcript. Take the reviewer's report from the final answer (`verbose: true` if the answer is cut off).

A big diff takes a while (about 10 minutes typical, 35 for a 300-file one) for every reviewer. That is expected: the runner counts your subagents' transcripts as your activity, so wait for them and never start a second copy of a reviewer.

**A reviewer that fails does not stop the review.** The codex-bridge tools are missing, Codex is not logged in, the model is refused, the run errors or never ends: write `<row ID> did not finish: <why>` in your summary and go on with the reports you have. If EVERY row failed and none of them was the default (`claude | opus | high | deep-review`), run that default once so the scope is not left unreviewed, and say so in your summary.

**More than one report: merge them before STEP 2.** One issue per defect: two reports that name the same file, the same lines and the same failure are one issue. Record which rows raised it (`RAISED BY: R1, R2`) and keep the higher confidence. Two different models finding the same defect is strong evidence; an issue only one reviewer found is not weaker for that, because catching what the other misses is why the roster has more than one row. Keep each reviewer's ready-to-merge verdict and "Declined to judge" list, by row, for your summary.

Take the merged list as the raw input to STEP 2. Keep every issue scored at confidence 50 or more - deep-review is explicit that the 50-79 band holds real bugs (a reproduced crash once scored 55). A skill that gives no confidence score: give each issue your own after you check it in STEP 2. deep-review's own Step 5 (fix, then review the fix) is not yours: you never fix, and <FIX_TAG> works your manifest.

## STEP 2 - TRIAGE. You are the deciding engineer, not a stenographer.

Before you bucket an issue, open the code at the reviewed head and check it yourself: confirmed, partly, or wrong. The reviewer's confidence is its evidence, not your verdict. Then every finding goes in exactly one bucket, and be hard about it. A finding you pass on becomes work for a session at 3am, so a padded list costs real hours.

Severity: a deep-review Critical is BLOCKER or HIGH, an Important is HIGH or MEDIUM, a Minor is LOW and is usually a FOLLOW-UP or a REJECT. Map another skill's scale onto the same buckets. Judge by the consequence, never by the confidence score.

- **FIX** - correctness, security, data integrity, permissions, or a real bug in what this sprint built.
- **FOLLOW-UP** - real, but out of scope. One line to <WS>/state/FOLLOWUPS.md: `<severity> | <file> | <what is wrong> | <why out of scope>`. The morning report turns it into a ticket.
- **REJECT** - wrong, or a style preference fighting this repo's conventions. Record it with the reason in your summary.

For a hand-copied library, check the sprint rules before choosing FIX. If adding it is explicitly forbidden, record or preserve a high FOLLOW-UP for <USER> instead of instructing the fixer to add it. Still report concrete bugs or unmet acceptance criteria in the fallback.

Permissions or access-control changes always need a human (charter #9). Never queue one as a fix - it is a manual step, STEP 5.

## STEP 3 - WRITE THE MANIFEST. This file is the deliverable.

REVIEW-FINAL: do the CARRY step at the top of STEP 6 first, so this manifest holds the whole night's open findings - it is the only thing <FIX_TAG> reads.

  <WS>/state/<TAG>.findings.md

One block per FIX finding, in severity order, exactly these fields:

    ID:        F<n>
    AT:        <the short sha you reviewed - `git rev-parse --short HEAD`>
    SEVERITY:  BLOCKER | HIGH | MEDIUM | LOW
    CONFIDENCE: <the reviewer's 0-100 score, after your own check - lower it if you found the evidence thinner>
    RAISED BY: <the roster row IDs that reported it, e.g. R1, R2 - only when the roster has more than one row>
    WHERE:     <file>:<line>
    ISSUE:     <what is wrong, in one sentence>
    EVIDENCE:  <the failure path, or the unmet acceptance criterion - why this is real>
    ACTION:    <the concrete change required>

Concrete enough that a session which never saw the review can act on it without re-running anything - hours later, after more tickets have landed on top of the code you read. That is why AT names the commit: WHERE is a line in THAT commit. EVIDENCE is not optional: a finding with no failure path is a finding that has not been triaged.

## STEP 4 - PUT IT ON THE PR, ONCE

Post **one** consolidated comment. Not one comment per finding.

REVIEW-FINAL posts only the findings it raised itself; the carried ones were posted by their checkpoint review when they were found.

  gh pr comment "$PR" --body-file <WS>/state/<TAG>.findings.md

Add inline anchors ONLY for BLOCKER and HIGH findings, where the exact line is the point:

  cat > "$TMPDIR/ns-<TAG>-review.json" <<'JSON'
  {
    "body": "Night sprint <TAG>: <n> to fix, <n> deferred, <n> rejected. Manifest in state/<TAG>.findings.md.",
    "event": "COMMENT",
    "comments": [
      {"path": "src/foo.ts", "line": 42, "side": "RIGHT",
       "body": "**[HIGH, confidence 85]** - <what is wrong>. <failure path>. Fix: <concrete change>."}
    ]
  }
  JSON
  gh api --method POST repos/<REPO_SLUG>/pulls/"$PR"/reviews --input "$TMPDIR/ns-<TAG>-review.json"

Three things about that call, each of which has cost a night:
1. `event` is `COMMENT`. `APPROVE` and `REQUEST_CHANGES` are both refused on your own PR and fail the whole request.
2. `line` must be a line the diff touches, counted on the RIGHT side. One line outside the diff rejects the ENTIRE review with a 422. For a range use `start_line` plus `line`.
3. If it fails, do not retry blind: the consolidated comment above is already posted, so say in your summary that inline anchoring failed and move on.

**The manifest, not the PR, is what the fixer reads.** Posting every internal finding to GitHub so another session can fetch it back is two round trips to replace reading a local file. The PR comment exists for <USER> and the bots, which is why it is one comment and not twenty.

## STEP 5 - ANYTHING A FINDING HANDS TO A HUMAN

A permissions change you refused to queue, a secret the diff now reads but nothing sets, a rotation the review says is needed. Append a block per item to <WS>/state/<TAG>.manual:

    STEP:     <one line: what a human must do>
    WHY:      <what breaks without it - the concrete failure>
    WHERE:    <URL, dashboard path or command, as concretely as you know it>
    VALUE:    <ENV_VAR_NAME, or "none" for a pure action>
    LANDS:    <.env | github secret | terraform var | a service | nowhere>
    SECRET:   <yes|no>
    BLOCKING: <yes = the feature does not work at all without it | no>

BOTH TESTS OR IT IS NOT A BLOCK: (1) the shipped feature does not work until a human acts, AND (2) no agent could have done it. A judgement call <USER> may want to reverse is a line in your summary. Something an agent could have done is a FOLLOWUPS.md line. Names and paths only, never a real secret value.

## STEP 6 - FINAL REVIEW ONLY

DELETE THIS WHOLE SECTION when rendering a checkpoint review. It applies only to REVIEW-FINAL.

- **CARRY THE CHECKPOINT FINDINGS FORWARD - this comes first.** The checkpoint reviews were async, so nobody fixed what they found: by design, every finding of the night is fixed once, by <FIX_TAG>, from YOUR manifest alone. Read every `<WS>/state/REVIEW-C*.findings.md`. Check each finding against HEAD now; later tickets may have fixed it, moved it or made it moot. Still real: copy it into your manifest with a new ID, today's WHERE and AT, and one more field, `ORIGIN: REVIEW-C<n> F<k>`. Gone: one line in your summary, `REVIEW-C<n> F<k> resolved by later work (<sha or ticket>)`. Do not post carried findings to the PR again; they were posted when they were found.
- **Re-read every ticket in <WS>/tickets/ against what actually landed.** Post any UNMET acceptance criterion as a finding like any other. This is the last honest check before <USER> sees it.
- **Do NOT take the PR out of draft** unless you route SKIP below. <FIX_TAG> does it after its fixes are pushed.
- **SWEEP THE DIFF FOR SETUP AND WRITE THE VERDICT.** You already have the whole diff loaded, so this is nearly free here. Over `git diff <BASE>...HEAD`: new env or config reads and whether `.env.example` documents them; new `secrets.*` or `vars.*` in `.github/workflows/*`; new terraform / terragrunt units; new migrations; new infrastructure a deploy will not create; a new third-party integration or OAuth client; anything a ticket's acceptance criteria assume exists but no code creates. Then check what is ALREADY set: `gh secret list`, `gh variable list`, `.env.example`, the repo's own store. **A FAILED READ IS NOT AN EMPTY ANSWER** - if a listing errors, say the read failed; never record it as "not configured".

  Apply BOTH TESTS from STEP 5 to every <WS>/state/*.manual block and to everything the sweep turned up, then write one word:

      echo NEEDED > <WS>/state/SETUP.verdict     # at least one thing passes BOTH tests
      echo NONE   > <WS>/state/SETUP.verdict     # nothing does

  Say which it is, and what you swept to reach it, in your summary. NONE is a finding, not a silence.

## CONTEXT

Measure, do not estimate: `bash <WS>/context-used.sh --self <CONTEXT_WINDOW>` - percent USED, counting up.

Check it after the reviewers' reports return; that is where the number jumps, once per report. You do no fixing, so you should finish inside your window comfortably. If you somehow reach <RELAY_AT_USED>% before posting, WRITE THE MANIFEST AND POST IT FIRST - a review that dies holding un-posted findings has produced nothing - then relay per the CONTEXT RELAY section of <WS>/PLAN.md, carrying the un-triaged findings so your successor does not re-run the review.

## WHEN DONE - in this order, and the order matters

1. `echo "<n findings, n deferred, n rejected, each reviewer's verdict by row>" > <WS>/state/<TAG>.summary`

2. **Decide what runs next**, and write it to `<WS>/state/<TAG>.next` BEFORE you write your status. Nothing launches off your status until `.next` is correct; that ordering is the whole reason the two files are separate.

   **A CHECKPOINT review (REVIEW-C<n>) launches nothing.** Your findings wait in your manifest for REVIEW-FINAL to carry forward and for <FIX_TAG> to fix. There is no checkpoint fixer, and you never hand findings to the session that wrote the code: it has moved on to its next ticket, which is the point.
       : > <WS>/state/<TAG>.next

   **REVIEW-FINAL decides whether <FIX_TAG> has anything to do.** It does if your manifest has ANY finding (your own or carried forward), or if the PR carries an unaddressed comment from a bot, CI, or a human:
     gh pr view "$PR" --json comments,reviews

   - **Nothing at all** - no findings, no open comments:
       echo "SKIPPED: nothing to address" > <WS>/state/<FIX_TAG>.status
       echo "<TAG> posted no findings and the PR has no open comments" > <WS>/state/<FIX_TAG>.summary
       echo "<NEXT_AFTER_FIX>" > <WS>/state/<FIX_TAG>.next
       echo "<NEXT_AFTER_FIX>" > <WS>/state/<TAG>.next
     No fixer will take the PR out of draft, so you do it: make sure the PR description reflects everything the sprint delivered, then `gh pr ready "$PR"`. Never wait for CI and never read it: the async CI ticket starts by itself once <FIX_TAG> has a status, and nothing waits for it. <NEXT_AFTER_FIX> is the tester, or empty when no test session was chosen.

   - **Anything to fix** - always a fresh fixer, because its rendered prompt carries the acceptance gate:
       echo "<FIX_TAG>" > <WS>/state/<TAG>.next
       bash <WS>/launch.sh <WS> <FIX_TAG>

3. `echo "DONE" > <WS>/state/<TAG>.status` (or `BLOCKED: <reason>`). LAST. Never `RELAYED` unless you actually relayed.

Post a summary as your last message: findings by severity, each reviewer's ready-to-merge verdict and "Declined to judge" list by roster row, any reviewer that did not finish, which issues you confirmed and which you found wrong, what you deferred, what you rejected and why, what you carried forward and what later work had already resolved (REVIEW-FINAL), what runs next, and anything needing a human decision in the morning.
