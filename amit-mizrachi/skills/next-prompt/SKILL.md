---
name: next-prompt
description: Generate a continuation prompt for the next task and launch it as a new background agent (visible in the Claude Code Agents screen). Use when the user wants to hand off work to a fresh session, is running low on context, or wants to capture what to do next.
argument-hint: [optional task description]
allowed-tools: Read, Grep, Glob, Bash
---

# Generate Continuation Prompt

Produce a self-contained prompt a fresh Claude Code session can paste in to continue
this work. The job is to **transfer what this session knows** — what was done, what was
decided, what to watch out for, and what's next. The new session can read git, CLAUDE.md,
and the codebase itself; don't spend the prompt re-deriving those. Spend it on the
knowledge that would otherwise be lost when this session ends.

## Gather

- The next task: use `<user-arguments>` if given; otherwise infer from this session's
  work, the Current State / plan notes, or TODO/status sections. If nothing's obvious, ask.
- Absolute paths of the docs the next session should read (CLAUDE.md, specs, plan files).
  If your team keeps prior context in a knowledge vault or wiki, point the next session at
  the specific notes that matter - the service note, the project note, the decision record -
  never at the vault root. A pointer the next session has to go searching from is a pointer
  it will skip.
- The session-specific knowledge: what got done, decisions made, gotchas hit, and any
  in-flight state that isn't written down anywhere yet.

## Emit

Print the prompt in one fenced block so the user can see it, then **launch it as a new
background agent** so it shows up in the Claude Code Agents screen (not the clipboard):

1. Write the prompt body verbatim to a temp file via a quoted heredoc (`<<'PROMPT'` —
   preserves backticks/quotes/newlines; never `echo`):
   ```bash
   f="$(mktemp -t next-prompt)"
   cat > "$f" <<'PROMPT'
   <prompt body here>
   PROMPT
   ```
2. Launch it as a background agent from the repo root, passing the file body as one arg:
   ```bash
   cd "<repo absolute path>" && claude --bg "$(cat "$f")"
   ```
   `--bg` starts the session as a background agent and returns immediately; it appears in
   the Agents screen (manage/list with `claude agents`).
3. Confirm: "Launched in a new background agent — open the Agents screen (or run
   `claude agents`) to jump into it."

Fallback: if `claude` is not on PATH or `--bg` errors, `pbcopy` the prompt body instead and
say "Couldn't launch a background agent — copied to clipboard instead: <reason>."

## Multiple prompts (one per phase / task)

When the user asks for more than one prompt - a prompt **per phase of a plan**, per ticket,
or per task in a sequence - generate **all** the prompts in one go (one fenced block each).
How many to LAUNCH depends on whether the tasks depend on each other:

**Default (dependent phases of one plan): launch only the next actionable one.** Phase 2
often can't start until Phase 1 lands, so starting them all in parallel just creates
conflicting work. Launch Phase 1, save the rest.

**Independent tasks, OR the user explicitly says to launch them all: launch them all.**
If the user says "launch both", "launch all", "start them all", "run them in parallel", or
the tasks are plainly independent (different subsystems, no ordering between them), LAUNCH
EVERY prompt as its own background agent. Do NOT save any for later - an explicit launch
instruction always overrides the save-the-rest default. When they run concurrently against
one checkout, make each prompt tell its session to use an isolated git worktree.

- Produce as many prompts as the work needs - one fenced block per prompt, each a complete,
  self-contained continuation prompt following the template below.
- Launch per the rule above (next-actionable-only when dependent; all of them when
  independent or when the user said to launch all), using the Emit steps for each.
- For any prompt you do NOT launch, write it to its own temp file
  (`mktemp -t next-prompt-phaseN`) and list the path so the user can launch it later with
  `claude --bg "$(cat <path>)"`.
- Close with one line naming what was launched vs saved, e.g. "Launched Phase 1 as a
  background agent; Phases 2-N saved to <paths>" OR "Launched all N prompts as background
  agents: <session ids>."

Template — drop any line whose source doesn't exist:

```
[Project] — [5-10 word task title]

I'm working on [project] — [one line]. Repo: [absolute path] ([owner/repo]).

Read first: [absolute paths — CLAUDE.md, specs, plan, relevant notes]
Done so far: [1-3 lines; reference the state doc, don't repeat it]
Your task: [what to do next]
[Plan at [path], N phases — start Phase X.  |  No plan yet — read [spec], write one first.]
Commands: [build / test / lint]
Gotchas: [conventions + traps hit this session that prevent repeated mistakes]
```

## Rules

- Self-contained · absolute paths only · 200-400 words · reference docs, don't duplicate.
- Lead with the `[Project] — [title]` line; some harnesses use it as the session title.
- Always include the `Gotchas:` line — it's the highest-value part of the handoff.
- Multiple prompts requested -> generate them all; launch per the "Multiple prompts" rule (next-actionable-only for dependent phases, ALL of them for independent tasks or when the user says to launch all). Never save a prompt for later once the user has told you to launch it.
- Describe destructive or restricted operations in prose, not as literal command lines.
  A handoff prompt is guidance, not a script — write "the pre-commit-bypass flag won't
  work here" / "don't force-push this branch" / "avoid hard-resetting" rather than pasting
  the exact command. Clearer for the reader, and avoids shipping copy-pasteable footguns.
