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

    def __init__(self, api_url: str | None):
        env = {k: v for k, v in os.environ.items()
               if k != API_URL_ENV and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        if api_url is not None:
            env[API_URL_ENV] = api_url
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

    def start_mcp(self, api_url: str | None) -> McpClient:
        client = McpClient(api_url)
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
        for name in ("shapes_connect", "shapes_whoami", "shapes_disconnect"):
            self.assertIn(name, tools)
            description = tools[name]["description"]
            self.assertIn("1 hour", description, name)
            self.assertIn("one internal Shapes account", description, name)
        self.assertEqual(tools["shapes_connect"]["inputSchema"]["required"], ["link"])

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


if __name__ == "__main__":
    unittest.main()
