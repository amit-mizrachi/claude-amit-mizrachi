# Night sprint - research mode

Read this when the invocation says `mode: research`, when `facts.env` has `MODE=research`, or
when `product-research` launched you as its conductor. The tickets are research questions, the
work is reading sources, and the deliverable is **one published artifact**, not a PR.

**What does not change.** The runner (`watch.sh`, `advance.sh`, `launch.sh`, `revive.sh`), the
context rungs and the conductor's own relay, one tag one session, nothing interrupts a working
session, classify-then-resume, `EVENTS.log` and the session ledger. Everything SKILL.md says
about those holds word for word.

**What this file replaces in SKILL.md:** Prerequisites, Kickoff, Review cadence and lanes, the
fix route, Acceptance, The manual steps, The PR, and the morning report's items 2 and 9.

## What is different, and why

| Code sprint | Research mode | Why |
|---|---|---|
| a git worktree of the repo, one PR | `<WS>/work`, a **local** git repo with no remote; no PR | sessions still commit, so the runner has a HEAD to diff and the reviver a log to read |
| `VERIFY` = the repo's checks | `VERIFY` = `bash <WS>/research-check.sh <WS>` | every claim must name its source; the review checks the source says it |
| implementer per ticket | researcher per ticket, `research-ticket-prompt.md` | writes `findings/<NN>-<slug>.md` |
| review lanes over the diff | ONE lane, **evidence**, `research-review-find-prompt.md` | re-opens the sources behind the claims |
| fixer, or a handback | always a fresh fixer, `research-review-fix-prompt.md`, or SKIP | the findings files are short; a handback buys nothing |
| optional `TEST`, a detached CI watcher (`ci-watch.sh`) handles CI | `SYNTH` builds and publishes the artifact, runs `research-check.sh --final` | there is no CI; the artifact is the thing delivered |
| asks permission mode and test session | **asks nothing**: `auto`, no test session | the brief was approved before the sprint began |
| connectors as the work needs | connectors **READ ONLY**, always | nothing may post under the user's name at 3am |

## Where the workspace lives - NOT under `~/.claude`

Claude Code guards writes inside `~/.claude`: a background session that uses the Write tool
there stops on a permission prompt nobody is awake to answer. A code sprint gets away with it
because its sessions write into the repo; a research sprint writes its findings and its page
into the workspace. So:

    WS       = ~/claude-research/<slug>
    WORKTREE = ~/claude-research/<slug>/work

## Kickoff

1. **Ask nothing.** `PERMISSION_MODE=auto`, no test session. If anything is ambiguous, decide,
   and write the decision into `LOG.md` for the report.
2. **The tickets.** From `product-research` they are already in `<WS>/tickets/<NN>-<slug>.md`,
   cut by `to-tickets` from `<WS>/spec.md`. Otherwise run `to-spec` and `to-tickets` yourself
   with the same instructions `product-research`'s conductor prompt gives. Each ticket is ONE
   question with acceptance criteria. `TOTAL` is how many there are; 8 at most.
3. **`facts.env`**, one `KEY=VALUE` per line, every value on ONE line:

       MODE=research
       SLUG=<slug>
       USER=<first name>
       WS=<absolute WS>
       WORKTREE=<absolute WS>/work
       BRANCH=research/<slug>
       VERIFY=bash <absolute WS>/research-check.sh <absolute WS>
       RESEARCH_TITLE=<short title>
       QUESTION=<the research question>
       DECISION=<the decision it informs>
       AUDIENCE=<who reads the artifact>
       SOURCES=<allowed sources, e.g. Web (WebSearch, WebFetch); Slack; Google Drive>
       TOTAL=<n>
       PERMISSION_MODE=auto
       CONTEXT_WINDOW=<200000, or 1000000 on a 1M model>
       WARN_AT_USED=20
       RELAY_AT_USED=30
       CEILING_USED=60

4. **Bootstrap**, exactly as SKILL.md says. With `MODE=research` it checks the research fact
   set, creates `<WS>/work` as a local repo on `<BRANCH>`, and pre-answers the runner's one-time
   PR ask, so `NEEDS-PR` never fires.
5. **Render** every prompt now, with `render.sh`:

   | Tag | Template | `vars-<TAG>.env` sets |
   |---|---|---|
   | `T<NN>` | `research-ticket-prompt.md` | `TAG`, `NN`, `TICKET_TITLE`, `GOTCHAS`, `NEXT_TAG`, `TOTAL` |
   | `REVIEW-FINAL` | `research-review-find-prompt.md` | `TAG=REVIEW-FINAL`, `FIX_TAG=FIX-FINAL`, `NEXT_AFTER_FIX=SYNTH` |
   | `FIX-FINAL` | `research-review-fix-prompt.md` | `TAG=FIX-FINAL`, `FIND_TAG=REVIEW-FINAL`, `NEXT_TAG=SYNTH` |
   | `SYNTH` | `research-synth-prompt.md` | `TAG=SYNTH` |
   | continuation | `research-continuation-prompt.md` | filled by the relaying session, not you |

   `GOTCHAS` is the judgement you add per ticket, on one line: which allowed source most likely
   holds the answer, useful search terms, a trap to avoid. `None known.` is a fine value.
6. **Wire the chain:** `T01.next` = `T02` ... `T<TOTAL>.next` = `REVIEW-FINAL`,
   `REVIEW-FINAL.next` = `FIX-FINAL`, `FIX-FINAL.next` = `SYNTH`, `SYNTH.next` empty.
7. **`PLAN.md`** from `research-plan-template.md`, filled from `spec.md`.
8. **Launch `T01`** with `launch.sh`, start the runner with `bash <WS>/runner.sh start <WS>`, arm
   a `Monitor` on `bash <WS>/runner.sh follow <WS>` (re-arm it at every 30-minute expiry), and go
   into the monitor loop.

**One review, at the end.** Research has no seams that break each other the way a schema
change breaks its callers, so there are no checkpoint reviews. `REVIEW-FINAL` always runs.

## The escalations that differ

`NEEDS-PR` never fires. `BLOCKED` on a ticket means no allowed source could answer it: record
it, carry on, and let `SYNTH` show it as a gap - a research run that answers 6 of 7 questions
and says which one it could not is a good result. Everything else in the monitor-loop table is
handled exactly as SKILL.md says.

## Acceptance, and the report

Delivered means `state/ACCEPTANCE.verdict` starts with `PASS` **and** `state/ARTIFACT.url` is a
published URL. `PASS` with `LOCAL-ONLY` is a partial delivery: the page exists on disk but was not
published. Say which in the first line.

Write the report to `<WS>/REPORT.md` and post it as your final message, in this order:

1. **The verdict and the artifact link** - one line each.
2. **The answer** - the research question and the one-line answer, with its confidence.
3. **Ticket outcomes** - every question as answered / partly answered / blocked, with why.
4. **The session ledger**, as SKILL.md describes it.
5. **Review results** - findings corrected, rejected, deferred; sources re-opened.
6. **Time lost** to budget waits, auth stalls, revivals.
7. **Gaps and follow-ups** - `state/FOLLOWUPS.md` and every `## Gaps` entry that matters,
   especially the questions only a person can answer.

Then, if the `PushNotification` tool is available (load it with ToolSearch), send one
notification: `Research ready: <RESEARCH_TITLE> - <artifact URL>`. That is how the user hears
the run finished; they are not watching this session.
