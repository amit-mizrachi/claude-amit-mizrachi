"""Tests for the shapes-session MCP, through its one seam: the stdio protocol.

Each test starts server.py as a subprocess, speaks JSON-RPC to it the way Claude Code
does, and points it (with SHAPES_SESSION_API_URL) at a fake io-server on 127.0.0.1.
Tokens are made-up unsigned JWT-shaped strings; nothing here talks to a real Shapes host.

Run from this folder: python3 -m unittest -v test_server
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVER = Path(__file__).resolve().parent / "server.py"
API_URL_ENV = "SHAPES_SESSION_API_URL"
REPLY_TIMEOUT = 20

INTERNAL_ACCOUNT = {"id": "acc-internal-1", "name": "Forge Demo Co", "isInternal": True}
CUSTOMER_ACCOUNT = {"id": "acc-customer-9", "name": "Real Customer Ltd", "isInternal": False}
USER = {"id": "user-1", "email": "admin@forge-demo.example"}


# --------------------------------------------------------------------------- #
# tokens and links
# --------------------------------------------------------------------------- #


def b64url(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def make_token(expires_in: float = 3600, **claims) -> str:
    """An unsigned JWT-shaped string with a chosen exp. Unique per call, so leak checks can find it."""
    payload = {"userId": USER["id"], "accountId": INTERNAL_ACCOUNT["id"], "tokenVersion": 1,
               "isSystemUser": True, "exp": int(time.time() + expires_in),
               "nonce": uuid.uuid4().hex}
    payload.update(claims)
    return f"{b64url({'alg': 'none', 'typ': 'JWT'})}.{b64url(payload)}.fake-signature-{uuid.uuid4().hex}"


def login_link(token: str | None, origin: str = "https://app.shapes.co") -> str:
    if token is None:
        return f"{origin}?isSystemUser=true"
    return f"{origin}?token={token}&isSystemUser=true"


def connect_answer(account: dict = INTERNAL_ACCOUNT, user: dict = USER) -> dict:
    return {"data": {"me": dict(user), "fetchAppConfig": {"currentAccount": dict(account)}}}


# --------------------------------------------------------------------------- #
# a small fixed schema, as io-server's introspection answer gives it
# --------------------------------------------------------------------------- #


def named(kind: str, name: str) -> dict:
    return {"kind": kind, "name": name, "ofType": None}


def non_null(ref: dict) -> dict:
    return {"kind": "NON_NULL", "name": None, "ofType": ref}


def list_of(ref: dict) -> dict:
    return {"kind": "LIST", "name": None, "ofType": ref}


def value(name: str, ref: dict, default: str | None = None) -> dict:
    return {"name": name, "defaultValue": default, "type": ref}


def field(name: str, ref: dict, args=(), deprecated: bool = False) -> dict:
    return {"name": name, "isDeprecated": deprecated, "args": list(args), "type": ref}


def schema_type(kind: str, name: str, fields=None, input_fields=None, enum_values=None) -> dict:
    return {"kind": kind, "name": name, "fields": fields, "inputFields": input_fields,
            "interfaces": [] if kind == "OBJECT" else None, "enumValues": enum_values,
            "possibleTypes": None}


ID, STRING, INT = named("SCALAR", "ID"), named("SCALAR", "String"), named("SCALAR", "Int")
DEPARTMENT = named("OBJECT", "Department")
DEPARTMENT_KIND = named("ENUM", "DepartmentKind")

SCHEMA_ANSWER = {"data": {"__schema": {
    "queryType": {"name": "Query"},
    "mutationType": {"name": "Mutation"},
    "types": [
        schema_type("OBJECT", "Query", fields=[
            field("departments", non_null(list_of(non_null(DEPARTMENT))),
                  args=[value("kind", DEPARTMENT_KIND), value("first", INT, "50")]),
            field("department", DEPARTMENT, args=[value("id", non_null(ID))]),
        ]),
        schema_type("OBJECT", "Mutation", fields=[
            field("createDepartment", non_null(DEPARTMENT),
                  args=[value("input", non_null(named("INPUT_OBJECT", "CreateDepartmentInput")))]),
        ]),
        schema_type("OBJECT", "Department", fields=[
            field("id", non_null(ID)),
            field("name", non_null(STRING)),
            field("kind", non_null(DEPARTMENT_KIND)),
            field("tags", list_of(non_null(STRING))),
            field("legacyCode", STRING, deprecated=True),
        ]),
        schema_type("INPUT_OBJECT", "CreateDepartmentInput", input_fields=[
            value("name", non_null(STRING)),
            value("kind", DEPARTMENT_KIND, "TEAM"),
        ]),
        schema_type("ENUM", "DepartmentKind", enum_values=[
            {"name": "TEAM", "isDeprecated": False},
            {"name": "DIVISION", "isDeprecated": False},
            {"name": "OLD", "isDeprecated": True},
        ]),
        schema_type("SCALAR", "ID"),
        schema_type("SCALAR", "String"),
        schema_type("SCALAR", "Int"),
        schema_type("OBJECT", "__Type", fields=[field("name", STRING)]),
    ],
}}}


# --------------------------------------------------------------------------- #
# fake io-server
# --------------------------------------------------------------------------- #


class FakeIoServer:
    """Plays io-server's POST /api on 127.0.0.1.

    A test sets answers with `on(match, status, body)`: the newest rule whose `match`
    text appears in the GraphQL query wins. `body` is a dict (sent as JSON), a str
    (sent as is), or a callable taking the recorded request and returning (status, body).
    Every request is recorded in `requests` as {"method", "path", "headers", "body"},
    with header names lower-cased and the body parsed from JSON when it is JSON.
    """

    def __init__(self):
        self.requests = []
        self.rules = []
        self.on("fetchAppConfig", 200, connect_answer())
        self.on("__schema", 200, SCHEMA_ANSWER)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake._answer(self, "POST", raw)

            def do_GET(self):
                fake._answer(self, "GET", b"")

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def url(self) -> str:
        return f"{self.origin}/api"

    def start(self) -> "FakeIoServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def on(self, match: str, status: int = 200, body=None) -> None:
        self.rules.insert(0, (match, status, body))

    def _answer(self, handler, method: str, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace")
        try:
            body = json.loads(text) if text else None
        except ValueError:
            body = text
        request = {"method": method, "path": handler.path,
                   "headers": {k.lower(): v for k, v in handler.headers.items()}, "body": body}
        self.requests.append(request)

        query = body.get("query", "") if isinstance(body, dict) else ""
        status, answer = 404, {"errors": [{"message": "fake io-server: no rule matched"}]}
        if method == "POST" and handler.path == "/api":
            status, answer = 200, {"data": None,
                                   "errors": [{"message": "fake io-server: no rule matched"}]}
            for match, rule_status, rule_body in self.rules:
                if match in query:
                    status, answer = rule_status, rule_body
                    break
        if callable(answer):
            status, answer = answer(request)
        payload = answer if isinstance(answer, (str, bytes)) else json.dumps(answer)
        payload = payload.encode("utf-8") if isinstance(payload, str) else payload
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


# --------------------------------------------------------------------------- #
# MCP client over stdio
# --------------------------------------------------------------------------- #


class McpClient:
    """Runs server.py as Claude Code does and speaks line-delimited JSON-RPC to it.

    `stdout_lines` and `stderr_lines` keep everything the server wrote, for leak checks.
    """

    def __init__(self, api_url: str | None, extra_env: dict | None = None):
        env = {k: v for k, v in os.environ.items()
               if k != API_URL_ENV and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        if api_url is not None:
            env[API_URL_ENV] = api_url
        env.update(extra_env or {})
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], env=env, text=True, bufsize=1,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.stdout_lines, self.stderr_lines = [], []
        self.replies = queue.Queue()
        self.next_id = 0
        self.pumps = [threading.Thread(target=self._pump_stdout, daemon=True),
                      threading.Thread(target=self._pump_stderr, daemon=True)]
        for pump in self.pumps:
            pump.start()

    def _pump_stdout(self) -> None:
        for line in self.proc.stdout:
            self.stdout_lines.append(line)
            try:
                self.replies.put(json.loads(line))
            except ValueError:
                self.replies.put({"unparsable": line})

    def _pump_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_lines.append(line)

    def notify(self, method: str, params: dict | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        rid = self.next_id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.time() + REPLY_TIMEOUT
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise AssertionError(f"no reply to {method} within {REPLY_TIMEOUT}s; "
                                     f"stderr: {''.join(self.stderr_lines)[-2000:]}")
            try:
                reply = self.replies.get(timeout=remaining)
            except queue.Empty:
                continue
            if reply.get("id") == rid:
                return reply

    def initialize(self) -> dict:
        reply = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "test", "version": "0"}})
        self.notify("notifications/initialized")
        return reply

    def call(self, name: str, arguments: dict | None = None):
        """Call a tool. Returns (result text, isError)."""
        reply = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in reply:
            raise AssertionError(f"protocol error from {name}: {reply['error']}")
        result = reply["result"]
        text = "\n".join(c.get("text", "") for c in result.get("content", []))
        return text, bool(result.get("isError"))

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for pump in self.pumps:
            pump.join(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()

    def _write(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()


# --------------------------------------------------------------------------- #
# base test case
# --------------------------------------------------------------------------- #


class ShapesSessionTestCase(unittest.TestCase):
    """Gives each test `self.fake` (a running fake io-server) and `self.mcp` (an initialized
    server pointed at it). Later tickets add cases by subclassing this."""

    def setUp(self):
        self.fake = FakeIoServer().start()
        self.addCleanup(self.fake.stop)
        self.mcp = self.start_mcp(self.fake.url)

    def start_mcp(self, api_url: str | None, extra_env: dict | None = None) -> McpClient:
        client = McpClient(api_url, extra_env)
        self.addCleanup(client.close)
        client.initialize()
        return client

    def connect(self, token: str, origin: str = "https://app.shapes.co", mcp: McpClient | None = None):
        return (mcp or self.mcp).call("shapes_connect", {"link": login_link(token, origin)})

    def assertNoLeak(self, token: str, mcp: McpClient | None = None) -> None:
        mcp = mcp or self.mcp
        self.assertNotIn(token, "".join(mcp.stdout_lines), "token leaked into a protocol message")
        self.assertNotIn(token, "".join(mcp.stderr_lines), "token leaked onto stderr")


# --------------------------------------------------------------------------- #
# ticket 01: connect, whoami, disconnect
# --------------------------------------------------------------------------- #


class ProtocolTests(ShapesSessionTestCase):
    def test_initialize_names_the_server(self):
        reply = self.start_mcp(self.fake.url).initialize()
        self.assertEqual(reply["result"]["serverInfo"]["name"], "shapes-session")
        self.assertIn("tools", reply["result"]["capabilities"])

    def test_tools_list_has_session_tools_with_one_hour_internal_account_descriptions(self):
        tools = {t["name"]: t for t in self.mcp.request("tools/list")["result"]["tools"]}
        for name in ("shapes_connect", "shapes_whoami", "shapes_disconnect", "shapes_graphql",
                     "shapes_schema"):
            self.assertIn(name, tools)
            description = tools[name]["description"]
            self.assertIn("1 hour", description, name)
            self.assertIn("one internal Shapes account", description, name)
        self.assertEqual(tools["shapes_connect"]["inputSchema"]["required"], ["link"])
        self.assertEqual(tools["shapes_graphql"]["inputSchema"]["required"], ["query"])

    def test_unknown_method_is_a_protocol_error(self):
        reply = self.mcp.request("no/such/method")
        self.assertEqual(reply["error"]["code"], -32601)


class ConnectTests(ShapesSessionTestCase):
    def test_connect_to_internal_account(self):
        token = make_token()
        text, is_error = self.connect(token)
        self.assertFalse(is_error, text)
        self.assertIn(INTERNAL_ACCOUNT["id"], text)
        self.assertIn(INTERNAL_ACCOUNT["name"], text)
        self.assertIn(USER["email"], text)
        self.assertIn("isInternal:    true", text)
        self.assertIn(f"graphql host:  127.0.0.1:{self.fake.httpd.server_address[1]}", text)
        self.assertRegex(text, r"minutes left:  (59|60) ")

        self.assertEqual(len(self.fake.requests), 1)
        sent = self.fake.requests[0]
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api"))
        self.assertEqual(sent["headers"]["authorization"], f"Bearer {token}")
        self.assertEqual(sent["headers"]["content-type"], "application/json")
        for field in ("fetchAppConfig", "currentAccount", "isInternal", "me", "email"):
            self.assertIn(field, sent["body"]["query"])
        self.assertNoLeak(token)

    def test_whoami_after_connect_shows_the_same_fields(self):
        self.connect(make_token())
        text, is_error = self.mcp.call("shapes_whoami")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("connected"), text)
        for value in (INTERNAL_ACCOUNT["id"], INTERNAL_ACCOUNT["name"], USER["email"], "true"):
            self.assertIn(value, text)
        self.assertRegex(text, r"minutes left:  \d+ ")

    def test_whoami_before_any_connect_says_not_connected(self):
        text, is_error = self.mcp.call("shapes_whoami")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("not connected"), text)

    def test_non_internal_account_is_refused_and_not_connected(self):
        self.fake.on("fetchAppConfig", 200, connect_answer(CUSTOMER_ACCOUNT))
        token = make_token()
        text, is_error = self.connect(token)
        self.assertTrue(is_error, text)
        self.assertIn(CUSTOMER_ACCOUNT["id"], text)
        self.assertIn(CUSTOMER_ACCOUNT["name"], text)
        self.assertIn("not an internal account", text)

        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)
        self.assertNoLeak(token)

    def test_refused_account_replaces_an_open_session(self):
        self.connect(make_token())
        self.fake.on("fetchAppConfig", 200, connect_answer(CUSTOMER_ACCOUNT))
        _, is_error = self.connect(make_token())
        self.assertTrue(is_error)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)

    def test_failed_connect_query_is_refused(self):
        self.fake.on("fetchAppConfig", 200,
                     {"data": None, "errors": [{"message": "boom",
                                                "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]})
        text, is_error = self.connect(make_token())
        self.assertTrue(is_error, text)
        self.assertIn("boom", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)

    def test_http_401_on_connect_is_refused(self):
        self.fake.on("fetchAppConfig", 401, {"errors": [{"message": "Unauthorized"}]})
        token = make_token()
        text, is_error = self.connect(token)
        self.assertTrue(is_error, text)
        self.assertIn("401", text)
        self.assertNoLeak(token)

    def test_unknown_origin_without_override_is_refused_before_any_request(self):
        mcp = self.start_mcp(api_url=None)
        token = make_token()
        # the link points at the fake server's own origin, so a wrongly sent request would land here
        text, is_error = self.connect(token, origin=self.fake.origin, mcp=mcp)
        self.assertTrue(is_error, text)
        self.assertIn(API_URL_ENV, text)
        self.assertEqual(self.fake.requests, [])
        self.assertNoLeak(token, mcp)

    def test_link_without_token_is_refused(self):
        text, is_error = self.mcp.call("shapes_connect", {"link": login_link(None)})
        self.assertTrue(is_error, text)
        self.assertIn("token", text)
        self.assertEqual(self.fake.requests, [])

    def test_link_that_is_not_a_url_is_refused(self):
        text, is_error = self.mcp.call("shapes_connect", {"link": "not a link"})
        self.assertTrue(is_error, text)
        self.assertEqual(self.fake.requests, [])

    def test_expired_link_is_refused_without_a_request(self):
        token = make_token(expires_in=-60)
        text, is_error = self.connect(token)
        self.assertTrue(is_error, text)
        self.assertIn("expired", text)
        self.assertEqual(self.fake.requests, [])
        self.assertNoLeak(token)

    def test_whoami_says_expired_once_exp_has_passed(self):
        token = make_token(expires_in=3)
        text, is_error = self.connect(token)
        self.assertFalse(is_error, text)
        time.sleep(4)
        text, is_error = self.mcp.call("shapes_whoami")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("expired"), text)
        self.assertIn(INTERNAL_ACCOUNT["name"], text)
        self.assertIn("new", text)
        self.assertNoLeak(token)


class SessionLifecycleTests(ShapesSessionTestCase):
    def test_second_connect_replaces_the_session(self):
        first, second = make_token(), make_token()
        self.connect(first)
        other = {"id": "acc-internal-2", "name": "Second Demo Co", "isInternal": True}
        self.fake.on("fetchAppConfig", 200, connect_answer(other))
        text, is_error = self.connect(second)
        self.assertFalse(is_error, text)

        text, _ = self.mcp.call("shapes_whoami")
        self.assertIn(other["id"], text)
        self.assertNotIn(INTERNAL_ACCOUNT["id"], text)
        self.assertEqual(self.fake.requests[-1]["headers"]["authorization"], f"Bearer {second}")
        self.assertNoLeak(first)
        self.assertNoLeak(second)

    def test_disconnect_clears_the_session(self):
        token = make_token()
        self.connect(token)
        text, is_error = self.mcp.call("shapes_disconnect")
        self.assertFalse(is_error, text)
        self.assertIn("disconnected", text)
        self.assertIn(INTERNAL_ACCOUNT["id"], text)

        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)
        self.assertNoLeak(token)

    def test_disconnect_without_a_session_says_so(self):
        text, is_error = self.mcp.call("shapes_disconnect")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("not connected"), text)


# --------------------------------------------------------------------------- #
# ticket 02: shapes_graphql
# --------------------------------------------------------------------------- #

DEPARTMENTS_QUERY = "query Departments { departments { id name } }"
CREATE_DEPARTMENT = ("mutation CreateDepartment($input: CreateDepartmentInput!) "
                     "{ createDepartment(input: $input) { id name } }")


class GraphqlTests(ShapesSessionTestCase):
    def setUp(self):
        super().setUp()
        self.token = make_token()
        text, is_error = self.connect(self.token)
        self.assertFalse(is_error, text)

    def graphql(self, query: str, variables: dict | None = None):
        arguments = {"query": query}
        if variables is not None:
            arguments["variables"] = variables
        return self.mcp.call("shapes_graphql", arguments)

    def test_mutation_with_variables_reaches_io_server_and_returns_data(self):
        def echo(request):
            name = request["body"]["variables"]["input"]["name"]
            return 200, {"data": {"createDepartment": {"id": "dep-1", "name": name}}}
        self.fake.on("createDepartment", 200, echo)
        variables = {"input": {"name": "Platform"}}

        text, is_error = self.graphql(CREATE_DEPARTMENT, variables)
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text),
                         {"data": {"createDepartment": {"id": "dep-1", "name": "Platform"}},
                          "errors": None})

        sent = self.fake.requests[-1]
        self.assertEqual(len(self.fake.requests), 2)  # connect, then the mutation, no retry
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api"))
        self.assertEqual(sent["headers"]["authorization"], f"Bearer {self.token}")
        self.assertEqual(sent["headers"]["content-type"], "application/json")
        self.assertEqual(sent["body"], {"query": CREATE_DEPARTMENT, "variables": variables})
        self.assertNoLeak(self.token)

    def test_query_without_variables_sends_an_empty_object(self):
        self.fake.on("departments", 200, {"data": {"departments": []}})
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertFalse(is_error, text)
        self.assertEqual(self.fake.requests[-1]["body"], {"query": DEPARTMENTS_QUERY, "variables": {}})

    def test_errors_beside_data_are_passed_through(self):
        answer = {"data": {"departments": [{"id": "dep-1", "name": "Sales"}], "secret": None},
                  "errors": [{"message": "Not allowed to read secret", "path": ["secret"],
                              "extensions": {"code": "FORBIDDEN"}}]}
        self.fake.on("departments", 200, answer)
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text), answer)

        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)  # a non-auth error keeps the session

    def test_http_400_with_graphql_errors_is_passed_through(self):
        answer = {"errors": [{"message": 'Cannot query field "nope" on type "Query".',
                              "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}
        self.fake.on("nope", 400, answer)
        text, is_error = self.graphql("query { nope }")
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text), {"data": None, "errors": answer["errors"]})

    def test_http_401_ends_the_session(self):
        self.fake.on("departments", 401, {"errors": [{"message": "Unauthorized"}]})
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertTrue(is_error, text)
        self.assertIn("session expired or rejected", text)
        self.assertIn("new login-as link", text)

        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)
        requests_before = len(self.fake.requests)
        _, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertTrue(is_error)
        self.assertEqual(len(self.fake.requests), requests_before)
        self.assertNoLeak(self.token)

    def assertSessionEnded(self, text: str, is_error: bool) -> None:
        self.assertTrue(is_error, text)
        self.assertIn("session expired or rejected", text)
        self.assertIn("new login-as link", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)

    def test_not_authenticated_error_ends_the_session(self):
        # io-server in dev: the shield's NotAuthenticatedError, sent with HTTP 200
        self.fake.on("departments", 200,
                     {"data": None, "errors": [{"message": "Not Authenticated",
                                                "extensions": {"code": 401}}]})
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertSessionEnded(text, is_error)
        self.assertNotIn("ShapesSessionProbe", json.dumps([r["body"] for r in self.fake.requests]))
        self.assertNoLeak(self.token)

    def test_not_authorized_error_keeps_the_session(self):
        answer = {"data": None, "errors": [{"message": "Not Authorized",
                                            "extensions": {"code": 401}}]}
        self.fake.on("departments", 200, answer)
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text), answer)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)

    def test_unauthenticated_code_from_a_login_mutation_keeps_the_session(self):
        answer = {"data": None, "errors": [{"message": "Wrong password",
                                            "extensions": {"code": "UNAUTHENTICATED"}}]}
        self.fake.on("login", 200, answer)
        text, is_error = self.graphql('mutation { login(email: "a", password: "b") { id } }')
        self.assertFalse(is_error, text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)

    def test_masked_error_and_failed_probe_ends_the_session(self):
        # io-server in production masks NotAuthenticatedError to a bare internal error
        masked = {"data": None, "errors": [{"message": "Internal server error"}]}
        self.fake.on("departments", 200, masked)
        self.fake.on("ShapesSessionProbe", 200, masked)
        requests_before = len(self.fake.requests)
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertSessionEnded(text, is_error)
        sent = [r["body"]["query"] for r in self.fake.requests[requests_before:]]
        self.assertEqual(sent, [DEPARTMENTS_QUERY, "query ShapesSessionProbe { me { id } }"])
        self.assertNoLeak(self.token)

    def test_masked_error_and_working_probe_keeps_the_session(self):
        masked = {"data": None, "errors": [{"message": "Internal server error"}]}
        self.fake.on("departments", 200, masked)
        self.fake.on("ShapesSessionProbe", 200, {"data": {"me": {"id": USER["id"]}}})
        requests_before = len(self.fake.requests)
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text), masked)
        sent = [r["body"]["query"] for r in self.fake.requests[requests_before:]]
        self.assertEqual(sent, [DEPARTMENTS_QUERY, "query ShapesSessionProbe { me { id } }"])
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)

    def test_non_graphql_answer_is_an_error_and_keeps_the_session(self):
        self.fake.on("departments", 502, "<html>Bad Gateway</html>")
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertTrue(is_error, text)
        self.assertIn("502", text)
        self.assertIn("Bad Gateway", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)

    def test_large_answer_is_cut_with_the_full_length(self):
        self.fake.on("departments", 200, {"data": {"departments": [{"id": "x" * 150_000}]}})
        text, is_error = self.graphql(DEPARTMENTS_QUERY)
        self.assertFalse(is_error, text)
        match = re.search(r"\[cut: the full answer was (\d+) characters; "
                          r"only the first 100000 are shown", text)
        self.assertIsNotNone(match, text[-500:])
        self.assertGreater(int(match.group(1)), 150_000)
        self.assertLess(len(text), 100_000 + 500)
        self.assertTrue(text.startswith('{"data": {"departments": [{"id": "xxx'), text[:100])

    def test_missing_query_is_refused_without_a_request(self):
        requests_before = len(self.fake.requests)
        text, is_error = self.mcp.call("shapes_graphql", {})
        self.assertTrue(is_error, text)
        self.assertIn("query", text)
        self.assertEqual(len(self.fake.requests), requests_before)

    def test_variables_that_are_not_an_object_are_refused_without_a_request(self):
        requests_before = len(self.fake.requests)
        text, is_error = self.mcp.call("shapes_graphql",
                                       {"query": DEPARTMENTS_QUERY, "variables": [1, 2]})
        self.assertTrue(is_error, text)
        self.assertIn("variables", text)
        self.assertEqual(len(self.fake.requests), requests_before)


class GraphqlTimeoutTests(ShapesSessionTestCase):
    def setUp(self):
        super().setUp()
        self.mcp = self.start_mcp(self.fake.url, {"SHAPES_SESSION_TEST_HTTP_TIMEOUT": "0.5"})
        self.token = make_token()
        text, is_error = self.connect(self.token)
        self.assertFalse(is_error, text)

    def test_timeout_says_the_request_may_have_run(self):
        def slow(request):
            time.sleep(2)
            return 200, {"data": {"createDepartment": {"id": "dep-9"}}}

        self.fake.on("createDepartment", 200, slow)
        text, is_error = self.mcp.call("shapes_graphql", {
            "query": CREATE_DEPARTMENT, "variables": {"input": {"name": "Ops"}}})
        self.assertTrue(is_error, text)
        self.assertIn("no answer from io-server", text)
        self.assertIn("the request may have run", text)
        self.assertNotIn("could not reach", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("connected"), text)
        self.assertNoLeak(self.token)


class GraphqlWithoutSessionTests(ShapesSessionTestCase):
    def test_no_session_is_refused_without_a_request(self):
        text, is_error = self.mcp.call("shapes_graphql", {"query": DEPARTMENTS_QUERY})
        self.assertTrue(is_error, text)
        self.assertIn("not connected", text)
        self.assertIn("Paste a new", text)
        self.assertEqual(self.fake.requests, [])

    def test_after_disconnect_is_refused_without_a_request(self):
        self.connect(make_token())
        self.mcp.call("shapes_disconnect")
        text, is_error = self.mcp.call("shapes_graphql", {"query": DEPARTMENTS_QUERY})
        self.assertTrue(is_error, text)
        self.assertIn("not connected", text)
        self.assertEqual(len(self.fake.requests), 1)  # the connect only

    def test_expired_token_is_refused_without_a_request(self):
        token = make_token(expires_in=3)
        text, is_error = self.connect(token)
        self.assertFalse(is_error, text)
        time.sleep(4)
        text, is_error = self.mcp.call("shapes_graphql", {"query": DEPARTMENTS_QUERY})
        self.assertTrue(is_error, text)
        self.assertIn("expired", text)
        self.assertIn("Paste a new", text)
        self.assertEqual(len(self.fake.requests), 1)  # the connect only
        self.assertNoLeak(token)


# --------------------------------------------------------------------------- #
# ticket 03: shapes_schema
# --------------------------------------------------------------------------- #


class SchemaTests(ShapesSessionTestCase):
    def setUp(self):
        super().setUp()
        self.token = make_token()
        text, is_error = self.connect(self.token)
        self.assertFalse(is_error, text)

    def schema(self, type_name: str | None = None):
        return self.mcp.call("shapes_schema", {} if type_name is None else {"type_name": type_name})

    def introspections(self) -> list:
        return [r for r in self.fake.requests
                if isinstance(r["body"], dict) and "__schema" in r["body"].get("query", "")]

    def test_no_argument_lists_root_query_and_mutation_fields_with_argument_names(self):
        text, is_error = self.schema()
        self.assertFalse(is_error, text)
        self.assertIn("Query (Query, 2 fields):", text)
        self.assertIn("  departments(kind, first): [Department!]!", text)
        self.assertIn("  department(id): Department", text)
        self.assertIn("Mutation (Mutation, 1 fields):", text)
        self.assertIn("  createDepartment(input): Department!", text)
        self.assertNotIn("legacyCode", text)  # root list only, no type bodies

        [sent] = self.introspections()
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api"))
        self.assertEqual(sent["headers"]["authorization"], f"Bearer {self.token}")
        for part in ("queryType", "mutationType", "fields", "args", "inputFields", "enumValues",
                     "ofType"):
            self.assertIn(part, sent["body"]["query"])
        self.assertNoLeak(self.token)

    def test_object_type_shows_fields_with_graphql_type_refs(self):
        text, is_error = self.schema("Department")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("type Department"), text)
        for line in ("  id: ID!", "  name: String!", "  kind: DepartmentKind!",
                     "  tags: [String!]", "  legacyCode: String (deprecated)"):
            self.assertIn(line, text)

    def test_root_type_lookup_shows_argument_types_and_defaults(self):
        text, is_error = self.schema("Query")
        self.assertFalse(is_error, text)
        self.assertIn("  departments(kind: DepartmentKind, first: Int = 50): [Department!]!", text)
        self.assertIn("  department(id: ID!): Department", text)

    def test_input_type_shows_input_fields(self):
        text, is_error = self.schema("CreateDepartmentInput")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("input CreateDepartmentInput"), text)
        self.assertIn("  name: String!", text)
        self.assertIn("  kind: DepartmentKind = TEAM", text)

    def test_enum_type_shows_values(self):
        text, is_error = self.schema("DepartmentKind")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("enum DepartmentKind"), text)
        for line in ("  TEAM", "  DIVISION", "  OLD (deprecated)"):
            self.assertIn(line, text)

    def test_wrapped_type_name_is_looked_up_by_its_named_type(self):
        text, is_error = self.schema("[Department!]!")
        self.assertFalse(is_error, text)
        self.assertTrue(text.startswith("type Department"), text)

    def test_schema_is_introspected_once_per_session(self):
        for type_name in (None, "Department", "DepartmentKind", "Nope"):
            self.schema(type_name)
        self.assertEqual(len(self.introspections()), 1)

    def test_reconnect_drops_the_cache(self):
        self.schema()
        second = make_token()
        self.connect(second)
        text, is_error = self.schema("Department")
        self.assertFalse(is_error, text)
        self.assertEqual(len(self.introspections()), 2)
        self.assertEqual(self.introspections()[-1]["headers"]["authorization"], f"Bearer {second}")
        self.assertNoLeak(second)

    def test_disconnect_drops_the_cache(self):
        self.schema()
        self.mcp.call("shapes_disconnect")
        text, is_error = self.schema()
        self.assertTrue(is_error, text)
        self.assertIn("not connected", text)
        self.assertEqual(len(self.introspections()), 1)  # no session, nothing sent

        self.connect(make_token())
        self.schema()
        self.assertEqual(len(self.introspections()), 2)

    def test_unknown_type_answers_no_such_type_with_close_names(self):
        text, is_error = self.schema("Departmnt")
        self.assertTrue(is_error, text)
        self.assertIn("no such type", text)
        self.assertIn("Departmnt", text)
        self.assertIn("Close names: Department", text)
        self.assertNotIn("__Type", text)

        text, is_error = self.schema("departmentkind")
        self.assertTrue(is_error, text)
        self.assertIn("DepartmentKind", text)

    def test_failed_introspection_is_an_error_and_is_not_cached(self):
        self.fake.on("__schema", 200, {"data": None, "errors": [
            {"message": "introspection broke", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]})
        text, is_error = self.schema()
        self.assertTrue(is_error, text)
        self.assertIn("introspection broke", text)

        self.fake.on("__schema", 200, SCHEMA_ANSWER)
        text, is_error = self.schema()
        self.assertFalse(is_error, text)
        self.assertEqual(len(self.introspections()), 2)

    def test_http_401_on_introspection_ends_the_session(self):
        self.fake.on("__schema", 401, {"errors": [{"message": "Unauthorized"}]})
        text, is_error = self.schema()
        self.assertTrue(is_error, text)
        self.assertIn("session expired or rejected", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)
        self.assertNoLeak(self.token)

    def test_type_name_that_is_not_a_string_is_refused_without_a_request(self):
        requests_before = len(self.fake.requests)
        text, is_error = self.mcp.call("shapes_schema", {"type_name": 7})
        self.assertTrue(is_error, text)
        self.assertIn("type_name", text)
        self.assertEqual(len(self.fake.requests), requests_before)


class SchemaWithoutSessionTests(ShapesSessionTestCase):
    def test_no_session_is_refused_without_a_request(self):
        text, is_error = self.mcp.call("shapes_schema", {"type_name": "Department"})
        self.assertTrue(is_error, text)
        self.assertIn("not connected", text)
        self.assertEqual(self.fake.requests, [])

    def test_expired_token_is_refused_without_a_request(self):
        token = make_token(expires_in=3)
        text, is_error = self.connect(token)
        self.assertFalse(is_error, text)
        time.sleep(4)
        text, is_error = self.mcp.call("shapes_schema")
        self.assertTrue(is_error, text)
        self.assertIn("expired", text)
        self.assertIn("Paste a new", text)
        self.assertEqual(len(self.fake.requests), 1)  # the connect only
        self.assertNoLeak(token)


# --------------------------------------------------------------------------- #
# ticket 04: the token never leaks
# --------------------------------------------------------------------------- #


def bearer_of(request: dict) -> str:
    return request["headers"].get("authorization", "").replace("Bearer ", "", 1)


class TokenLeakTests(ShapesSessionTestCase):
    def test_token_never_appears_in_a_result_or_on_stderr(self):
        """A hostile io-server echoes the bearer token back in every answer it can. Across a
        connect, failing calls and a refused connect, no tool result and no stderr line may
        carry a token."""
        live, refused = make_token(), make_token()

        # 1. a connect that works
        text, is_error = self.connect(live)
        self.assertFalse(is_error, text)

        # 2. failing calls whose answers carry the token: a non-GraphQL 502 body (the token
        # comes first, so it sits inside the excerpt the error quotes) and GraphQL errors
        self.fake.on("departments", 200, lambda request: (502, f"{bearer_of(request)} rejected"))
        text, is_error = self.mcp.call("shapes_graphql", {"query": DEPARTMENTS_QUERY})
        self.assertTrue(is_error, text)
        self.assertIn("502", text)
        self.fake.on("departments", 200, lambda request: (200, {
            "data": None, "errors": [{"message": f"bad token {bearer_of(request)}"}]}))
        text, is_error = self.mcp.call("shapes_graphql", {"query": DEPARTMENTS_QUERY})
        self.assertFalse(is_error, text)
        self.assertIn("bad token", text)

        # 3. a refused connect for a customer account whose name echoes the token
        self.fake.on("fetchAppConfig", 200, lambda request: (200, connect_answer(
            dict(CUSTOMER_ACCOUNT, name=f"Customer {bearer_of(request)}"))))
        text, is_error = self.connect(refused)
        self.assertTrue(is_error, text)
        self.assertIn("not an internal account", text)
        text, _ = self.mcp.call("shapes_whoami")
        self.assertTrue(text.startswith("not connected"), text)

        # the fake really got both tokens, so the echoes above really carried them
        sent = [bearer_of(request) for request in self.fake.requests]
        self.assertIn(live, sent)
        self.assertIn(refused, sent)
        for token in (live, refused):
            self.assertNoLeak(token)


if __name__ == "__main__":
    unittest.main()
