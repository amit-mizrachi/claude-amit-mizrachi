# Sources

`reviewer-prompt.md` is written fresh, combining ideas from three public, widely used review guides. It is not a verbatim copy of any of them.

- **obra/superpowers**, `skills/requesting-code-review/code-reviewer.md` (MIT): https://github.com/obra/superpowers
  We use its single senior reviewer, its read-only and no-sub-agent rules, the "Declined to judge" list, and the Strengths / Critical / Important / Minor / Assessment format.
- **anthropics/claude-code**, `plugins/pr-review-toolkit/agents/code-reviewer.md`: https://github.com/anthropics/claude-code
  We use the 0-100 confidence score on each issue and the check against project guidelines. Deviation: we report >= 50, not >= 80.
- **google/eng-practices**, `review/reviewer/looking-for.md` (CC-BY 3.0): https://github.com/google/eng-practices
  We use its checklist: design, functionality, complexity, tests, naming, comments, style, consistency, documentation, every line, context.

# Why this replaced squad-review (Oct 2026 benchmark)

Six squad-reviewed commits from the week of Oct 18, 2026 were replayed at their exact heads. Each got one blind Opus 5.5 agent at high effort running this method. An independent judge then rated every real issue from both reviews on one High/Med/Low/Nit scale.

| | Single reviewer | Squad |
|---|---|---|
| High | 3 | 1 |
| High + Med | 17 | 10 |
| Real share of findings | 93% | 46% |
| Median time per review | 9.4 min | 4.8 min |

The single reviewer also caught the Has Reports bug that later escaped to the PR reviewer, and a sensitive-value exposure in Cmd+K. The squad found more Low and Nit cleanups.

Report: https://claude.ai/artifact/WXVQZHWkRJeGNB2a8xJAAb
