---
name: dod-verdict
label: "Classify a report - the verdict"
folder: "DoD"
description: "Classifies a CSM's report: the fork (product question / issue / request), the outcome class (bug, user mistake, by design, permissions, feature flag, bad data, config, user environment, known issue, duplicate, feature request), product area, severity and routing, and the confidence label Confirmed / Likely / Not sure. Open it for every issue or request before you answer."
---

# Classify a report - the verdict

The verdict goes in line 1 of your reply, so it must be right or honestly labelled. A guess shown as fact is the shared defect behind the worst Benny threads (FireArc "in dev", Sensos "by design", Schillings "missing flag", each corrected by the CSM's next message).

## 1. The fork
| CSM brought you | Sounds like | Path |
|---|---|---|
| Product question | "can it do X?", "how does X work?", "is this expected?" | Answer it. No ticket. No core set. |
| Issue | "X is broken / wrong / missing / stopped" | By-design check, then evidence, then a class. |
| Request | "please change / fix / re-run / enable X" | Capability (feature request) vs operational (DoD). |

The fork is not the ticket's Type label. If you cannot tell a question from an issue, ask "is the customer asking how it works, or telling us it is wrong?". Say the fork in one clause inside the answer, never as a preamble.

## 2. The outcome class
Hold one class as a hypothesis, then prove it with `investigate-incident`. Shares are from 213 real DoD cases.
| Class | Share | Typical proof | Ticket |
|---|---|---|---|
| Bug (code defect) | 24% | A server-class error (`classification: server`, INTERNAL_SERVER_ERROR) for this account and time; the same error on several accounts; a start that matches a release | Yes (R7) |
| Config, cause | 9% | The account's setting explains the report | No (R3) |
| Config change, no UI | 11% | The change needs a developer in the backend | Yes (R8) |
| Data fix | 13% | A wrong, missing or duplicate value on one account; an import or audit row shows where it came from | Yes (R8) |
| User mistake | 11% | BAD_USER_INPUT for this user AND the input breaks a rule the code or an article states; an audit row of a customer change before the report; an import error; the session recording | No (R3) |
| Feature request | 7% | The capability does not exist | No DoD (R2) |
| By design | 5% | A code line or article shows the behaviour is intended | No (R1) |
| Known issue / already fixed | 4% | An open item on the same symptom, or a fix shipped after the report | No (R4) |
| User environment | 3% | RUM status 0, browser errors, an extension, a third-party error, with no backend error | No (R5) |
| Permissions | 1% | FORBIDDEN for this user AND the role lacks the access level; or an empty list with no error that the data area's row rule explains (`references/who-sees-which-rows.md`) | No, unless the role is right and it still fails (R6) |
| Duplicate | 1% | Same account, same symptom, open item | No (R4) |
| Feature flag | 1% | The account's flag is off and the code gates the feature on it | No - CS flips it at https://scale.shapes.co/flags |

`references/examples.md` has worked examples, including the real ones.

**Empty with no error.** A user sees no rows, or fewer rows than a colleague, and no request failed: read `references/who-sees-which-rows.md` before you pick a class. The server sends only the rows the user may see, so this is usually Permissions (by design), not a bug or a filter. Name the exact setting that changes it, with its side effect.

## 3. Confidence - the label in line 1
- **Confirmed** - one log line, database row, code line or ticket shows the mechanism. Write the verdict as a fact.
- **Likely** - the signals agree, but one check is missing. Write "Likely <class>" and name the missing check.
- **Not sure** - the evidence does not settle it. Write "Not sure yet", say what you checked, and recommend a ticket (R9).
Never sharpen or soften a verdict or a severity on a reading you did not take. A source you could not reach is never evidence that "nothing happened".

## 4. The fields a ticket needs
1. **Type:** `Bug` (something is broken) or `Request` (an operational change or data fix).
2. **Domain** (the board label, exact spelling): People directory, Performance review, Surveys, Time managment, Workflow, Assigned tasks, Agent (AI chat), MCP, Vibe views, Dashboards, Integrations, Login / access, Compensation, Mobile. Note the board spells "Time managment".
3. **Account:** the numeric account id, verified (`customer-identity`). A name alone is "unverified".
4. **Affected user:** the user id when the issue is user-scoped.
5. **Severity:** from customer impact and blast radius, not from the word the reporter used. Data integrity and access problems on an HR platform rank high. Unsure between High and Medium: choose High. Unsure about Critical: escalate.

## 5. Routing
- **Capability vs operational:** a new capability the product lacks is a feature request (offer `create_feature_request`). An operational change or data fix belongs on DoD. When in doubt, operational.
- **Account-specific defect:** stays on DoD.
- **Platform bug** (reproduces on any account): Low/Medium -> Bugs board (`create_bug`); High -> DoD at High; Critical -> page R&D on-call first (or VP R&D + Product), then offer a Critical record ticket marked "escalated - record only, details to follow".
- Account-scoped logs prove a failure FOR THIS ACCOUNT. "Does it happen on every account?" comes from the Bugs board, past DoD tickets on other accounts, #releases, or the CSM reproducing it elsewhere - never from reading other accounts' rows. The counts-only check in `investigate-incident` is a lead, not proof.
