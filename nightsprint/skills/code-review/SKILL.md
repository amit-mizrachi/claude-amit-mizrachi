---
name: code-review
description: "Review a change through only the lanes it earns - correctness always, plus security, architecture, observability, performance, reuse, simplification or prompt where the diff gives them something to find - with one bundled reviewer agent per lane, then verify, dedupe and rank the findings. Presets: `quad` (correctness, security, architecture, simplification) and `full`. Use when the user or a calling skill says \"code review\", \"review this branch\", \"review the PR\", \"quad review\", \"review with lanes\", or when night-sprint's FIND step runs its review. Reports findings; never edits code."
argument-hint: "[PR number or URL | branch | <base>..<head>] [lanes: <lane>,<lane> | quad | full]"
---

# Code review

Review one body of work and report the problems a human would want to know about before it
merges. The skill finds; it does not fix. A caller that wants fixes (night-sprint's FIX step,
`address-review`, a human) takes the report from here.

**Report demonstrable problems only.** A finding is a regression with a concrete failure path, or
a requirement the change says it meets and does not. Style preferences, elective refactors and
"consider adding" notes are not findings. A short list that is all real beats a long one that
somebody has to triage at 3am.

## 1. Resolve what is under review

Read the argument, in this order:

| Argument | Base | Head |
|---|---|---|
| PR number or URL | the PR's base branch (`gh pr view <n> --json baseRefName,headRefName`) | the PR head |
| `<base>..<head>` | `<base>` | `<head>` |
| a branch name | `git merge-base origin/<default> <branch>` | `<branch>` |
| nothing | `git merge-base origin/<default> HEAD` | `HEAD`, plus uncommitted changes |

`<default>` is `git symbolic-ref --short refs/remotes/origin/HEAD` without the `origin/`.
Record the base and head SHAs. Then collect, once, what every lane needs:

- `git diff --stat <base>...<head>` and the list of changed files.
- The intent: the PR body, the spec or ticket the caller names, or the commit messages.
- The repo's own rules: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md` and the docs they point to.
  A finding that contradicts a documented convention of this repo is wrong, not the code.

## 2. Pick the lanes

`lanes:` from the caller wins: a list, `quad` (correctness, security, architecture,
simplification) or `full` (every lane below except `prompt`, which is added only for prompt
files). Without `lanes:`, correctness always runs and each other lane runs only when the diff
gives it something to find:

| Lane | Agent | Add it when the diff |
|---|---|---|
| correctness | `correctness-reviewer` | ALWAYS. Bugs, races, type holes, error paths, test quality |
| security | `security-reviewer` | touches authn or authz, parses untrusted input, handles a secret or token, crosses a network or process boundary, builds a query, command or path from user data, changes CORS or origin checks |
| architecture | `architecture-reviewer` | changes a contract, schema, public interface, deployment topology or cross-service call |
| observability | `observability-reviewer` | adds or changes logging, spans, metrics, alerts, or an error-handling path |
| performance | `performance-reviewer` | adds a query, a loop over data that grows, I/O on a hot path, a cache, or a large payload |
| reuse | `reuse-reviewer` | adds general-purpose logic, or reimplements something the repo already has |
| simplification | `simplification-reviewer` | is a final review, or is large enough that its shape is in question |
| prompt | `prompt-reviewer` | changes a prompt, skill, agent definition or prompt template |

Say which lanes you picked and why in one line. Running every lane on a two-file diff is several
reviewers reading the same code to report nothing.

## 3. Run one reviewer per lane

The agents ship with this plugin as `nightsprint:<agent>`. Start the selected lanes in parallel,
one subagent each, and give every one the same brief:

```
Review <base-sha>..<head-sha> in <repo path>. Lane: <lane>.
Intent: <one paragraph: what the change is supposed to do>.
Changed files: <list>. Repo rules: <paths of AGENTS.md / CLAUDE.md / CONTRIBUTING.md>.
Report only demonstrable problems in your lane, in your output format.
```

When the `nightsprint:` agents are not available (the skill was copied without its plugin), use a
general-purpose subagent and paste the matching file from this plugin's `agents/` folder into the
brief. When the session's own rules say subagents need the user's permission first, or forbid
them, run the lanes one after another in this session instead, reading each agent file as your
instructions for that lane.

## 4. Verify, dedupe and rank

A reviewer's report is a lead, not a verdict. For every finding:

1. **Open the code at the cited line** and confirm the problem is there at `<head-sha>`. Drop it
   if the line does not say what the finding claims.
2. **Check the failure path.** Drop it if you cannot say what input or state makes it go wrong.
3. **Merge duplicates.** Two lanes reporting one root cause is one finding; keep the stronger
   evidence and list both lanes.
4. **Rank** by what happens if it ships: `BLOCKER` (data loss, security hole, broken main path),
   `HIGH` (a real bug users will hit), `MEDIUM` (a bug on an edge path, a missing guard),
   `LOW` (real but minor).

## 5. Report

One block per finding, most severe first. These fields match night-sprint's findings manifest,
so its FIND step can copy them as they are:

```
ID:        F<n>
AT:        <head short sha>
SEVERITY:  BLOCKER | HIGH | MEDIUM | LOW
LANE:      <lane, or lanes joined with +>
WHERE:     <file>:<line>
ISSUE:     <what is wrong, one sentence>
EVIDENCE:  <the failure path or the unmet requirement - why this is real>
ACTION:    <the concrete change that fixes it>
```

Then one line per lane: how many findings it reported, how many survived step 4, and why the rest
were dropped. If nothing survived, say so plainly: "No demonstrable problems in <lanes>."

## Rules

- **Never edit code, commit or push.** Fixing is the caller's step.
- **Post to the PR only when asked.** When asked, post ONE consolidated comment, not one per
  finding.
- **No human in the session** (a background or headless run, or a caller that owns the decisions):
  never ask a question. Decide, and say what you decided in the report.
- **Do not run the test suite** to find problems. Read the diff. If a lane needs to see a
  behaviour, a targeted test file by name is the most it may run.
