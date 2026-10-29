---
created: 2026-03-05
tags: [agents, instructions]
syncs_to: ~/.codex/AGENTS.md
---
# Global Agent Instructions

Source of truth for ~/AGENTS.md; the dotfiles installer copies it to `~/.codex/AGENTS.md`, preserving personal content outside its marked block. Edit here.

---

# Behavioral Rules

## 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building

## 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

## 3. Self-Improvement Loop
- After ANY correction from the user: update the project's master note **Lessons** section with the pattern
- Review lessons at session start for relevant project

## 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant

## 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"

## 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Go fix failing CI tests without being told how

## Core Principles
- **No Laziness**: Find root causes. No temporary fixes.

---

# Context pointers

- **Master notes**: when you start or finish work on a project, or after a user correction, read /Users/amitmizrachi/Documents/development/claude-amit-mizrachi/agents-md/obsidian-master-notes.md.
- **Sprint board**: before reading or writing Amit's Monday sprint board, read /Users/amitmizrachi/Documents/development/claude-amit-mizrachi/agents-md/sprint-board.md.
- **Delegation**: before choosing a subagent type, read /Users/amitmizrachi/Documents/development/claude-amit-mizrachi/agents-md/delegation.md.
