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
import difflib
import json
import os
import socket
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

# seconds; SHAPES_SESSION_TEST_HTTP_TIMEOUT exists only so the tests can wait less
try:
    HTTP_TIMEOUT = float(os.environ.get("SHAPES_SESSION_TEST_HTTP_TIMEOUT", "")) or 60.0
except ValueError:
    HTTP_TIMEOUT = 60.0

# a shapes_graphql answer longer than this is cut, so one call cannot fill Claude's context
MAX_RESULT_CHARS = 100_000

# io-server answers a rejected bearer token with HTTP 200, not 401: its graphql-shield
# fallback returns NotAuthenticatedError ("Not Authenticated", extensions.code 401), and in
# production format-error masks it to a bare "Internal server error" with no code.
# "Not Authorized" shares code 401 but is a permission denial, so it keeps the session.
NOT_AUTHENTICATED_MESSAGE = "Not Authenticated"
MASKED_ERROR_MESSAGE = "Internal server error"

# sent once after a masked error with no data, to tell a dead token from a failed query
PROBE_QUERY = "query ShapesSessionProbe { me { id } }"

CONNECT_QUERY = """query ShapesSessionConnect {
  me { id email }
  fetchAppConfig { currentAccount { id name isInternal } }
}"""

# One standard introspection query (no descriptions, no directives). io-server keeps
# introspection on in production, and the private /api server has no query depth limit.
INTROSPECTION_QUERY = """query ShapesSessionSchema {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      kind
      name
      fields(includeDeprecated: true) {
        name
        isDeprecated
        args { name defaultValue type { ...TypeRef } }
        type { ...TypeRef }
      }
      inputFields { name defaultValue type { ...TypeRef } }
      interfaces { ...TypeRef }
      enumValues(includeDeprecated: true) { name isDeprecated }
      possibleTypes { ...TypeRef }
    }
  }
}

fragment TypeRef on __Type {
  kind
  name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name
    ofType { kind name ofType { kind name ofType { kind name } } } } } } }
}"""

NEW_LINK_HINT = "Paste a new Scale \"login as\" link and call shapes_connect."

# The one open session, or None. Keys: token, graphql_url, account_id, account_name,
# user_id, user_email, is_internal, exp, schema_cache. The token is set to None once it
# expires. schema_cache is filled by the first shapes_schema call and lives and dies with
# the session, so a new connect or a disconnect drops it.
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
        if isinstance(reason, (socket.timeout, TimeoutError)):
            lost = f"no answer from io-server at {host_of(url)} within {HTTP_TIMEOUT:g} s"
        elif isinstance(reason, ConnectionResetError):
            lost = f"io-server at {host_of(url)} dropped the connection without an answer"
        else:
            raise ValueError(f"could not reach io-server at {host_of(url)}: {reason}") from None
        raise ValueError(f"{lost} - the request may have run; check its effect (for example "
                         "with a query) before you send a mutation again.") from None
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


def graphql_errors(parsed) -> list:
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    return errors if isinstance(errors, list) else []


def is_not_authenticated(parsed) -> bool:
    """True when an error is io-server's unmasked NotAuthenticatedError (as dev sends it)."""
    for error in graphql_errors(parsed):
        if not isinstance(error, dict):
            continue
        code = (error.get("extensions") or {}).get("code")
        if str(code) == "401" and error.get("message") == NOT_AUTHENTICATED_MESSAGE:
            return True
    return False


def is_masked_failure(parsed) -> bool:
    """True when there is no data and every error is production's masked "Internal server error"."""
    errors = graphql_errors(parsed)
    if not errors or parsed.get("data") is not None:
        return False
    return all(isinstance(error, dict) and error.get("message") == MASKED_ERROR_MESSAGE
               and not (error.get("extensions") or {}).get("code") for error in errors)


def token_rejection(url: str, token: str, status: int, parsed) -> str | None:
    """How io-server showed it no longer takes the token, or None.

    A masked failure could be a dead token or a query that broke, so it sends one
    PROBE_QUERY: a GraphQL answer without data.me means the token is dead. An
    unreachable or non-GraphQL probe answer proves nothing and keeps the session.
    """
    if status == 401:
        return "answered HTTP 401"
    if is_not_authenticated(parsed):
        return f"answered {NOT_AUTHENTICATED_MESSAGE} (401)"
    if not is_masked_failure(parsed):
        return None
    try:
        probe_status, probe, _ = post_graphql(url, token, PROBE_QUERY)
    except ValueError:
        return None
    me = ((probe.get("data") if isinstance(probe, dict) else None) or {}).get("me")
    if probe_status == 401 or (isinstance(probe, dict) and not me):
        return f"answered {MASKED_ERROR_MESSAGE}, and a `me` probe got no user"
    return None


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


def live_session() -> dict:
    """The open session, or a ValueError (nothing sent) when there is none or it has expired."""
    state = session_state()
    if state == "none":
        raise ValueError(f"Refused: {not_connected_text()} Nothing was sent.")
    if state == "expired":
        raise ValueError(f"Refused: {expired_text(SESSION)} Nothing was sent.")
    return SESSION


def post_in_session(session: dict, query: str, variables: dict | None = None):
    """POST as the session's user. Returns (status, parsed, text).

    An answer that shows io-server no longer takes the token (see token_rejection)
    closes the session and raises a ValueError that asks for a new link. The request
    itself is never sent again.
    """
    global SESSION
    url = session["graphql_url"]
    status, parsed, text = post_graphql(url, session["token"], query, variables)
    ending = token_rejection(url, session["token"], status, parsed)
    if ending:
        SESSION = None
        log(f"session for account {session['account_id']} ended: io-server {ending}")
        raise ValueError(f"session expired or rejected - io-server at {host_of(url)} "
                         f"{ending}, so the session is closed. Paste a new login-as link and "
                         "call shapes_connect; do not retry this call.")
    return status, parsed, text


def cut(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return (f"{text[:MAX_RESULT_CHARS]}\n\n[cut: the full answer was {len(text)} characters; "
            f"only the first {MAX_RESULT_CHARS} are shown. Ask for fewer fields or a smaller page.]")


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
    {
        "name": "shapes_graphql",
        "description": (
            "Run any GraphQL query or mutation in the connected account, as the user of the "
            "login-as link (a super admin of that account). Answers with io-server's "
            "`{data, errors}` as JSON text: read `errors` even when `data` is there, a partial "
            "failure shows up only there. A request is sent once and never retried, so check a "
            "mutation's answer before you run it again. An answer longer than "
            f"{MAX_RESULT_CHARS} characters is cut, and the result says so and gives the full "
            "length; ask for fewer fields or a smaller page then. If the tool says the session "
            "expired or was rejected, ask the user for a new login-as link and do not retry. "
            f"{SESSION_NOTE}"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string",
                          "description": "The GraphQL document: one query or mutation."},
                "variables": {"type": "object",
                              "description": "Values for the document's variables, if it has any."},
            },
        },
    },
    {
        "name": "shapes_schema",
        "description": (
            "Look up the account's GraphQL schema one type at a time, before writing a "
            "shapes_graphql query or mutation. With no argument it lists the root Query and "
            "Mutation fields, each with its argument names and return type. With `type_name` "
            "it shows that type: fields with argument and return types for an object type, "
            "input fields for an input type, values for an enum. Types are written the GraphQL "
            "way (`[Employee!]!`). An unknown name answers `no such type` with close names. "
            "The schema is read once per session and cached; a new connect or a disconnect "
            f"drops it. {SESSION_NOTE}"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type_name": {"type": "string",
                              "description": "One type name, such as \"Employee\" or "
                                             "\"CreateDepartmentInput\". Leave it out to list "
                                             "the root fields."},
            },
        },
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


def tool_graphql(args: dict) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Refused: pass the GraphQL document as `query`. Nothing was sent.")
    variables = args.get("variables")
    if isinstance(variables, str) and variables.strip():
        try:
            variables = json.loads(variables)
        except ValueError:
            pass  # refused just below
    if variables in (None, ""):
        variables = None
    elif not isinstance(variables, dict):
        raise ValueError("Refused: `variables` must be a JSON object. Nothing was sent.")
    session = live_session()

    status, parsed, text = post_in_session(session, query, variables)
    if not isinstance(parsed, dict) or not ("data" in parsed or "errors" in parsed):
        raise ValueError(f"io-server at {host_of(session['graphql_url'])} answered HTTP {status} "
                         f"without a GraphQL body: {text[:300]!r}")
    return cut(json.dumps({"data": parsed.get("data"), "errors": parsed.get("errors")},
                          ensure_ascii=False))


def session_schema(session: dict) -> dict:
    """The session's cached schema, sending the one introspection query on first use.

    Returns {"query": root query type name, "mutation": root mutation type name or None,
    "types": {name: introspected type}}. A failed introspection is not cached.
    """
    if session.get("schema_cache"):
        return session["schema_cache"]
    status, parsed, text = post_in_session(session, INTROSPECTION_QUERY)
    schema = ((parsed.get("data") if isinstance(parsed, dict) else None) or {}).get("__schema")
    if not isinstance(schema, dict) or not isinstance(schema.get("types"), list):
        detail = (graphql_error_summary(parsed) if isinstance(parsed, dict)
                  else f"no GraphQL body: {text[:300]!r}") or "no __schema in the answer"
        raise ValueError(f"io-server at {host_of(session['graphql_url'])} did not answer the "
                         f"schema introspection (HTTP {status}): {detail}")
    session["schema_cache"] = {
        "query": (schema.get("queryType") or {}).get("name"),
        "mutation": (schema.get("mutationType") or {}).get("name"),
        "types": {t["name"]: t for t in schema["types"] if isinstance(t, dict) and t.get("name")},
    }
    log(f"cached the schema for account {session['account_id']} "
        f"({len(session['schema_cache']['types'])} types)")
    return session["schema_cache"]


def type_ref(ref) -> str:
    """A type reference written the GraphQL way, for example [Employee!]!"""
    if not isinstance(ref, dict):
        return "?"
    if ref.get("kind") == "NON_NULL":
        return f"{type_ref(ref.get('ofType'))}!"
    if ref.get("kind") == "LIST":
        return f"[{type_ref(ref.get('ofType'))}]"
    return str(ref.get("name") or "?")


def value_sdl(value: dict) -> str:
    """An argument or input field: `name: Type` or `name: Type = default`."""
    text = f"{value.get('name')}: {type_ref(value.get('type'))}"
    if value.get("defaultValue") is not None:
        text += f" = {value['defaultValue']}"
    return text


def deprecated(item: dict) -> str:
    return " (deprecated)" if item.get("isDeprecated") else ""


def root_fields_text(schema: dict) -> str:
    lines = []
    for label, name in (("Query", schema["query"]), ("Mutation", schema["mutation"])):
        fields = (schema["types"].get(name) or {}).get("fields") or []
        if not name or not fields:
            lines += [f"{label}: none in this schema.", ""]
            continue
        lines.append(f"{label} ({name}, {len(fields)} fields):")
        for field in fields:
            arg_names = ", ".join(str(a.get("name")) for a in field.get("args") or [])
            call = f"{field.get('name')}({arg_names})" if arg_names else str(field.get("name"))
            lines.append(f"  {call}: {type_ref(field.get('type'))}{deprecated(field)}")
        lines.append("")
    lines.append("Call shapes_schema with a type name (a return type, an input type, or "
                 f"\"{schema['query']}\" itself) to see its fields with argument types.")
    return "\n".join(lines)


def type_text(t: dict) -> str:
    kind, name = t.get("kind"), t.get("name")
    if kind in ("OBJECT", "INTERFACE"):
        interfaces = [type_ref(i) for i in t.get("interfaces") or []]
        header = f"{'type' if kind == 'OBJECT' else 'interface'} {name}"
        if interfaces:
            header += f" implements {' & '.join(interfaces)}"
        fields = t.get("fields") or []
        lines = [header, f"fields ({len(fields)}):"]
        for field in fields:
            args = ", ".join(value_sdl(a) for a in field.get("args") or [])
            call = f"{field.get('name')}({args})" if args else str(field.get("name"))
            lines.append(f"  {call}: {type_ref(field.get('type'))}{deprecated(field)}")
        if kind == "INTERFACE" and t.get("possibleTypes"):
            lines.append(f"implemented by: {', '.join(type_ref(p) for p in t['possibleTypes'])}")
        return "\n".join(lines)
    if kind == "INPUT_OBJECT":
        input_fields = t.get("inputFields") or []
        return "\n".join([f"input {name}", f"input fields ({len(input_fields)}):"]
                         + [f"  {value_sdl(f)}" for f in input_fields])
    if kind == "ENUM":
        values = t.get("enumValues") or []
        return "\n".join([f"enum {name}", f"values ({len(values)}):"]
                         + [f"  {v.get('name')}{deprecated(v)}" for v in values])
    if kind == "UNION":
        return f"union {name} = {' | '.join(type_ref(p) for p in t.get('possibleTypes') or [])}"
    return f"scalar {name}"


def close_names(name: str, types: dict) -> list:
    """Up to five schema type names that look like `name`: same name in another case,
    then spelling neighbours, then names that contain it."""
    names = [n for n in types if not n.startswith("__")]
    lower = name.lower()
    found = [n for n in names if n.lower() == lower]
    found += [n for n in difflib.get_close_matches(name, names, n=5, cutoff=0.6) if n not in found]
    found += sorted((n for n in names if lower in n.lower() and n not in found), key=len)
    return found[:5]


def tool_schema(args: dict) -> str:
    type_name = args.get("type_name")
    if type_name is not None and not isinstance(type_name, str):
        raise ValueError("Refused: `type_name` must be a string, such as \"Employee\". "
                         "Nothing was sent.")
    session = live_session()
    schema = session_schema(session)

    name = (type_name or "").strip().strip("[]!").strip()  # "[Employee!]!" -> "Employee"
    if not name:
        return cut(root_fields_text(schema))
    found = schema["types"].get(name)
    if found is None:
        near = close_names(name, schema["types"])
        hint = f" Close names: {', '.join(near)}." if near else ""
        raise ValueError(f"no such type {name!r} in this account's schema.{hint} Call "
                         "shapes_schema with no argument to list the root fields.")
    return cut(type_text(found))


HANDLERS = {
    "shapes_connect": tool_connect,
    "shapes_whoami": tool_whoami,
    "shapes_disconnect": tool_disconnect,
    "shapes_graphql": tool_graphql,
    "shapes_schema": tool_schema,
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
                "and its minutes left, shapes_graphql runs any query or mutation in the account, "
                "shapes_schema looks up the schema one type at a time, "
                "shapes_disconnect closes it. A session lasts 1 hour and "
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
