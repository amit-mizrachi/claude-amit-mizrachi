---
name: customer-reply-draft
label: "Draft a reply to the customer"
folder: "DoD"
description: "Writes a paste-ready reply that the CSM sends to the customer, built from the answer you already gave in this conversation. Open it when the CSM says yes to \"Want me to draft a reply to the customer?\", or asks \"what should I answer?\", \"draft a reply\", \"write to the customer\" or similar, in any language."
---

# Draft a reply to the customer

The CSM pastes your draft to the customer as it is. The customer is not technical, does not
know how Shapes works inside, and may be upset. Write so that one read is enough.

## Before you write

- Build the draft from your last answer in this conversation: its verdict, its label
  (Confirmed, Likely or Not sure) and its steps. Add no fact that is not in this conversation.
- No answer yet in this conversation: say so to the CSM in one line and triage the case first.
- The CSM gave a new fact since your answer: use it, and say in one line to the CSM what
  changed.

## The draft

A short greeting, then four parts in this order, then one closing line. At most 120 words.

1. **What we found.** One or two sentences.
2. **Why.** One sentence in plain words.
3. **What you can do.** Numbered steps, with the screen, menu and button names the customer sees
   in the app. Say the side effect of every setting plainly, in the same step: "This also lets
   them edit and run these workflows."
4. **What we will do.** Only what CS really does next, for example "We will check this and
   come back to you by email." Leave this part out when CS does nothing more.

## Rules

- **Language:** the customer's language, from their own words in this conversation. The CSM
  asks for another language: use that one. You cannot tell: use the CSM's language.
- **Confidence:** a Confirmed fact is a fact. A Likely or unchecked fact stays "it appears
  that" or "it looks like". Not sure: say "we are checking" and give no cause. Never turn a
  guess into a fact, and never promise a fix, a date or a developer action that nobody agreed to.
- **No internal terms:** no account, user, role or view ids; no tool, log, database, code,
  ticket, board, Dev of the Day, Benny or agent names; no evidence links; no Slack links; no
  other customer. Say "the user" or "your employee" where you would write an id.
- **Warm and short:** thank them once, do not blame them ("the setting is off", not "you did
  not turn on the setting"), and do not apologise more than once.
- **No tags:** no @mention and no escalation tag in a draft.

## What you send to the CSM

One line to the CSM ("Here is a draft you can paste:"), then the draft as a block quote (every
line starts with `>`). Nothing after the draft, except one line when the draft carries a Likely
or Not sure fact: "Unconfirmed in the draft: <the fact>."

## Example

The answer was "By design: the user has no access to these workflows. Likely." with the role
setting and the Subscribers option as next steps.

> Hi, thank you for your patience.
> We checked the shared view. The view works. It appears that the user does not have access to these workflows, so the view shows an empty list.
> This is because a shared view shows each person only the data they are allowed to see.
> What you can do:
> 1. To let the user see all these workflows, an admin goes to Account Settings > Permissions, opens the user's role, and turns on "Manage employees' workflows" under Workflows. This also lets the user edit and run those workflows.
> 2. To give view access only, add the user to "Subscribers" on each workflow they must see.
> Let us know if you want help with either option.

Unconfirmed in the draft: that the user's role has no workflow access.
