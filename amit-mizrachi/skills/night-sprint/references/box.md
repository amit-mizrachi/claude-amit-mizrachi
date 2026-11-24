# The cloud box - how the tester runs the app in mode D

A Shapes cloud dev box is the whole Shapes app (io-client, io-server, its own Postgres and seed data) running
in Cloudflare, checked out at one pushed **shapes-platform** branch. It replaces the laptop stack for the
test session: nothing boots on this machine, nothing competes with the sprint's builds, and the box stays
up after the sprint so the user can open it in the morning. Source: shapes-machina `apps/cloud-dev-env`
(README) and `docs/runbooks/cloud-dev-env-preview.md`.

## What a box covers, and what it does not

- It runs the **shapes-platform** branch you name. A change in another repo is in the box only when that repo
  is already deployed where the box reaches it: the box talks to the **internal** Machina, so a
  shapes-machina branch is not in it until that branch is deployed to internal. Say so in the report as
  "not covered by the box", never as a PASS.
- The branch must be pushed. The sprint's draft PR exists from `T01`, so it is.

## Start it, or reuse it

The tools are the `cloud-boxes` MCP (`cloud_box_*`), acting as the user, so the box is theirs and shows
on their Boxes page in Machina Studio.

1. Look for the box first: `<WS>/state/BOX.id` (an earlier TEST or a relay), then `cloud_box_list` for a
   box on this branch. Use it if its state is `ready` or `asleep` (`cloud_box_start` with
   `if_exists: use` wakes it).
2. Else `cloud_box_start` with `branch: <the platform sprint branch>`, `if_exists: "use"`,
   `name: "night-sprint <slug>"` and `sleep_after_hours: 12`. Nobody can answer the "you already have a
   box" question tonight, so `if_exists: "use"` is the answer. Write the id at once:
   `echo <id> > <WS>/state/BOX.id`.
3. Poll `cloud_box_status` every 60 seconds until `ready`: about 4 to 6 minutes, up to 25 on a fresh
   image snapshot. `failed`: read `cloud_box_logs`, record the error, and go to "When the box will not
   come up".
4. After a later push to the branch (FIX-TEST), bring the box up to date in place:
   `cloud_box_exec` `git pull --ff-only origin <branch>`. Vite hot-reloads the client; restart one server
   only when PLAN.md says it does not reload.

## Walk it

- **Explore** with `cloud_box_browser`: `["login", "admin"]`, `["open", "/path"]`, `["snapshot", "-i"]` for
  element refs, `["click", "@e3"]`, `["screenshot"]`. Use it to find the selectors the recording needs and
  to check a step by eye. Its images reach you only; they are not files.
- **Record** with `bash <WS>/box-capture.sh https://<id>-dev.shapes.services ...` (the RECORDING section of
  your prompt). It drives a Playwright browser on this laptop through Cloudflare Access with the box
  browser's service token (AWS SM `shapes-machina/internal/box-browser-access`, read with the `amit`
  profile, held in the process only), signs in with the seeded preview logins, and writes the
  screenshots, the video and the gallery page.
- `cloud_box_exec` runs a shell command in the box (tests, `psql` on the box's own database, a seed).
  `cloud_box_logs` is the app's preview log.

## Leave it up

Never call `cloud_box_stop`. At the end, set the longest idle timer so it is awake in the morning:
`cloud_box_rename` with `id` and `sleep_after_hours: 12`. A box asleep after that keeps its data, and
opening its link wakes it in about a minute.

Then write this block, filled in, to `<WS>/state/BOX.md` and as the `## Box left up` section of
TEST-REPORT.md. The conductor sends it to the user as it stands, so it must need no thinking:

```
## Box left up
Open:      https://<id>-dev.shapes.services
           (Cloudflare Access asks for your @shapes.co Google account first)
Sign in:   super-admin@shapes.co | admin@shapes.co | manager@shapes.co | employee@shapes.co
Password:  <the seeded preview password: PREVIEW_LOGIN_PASSWORD in shapes-platform .github/workflows/preview-deploy.yml>
Box:       <id> - "<name>" - branch <branch> - <state>
Recording: <the Artifact link from state/TEST.artifact>
Sleeps:    after 12 idle hours, data kept; opening the link wakes it
Stop it:   ask Claude "cloud_box_stop <id>", or the Boxes page in Machina Studio
```

The password is a committed test value the preview deploy already posts to Slack, so it goes in the
block as plain text. The Access token never does.

## When the box will not come up

- The `cloud_box_*` tools are not in your tool list, or they answer 401: the `cloud-boxes` MCP is not
  signed in. Record a manual step (`STEP: sign in to the cloud-boxes MCP: run /mcp in Claude Code, pick
  cloud-boxes, Authenticate`), then fall back.
- The box ends `failed`, or is not `ready` after 25 minutes: record the state and the last
  `cloud_box_logs` lines.
- Fall back to mode A (the laptop stack) only when PLAN.md names its boot command. Else write
  `UNKNOWN cloud box: <why>` to GOLDEN.verdict and test what you can without the app.
