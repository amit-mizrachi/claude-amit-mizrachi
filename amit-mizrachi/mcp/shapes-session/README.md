# shapes-session

A local MCP server that lets Claude Code work inside one **internal** Shapes account, as the
user of a Scale "login as" link you paste. It is for filling internal accounts that Forge or
Scale created with realistic data - employees, departments, surveys, reviews, workflows - the
way Forge does, but driven by Claude.

It never holds the io-server admin token, never creates accounts, and never writes the token
to disk. It refuses any account whose `isInternal` is not `true`.

## Install

It ships with the `amit-mizrachi` plugin and registers itself from the plugin's `.mcp.json`
(`python3 ${CLAUDE_PLUGIN_ROOT}/mcp/shapes-session/server.py`). Install or update the plugin,
start a new session, and `/mcp` shows `plugin:amit-mizrachi:shapes-session` with five tools.

It needs `python3` (3.9+, no packages - the one macOS ships is enough). Nothing else to set up:
no key, no config. You paste a link each time you use it.

## Getting a link

1. Create the account with Forge or Scale, as today.
2. In Scale, copy the "login as" link for that account's user ("copy login link").
3. Paste it into Claude Code and ask Claude to connect with it.

The link looks like `<app origin>?token=<jwt>&isSystemUser=true`. Pass it exactly as Scale
copies it; the server reads the `token` parameter itself. A raw token on its own, or an
email and password, is not accepted.

io-server does not mint a login-as link for protected accounts (Shapes in Shapes) or Scale host
accounts, so those cannot be reached this way at all.

## Tools

| Tool | What it does |
|---|---|
| `shapes_connect` | Open a session from a login-as link. Checks with io-server that the account is internal, then answers with the account id and name, user email, `isInternal`, GraphQL host and minutes left. A new connect replaces the old session. |
| `shapes_whoami` | Show the open session and its minutes left, or say `not connected` / `expired` in plain words. Makes no network call. |
| `shapes_graphql` | Run any GraphQL query or mutation in the account, as the link's user. Answers with io-server's `{data, errors}` as JSON text. |
| `shapes_schema` | Look up the schema one type at a time: no argument lists the root `Query` and `Mutation` fields; `type_name` shows one type's fields, input fields or enum values. |
| `shapes_disconnect` | Close the session and forget the token before the hour ends. |

### Parameters

- `shapes_connect(link)` - the full login-as link.
- `shapes_graphql(query, variables?)` - one GraphQL document, and an optional JSON object for
  its variables.
- `shapes_schema(type_name?)` - one type name, such as `Employee` or `CreateDepartmentInput`.
  A wrapped name such as `[Employee!]!` is looked up by its named type. An unknown name answers
  `no such type` with close names.

### Limits

- **One session, one account, 1 hour.** The session lives as long as the link's token: 1 hour
  from when Scale made it. `shapes_connect` reads the expiry from the token itself and every
  other tool refuses once it has passed, so Claude asks you for a new link instead of sending
  calls that would fail.
- **No refresh.** A login-as token comes without a refresh token (io-server refreshes only from
  its refresh cookie, which the link does not carry), and the Shapes web app itself ends a
  login-as session after 60 minutes. When the hour is up, paste a new link.
- **A 401 ends the session.** An HTTP 401, or a GraphQL `UNAUTHENTICATED` /
  `REFRESH_TOKEN_INVALID` code, closes the session at once and the tool says
  `session expired or rejected`. Claude does not retry it.
- **No retries.** Every request is sent once. A mutation that timed out may still have run, so
  check before running it again.
- **Answers are cut at 100 000 characters.** A longer `shapes_graphql` answer is cut, and the
  result says so and gives the full length. Ask for fewer fields or a smaller page.
- **The schema is read once per session** (one introspection query, on the first
  `shapes_schema` call) and cached. A new connect or a disconnect drops it.
- **Requests time out after 60 seconds.**
- **Mutations are not filtered.** The link's user is a super admin of an internal account, so
  any mutation runs, deletes included.

## Endpoints

The server picks the io-server GraphQL URL from the link's origin:

| Link origin | GraphQL URL |
|---|---|
| `https://app.shapes.co` | `https://api.shapes.co/api` |
| `http://localhost:8000` (local `make dev`) | `http://localhost:4000/api` |

Any other origin is refused before anything is sent, so a token never goes to a host the server
does not know. To reach another stack (the eval stack, for example), set
`SHAPES_SESSION_API_URL` to the full GraphQL URL in the MCP's environment and restart Claude
Code. When it is set, it wins over the table for every link.

Every request is `POST <GraphQL URL>` with `Authorization: Bearer <token>` and a JSON body
`{query, variables}`, the same as Forge's GraphQL client. Redirects are not followed, so the
token cannot be carried to another URL.

## The internal-only rule

On connect the server sends one query:

```graphql
query ShapesSessionConnect {
  me { id email }
  fetchAppConfig { currentAccount { id name isInternal } }
}
```

If `isInternal` is not `true`, or the query fails, connect is refused, the refusal names the
account id and name, and the token is forgotten at once. A login-as token is bound to one
account, so this one check covers the whole session. A failed connect also closes any session
that was open before it.

## Keeping the token secret

The token is a live credential for the account. It is held in process memory only and is never
written to disk. It appears in no tool result, no error and no stderr line: any answer from
io-server that echoes it back is scrubbed to `[token]` before it leaves the server. Errors name
the link's origin or the GraphQL host, never the link itself. The tool descriptions also tell Claude never to repeat the link or
its token.

## Behaviour worth knowing

- **Some features are blocked in a login-as session.** io-server turns some features off for a
  login-as user (for example employee files in the people header). If Claude hits one, it is a
  server rule, not a bug in this MCP.
- **Read `errors` even when `data` is there.** `shapes_graphql` passes GraphQL `errors` through
  next to `data`, and a partial failure shows up only there.
- **Check the minutes left before a long batch.** `shapes_whoami` answers at once, with no
  network call.

## Tests

`test_server.py` starts `server.py` as a subprocess, speaks JSON-RPC to it the way Claude Code
does, and points it at a fake io-server on `127.0.0.1` with `SHAPES_SESSION_API_URL`. Tokens
are made-up unsigned JWT-shaped strings; nothing talks to a real Shapes host. CI runs it on
every pull request (Python 3.9 and a current Python):

```
cd amit-mizrachi/mcp/shapes-session && python3 -m unittest -v test_server
```

## Troubleshooting

- `/mcp` shows it failed: run `python3 <plugin root>/mcp/shapes-session/server.py` directly - it
  should sit there waiting on stdin and print `[shapes-session] ready - no session open` to
  stderr.
- `no GraphQL endpoint is known for <origin>`: the link is not from production or local
  `make dev`. Set `SHAPES_SESSION_API_URL` (see Endpoints).
- `not an internal account`: the link is for a customer account. Copy the link for an internal
  account instead.
- `expired` or `session expired or rejected`: the hour is up or io-server no longer takes the
  token. Copy a new link from Scale and connect again.
