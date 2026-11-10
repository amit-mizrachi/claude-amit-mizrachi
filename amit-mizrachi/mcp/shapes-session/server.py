#!/usr/bin/env python3
"""shapes-session - a local stdio MCP server that lets Claude Code work inside one
internal Shapes account, using the token from a pasted Scale "login as" link.

The link looks like `<app origin>?token=<jwt>&isSystemUser=true`. The token lives
1 hour and has no refresh token, so a session lasts as long as the link does. The
server holds at most one session, in memory only, and refuses any account whose
`isInternal` is not true. The token never appears in a tool result, an error or
on stderr.

Zero dependencies. Python 3.9+.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
# endpoints and constants
# --------------------------------------------------------------------------- #

API_URL_ENV = "SHAPES_SESSION_API_URL"

# app origin of a login-as link -> io-server GraphQL URL (Apollo is mounted at /api)
ORIGIN_TO_API = {
    "https://app.shapes.co": "https://api.shapes.co/api",
    "http://localhost:8000": "http://localhost:4000/api",
}

HTTP_TIMEOUT = 60

CONNECT_QUERY = """query ShapesSessionConnect {
  me { id email }
  fetchAppConfig { currentAccount { id name isInternal } }
}"""

NEW_LINK_HINT = "Paste a new Scale \"login as\" link and call shapes_connect."

# The one open session, or None. Keys: token, graphql_url, account_id, account_name,
# user_id, user_email, is_internal, exp. The token is set to None once it expires.
SESSION = None


def log(msg: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for the MCP protocol. Never log the token."""
    print(f"[shapes-session] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# the login-as link and its token
# --------------------------------------------------------------------------- #


def origin_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def token_from_link(link) -> str | None:
    """The `token` query parameter of a link, or None. Never raises."""
    if not isinstance(link, str):
        return None
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(link.strip()).query).get("token")
    except ValueError:
        return None
    return values[0].strip() if values and values[0].strip() else None


def jwt_claims(token: str) -> dict | None:
    """The JWT payload, decoded without a signature check (only for display and the local stop)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    segment = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    except (ValueError, UnicodeError):
        return None
    return claims if isinstance(claims, dict) else None


def graphql_url_for(origin: str) -> str:
    """The GraphQL URL for a link origin: the env override first, then the built-in map."""
    override = os.environ.get(API_URL_ENV, "").strip()
    if override:
        return override
    url = ORIGIN_TO_API.get(origin)
    if not url:
        known = ", ".join(sorted(ORIGIN_TO_API))
        raise ValueError(
            f"Refused: no GraphQL endpoint is known for {origin} (known origins: {known}). "
            f"Set {API_URL_ENV} to the full io-server GraphQL URL (for example "
            f"https://api.shapes.co/api) in this MCP's environment and restart Claude Code. "
            "Nothing was sent.")
    return url


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def clock(epoch: float) -> str:
    return time.strftime("%H:%M UTC", time.gmtime(epoch))


def minutes_left(exp: float) -> int:
    return max(0, int((exp - time.time()) // 60))


# --------------------------------------------------------------------------- #
# talking to io-server
# --------------------------------------------------------------------------- #


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a followed redirect would carry the bearer token to another URL


OPENER = urllib.request.build_opener(_NoRedirect)


def post_graphql(url: str, token: str, query: str, variables: dict | None = None):
    """POST one GraphQL request as the link's user.

    Returns (HTTP status, parsed JSON body or None, raw body text). Raises ValueError
    only when io-server cannot be reached at all. Never retries.
    """
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "shapes-session-mcp",
    })
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            raw = exc.read()
        except OSError:
            raw = b""
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ValueError(f"could not reach io-server at {host_of(url)}: {reason}") from None
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return status, parsed, text


def graphql_error_summary(parsed) -> str:
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    if not errors:
        return ""
    first = errors[0] if isinstance(errors[0], dict) else {"message": str(errors[0])}
    code = (first.get("extensions") or {}).get("code")
    message = str(first.get("message", "unknown error"))[:300]
    return f"{message} ({code})" if code else message


# --------------------------------------------------------------------------- #
# the session
# --------------------------------------------------------------------------- #


def session_state() -> str:
    """'none', 'expired' or 'live'. Drops the token the moment its exp has passed."""
    if SESSION is None:
        return "none"
    if SESSION["token"] is None or SESSION["exp"] <= time.time():
        SESSION["token"] = None
        return "expired"
    return "live"


def describe(session: dict, headline: str) -> str:
    return "\n".join([
        headline,
        f"account id:    {session['account_id']}",
        f"account name:  {session['account_name']}",
        f"user email:    {session['user_email']}",
        f"isInternal:    {json.dumps(session['is_internal'])}",
        f"graphql host:  {host_of(session['graphql_url'])}",
        f"minutes left:  {minutes_left(session['exp'])} (expires {clock(session['exp'])})",
        "The session lasts as long as the link (1 hour) and cannot be refreshed. "
        "When it ends, ask the user for a new login-as link.",
    ])


def not_connected_text() -> str:
    return f"not connected - no Shapes session is open. {NEW_LINK_HINT}"


def expired_text(session: dict) -> str:
    return (f"expired - the session for account {session['account_name']} "
            f"(id {session['account_id']}) ended at {clock(session['exp'])}. {NEW_LINK_HINT}")


# --------------------------------------------------------------------------- #
# tool definitions
# --------------------------------------------------------------------------- #

SESSION_NOTE = ("A session is bound to one internal Shapes account and lasts 1 hour "
                "(the life of the login-as link); there is no refresh.")

TOOLS = [
    {
        "name": "shapes_connect",
        "description": (
            "Open a session inside one internal Shapes account from a Scale \"login as\" link "
            "(`<app origin>?token=<jwt>&isSystemUser=true`). Pass the link exactly as the user "
            "pasted it. The server checks with io-server that the account is internal and "
            "refuses any account that is not. On success it answers with the account id and "
            "name, the user email, isInternal, the GraphQL host and the minutes left. "
            f"{SESSION_NOTE} A new connect replaces the old session. Never repeat the link or "
            "its token back to the user."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["link"],
            "additionalProperties": False,
            "properties": {
                "link": {"type": "string",
                         "description": "The full login-as link copied from Scale."},
            },
        },
    },
    {
        "name": "shapes_whoami",
        "description": (
            "Show the open Shapes session: account id and name, user email, isInternal, "
            "GraphQL host and minutes left. Says `not connected` or `expired` in plain words "
            f"when there is no usable session. {SESSION_NOTE} Check the minutes left before a "
            "long batch of work."
        ),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "shapes_disconnect",
        "description": (
            "Close the Shapes session and forget its token now, before its 1 hour ends. "
            f"{SESSION_NOTE}"
        ),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


# --------------------------------------------------------------------------- #
# tool implementations
# --------------------------------------------------------------------------- #


def tool_connect(args: dict) -> str:
    global SESSION
    SESSION = None  # a connect attempt always drops the old session, even when it fails

    link = args.get("link")
    if not isinstance(link, str) or not link.strip():
        raise ValueError("Refused: pass the login-as link as `link`.")
    origin = origin_of(link.strip())
    if not origin.startswith(("http://", "https://")) or origin.endswith("://"):
        raise ValueError("Refused: `link` is not an http(s) URL. Pass the login-as link "
                         "exactly as Scale copies it.")
    token = token_from_link(link)
    if not token:
        raise ValueError(f"Refused: the link for {origin} has no `token` parameter. Copy the "
                         "login-as link from Scale again; it ends in `?token=...&isSystemUser=true`.")
    url = graphql_url_for(origin)

    claims = jwt_claims(token)
    exp = claims.get("exp") if claims else None
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        raise ValueError(f"Refused: the token in the link for {origin} is not a readable JWT "
                         "with an `exp` claim. Nothing was sent.")
    if exp <= time.time():
        raise ValueError(f"Refused: the link for {origin} expired at {clock(exp)}. "
                         f"Nothing was sent. {NEW_LINK_HINT}")

    status, parsed, _ = post_graphql(url, token, CONNECT_QUERY)
    data = parsed.get("data") if isinstance(parsed, dict) else None
    account = ((data or {}).get("fetchAppConfig") or {}).get("currentAccount")
    me = (data or {}).get("me") or {}
    if status == 401:
        raise ValueError(f"Refused: io-server at {host_of(url)} rejected the token (HTTP 401). "
                         f"The link may be expired or revoked. {NEW_LINK_HINT}")
    if status != 200 or not isinstance(account, dict):
        detail = graphql_error_summary(parsed) or f"HTTP {status}, no current account in the answer"
        raise ValueError(f"Refused: io-server at {host_of(url)} did not confirm the account: "
                         f"{detail}. The token was dropped; no session is open.")

    account_id, account_name = account.get("id"), account.get("name")
    if account.get("isInternal") is not True:
        log(f"refused non-internal account {account_id}")
        raise ValueError(
            f"Refused: account {account_name} (id {account_id}) is not an internal account "
            f"(isInternal: {json.dumps(account.get('isInternal'))}). shapes-session only works "
            "inside internal accounts. The token was dropped; no session is open.")

    SESSION = {
        "token": token,
        "graphql_url": url,
        "account_id": account_id,
        "account_name": account_name,
        "user_id": me.get("id"),
        "user_email": me.get("email"),
        "is_internal": True,
        "exp": float(exp),
    }
    log(f"connected to internal account {account_id} via {host_of(url)}")
    return describe(SESSION, "connected to an internal Shapes account")


def tool_whoami(args: dict) -> str:
    state = session_state()
    if state == "none":
        return not_connected_text()
    if state == "expired":
        return expired_text(SESSION)
    return describe(SESSION, "connected")


def tool_disconnect(args: dict) -> str:
    global SESSION
    if SESSION is None:
        return "not connected - there was no session to close."
    closed = SESSION
    SESSION = None
    log(f"disconnected from account {closed['account_id']}")
    return (f"disconnected - the session for account {closed['account_name']} "
            f"(id {closed['account_id']}) is closed and its token is forgotten.")


HANDLERS = {
    "shapes_connect": tool_connect,
    "shapes_whoami": tool_whoami,
    "shapes_disconnect": tool_disconnect,
}


def scrub(text: str, args: dict) -> str:
    """Remove every token this server knows of from a message before it leaves the process."""
    for secret in (SESSION and SESSION.get("token"), token_from_link(args.get("link"))):
        if secret:
            text = text.replace(secret, "[token]")
    return text


# --------------------------------------------------------------------------- #
# MCP plumbing (JSON-RPC 2.0 over stdio, line delimited)
# --------------------------------------------------------------------------- #


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "shapes-session", "version": "0.1.0"},
            "instructions": (
                "Works inside one internal Shapes account as the user of a pasted Scale "
                "\"login as\" link. shapes_connect(link) opens the session, shapes_whoami shows it "
                "and its minutes left, shapes_disconnect closes it. A session lasts 1 hour and "
                "cannot be refreshed; when a tool says `not connected` or `expired`, ask the user "
                "for a new login-as link. Never repeat the link or its token."
            ),
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            raise ValueError(f"unknown tool {name!r}")
        try:
            text = fn(args)
        except Exception as exc:  # surface as a tool error, not a protocol error
            message = scrub(str(exc), args)
            log(f"tool {name} failed: {type(exc).__name__}: {message}")
            return {"content": [{"type": "text", "text": f"shapes-session error: {message}"}],
                    "isError": True}
        return {"content": [{"type": "text", "text": scrub(text, args)}]}
    if rid is None:
        return None
    raise LookupError(f"method not found: {method}")


def main() -> None:
    log("ready - no session open")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        try:
            result = handle(req)
        except LookupError as exc:
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": str(exc)}})
            continue
        except Exception as exc:
            log(f"request failed: {type(exc).__name__}")
            if rid is not None:
                send({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": -32603, "message": str(exc)}})
            continue
        if rid is not None and result is not None:
            send({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
