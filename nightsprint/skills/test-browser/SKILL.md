---
name: test-browser
description: Exercise a UX-affecting change in a real Chrome browser via `agent-browser` before claiming the task is done. Use whenever a code change affects what a user sees or clicks - new UI, a layout / styling tweak, a role-or-permission-gated surface, an empty / error / loading state, a form flow. Triggers on "test in the browser", "test browser", "exercise the UI", "screenshot the change", "walk the golden path", "validate UX", or any moment a frontend edit needs visual confirmation that the green test suite cannot provide. Covers both clean-Chrome flows and logged-in flows via a persistent Chrome profile.
allowed-tools: Bash, Read
---

# Test Browser

Type-checks and unit tests verify code, not UX. Any change that affects what a user sees or clicks must be exercised in a real browser before claiming the task is done.

It needs the `agent-browser` CLI (`brew install agent-browser`, then `agent-browser install` once to fetch its browser). If `command -v agent-browser` finds nothing, say so and stop: do not substitute a different tool silently. Headless is the default - no Chrome window pops up unless you pass `--headed`.

## When to use

- New UI, layout shift, copy change, styling tweak - anything visual.
- The role / permission / feature-flag variant the change targets (default state + the off-by-default state).
- Empty state, error state, loading state, the "no data yet" path.
- Before/after screenshots for a PR description.

Skip when: backend-only change, the bug is reproducible from code reading alone, or the user explicitly says "don't bother running it."

## Logged-in flows (cookies, OAuth, real account data)

Use a **dedicated persistent profile**. Log in once by hand, then every later run is
already authenticated:

```bash
# One-time, interactive: a real window opens, YOU log in, then leave it.
agent-browser --session app --profile ~/.agent-browser-profiles/app --headed open https://app.example.com/login

# Every run after that - login state persists (cookies, IndexedDB, service workers).
agent-browser --session app --profile ~/.agent-browser-profiles/app open https://app.example.com/dashboard
```

Ask the user to do the one-time login; do not attempt to type their credentials. With no human in the session (a night run), use a profile somebody already logged into; if there is none, test what needs no login and report the logged-in steps as not run, with the reason.

### Avoid `--auto-connect`

`--auto-connect` scans for a CDP port and attaches to whatever answers. If your local dev
stack runs a Node inspector (for example `workerd` or `node --inspect` on **127.0.0.1:9229**),
it attaches to that instead of a browser and fails with:

```
✗ CDP error (Target.setDiscoverTargets): 'Target.setDiscoverTargets' wasn't found
```

Attaching to the user's *running* Chrome is also a dead end: Chromium 136+ refuses
remote debugging on a default profile ("DevTools remote debugging requires a
non-default data directory"), and their Chrome is not started with a debug port.
Use the persistent-profile recipe above instead.

### Alternative: snapshot auth state to a file

Only works against a browser that already exposes a real CDP port:

```bash
agent-browser --cdp <port> state save ./auth.json
agent-browser --state ./auth.json open https://app.example.com/dashboard
```

## Workflow

1. **Boot the stack** the way the repo documents it: the boot command or dev-environment skill named
   in the task (night-sprint's `PLAN.md` names it), else the repo's `AGENTS.md`, `CLAUDE.md` or
   README. Wait until it serves before testing - a stack still coming up looks the same as a broken
   one. Note the client port from the output (or `lsof -iTCP -sTCP:LISTEN -P`).

2. **Drive it.** Each command runs against the persistent agent-browser daemon - no need to re-open between commands:

   > **Launch-time flags bind only when the daemon starts.** `--profile`, `--headed`,
   > `--state`, `--cdp`, `--args` are silently dropped on an already-running daemon:
   > `⚠ --profile ignored: daemon already running`. Put them on the FIRST command of a
   > session, or run `agent-browser --session <name> close` first. Use `--session <name>`
   > to keep unrelated runs from colliding.

   ```bash
   agent-browser open http://localhost:<CLIENT_PORT>
   agent-browser snapshot                 # accessibility tree -> @e1, @e2, ...
   agent-browser click @e<n>              # use refs from the snapshot, not CSS selectors
   agent-browser fill @e<n> "some text"
   agent-browser screenshot out.png       # attach to PR / share with user
   agent-browser console                  # check for runtime errors you didn't intend
   agent-browser errors                   # surfaces page errors specifically
   agent-browser close
   ```

3. **Walk the golden path AND the obvious edge cases.** Empty state, error state, the variant the change targets. One screenshot per state if it's PR-bound.

4. **Watch for regressions.** After each meaningful interaction, run `agent-browser console` / `agent-browser errors`. A new "Uncaught TypeError" in console is a regression even if the screen looks fine.

5. **Honest failure mode.** If you cannot reach the UI (auth wall, missing seed data, env won't boot, route 404s), say so explicitly. Do not claim success from a passing test suite alone.

## When you need the full command reference

agent-browser ships its own skill docs that stay version-matched to the binary. Prefer these over guessing:

```bash
agent-browser skills get core --full     # full command reference + workflow patterns
agent-browser skills list                # specialized skills (electron, slack, dogfood, ...)
agent-browser skills get dogfood         # systematic exploratory testing for bug-hunting passes
```

Read those first if you hit a command shape you don't recognize.

## Tips

- Refs (`@e1`, `@e2`) come from `snapshot` and are stable across that snapshot only - re-snapshot after navigation or significant DOM change.
- `agent-browser screenshot` defaults to a sensible viewport; pass `--full-page` for long scrolling pages.
- The daemon persists across commands - don't `close` between every step, only when the session is genuinely done, or when you need to change a launch-time flag (see the callout in step 2).
- `agent-browser doctor` is the first move when anything looks wrong; it ends in a `N pass, N warn, N fail` summary and `--fix` repairs common breakage.
- `agent-browser profiles` lists the real Chrome profiles on this machine - useful for knowing which account a login belongs to. Don't point `--profile` at a live Chrome profile while Chrome is running; use a dedicated dir under `~/.agent-browser-profiles/`.
- For right-to-left languages: take the screenshot, then check where `dir="rtl"` is set - on the element that needs it, or on the whole document - matches what the change intended.
