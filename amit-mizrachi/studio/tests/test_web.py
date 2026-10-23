"""The studio web server over a real socket: the launcher reuses a running server, the Host and
token/Origin guards, /state, the first SSE event, and the page script writing text only as text."""

import http.client
import json
import os
import re
import socket

from sdk import api, server

from . import STUDIO
from .support import TempHome


class Guards(TempHome):
    def test_host_must_be_this_server_exactly(self):
        self.assertTrue(server.host_ok("127.0.0.1:8123", 8123))
        for host in ("localhost:8123", "127.0.0.1", "127.0.0.1:8124", "evil.example", None):
            self.assertFalse(server.host_ok(host, 8123), host)

    def test_a_mutation_needs_the_token_and_this_origin(self):
        self.assertTrue(server.mutation_ok("t0k", None, 8123, "t0k"))
        self.assertTrue(server.mutation_ok("t0k", "http://127.0.0.1:8123", 8123, "t0k"))
        self.assertFalse(server.mutation_ok(None, None, 8123, "t0k"))
        self.assertFalse(server.mutation_ok("nope", None, 8123, "t0k"))
        self.assertFalse(server.mutation_ok("t0k", "http://evil.example", 8123, "t0k"))
        self.assertFalse(server.mutation_ok("t0k", "null", 8123, "t0k"))


class Web(TempHome):
    def setUp(self):
        super().setUp()
        self.addCleanup(api.stop_studio)
        self.studio = api.open_studio()
        self.port = self.studio.port
        self.token = server.read_info()["token"]

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        sent = {"Host": "127.0.0.1:%d" % self.port}
        sent.update(headers or {})
        conn.request(method, path, body=body, headers=sent)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, data

    def create(self, name, headers):
        return self.request("POST", "/api/projects", json.dumps({"name": name}).encode(), headers)

    def test_a_second_open_reuses_the_running_server(self):
        self.assertTrue(self.studio.started)
        again = api.open_studio()
        self.assertEqual((again.pid, again.port, again.started), (self.studio.pid, self.port, False))
        self.assertEqual(api.studio_status().pid, self.studio.pid)
        self.assertEqual(oct(os.stat(server.server_path()).st_mode & 0o777), "0o600")

    def test_a_wrong_host_is_refused(self):
        status, body = self.request("GET", "/state", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["code"], "forbidden")
        self.assertEqual(self.request("GET", "/", headers={"Host": "evil.example"})[0], 403)

    def test_a_post_without_the_token_or_from_another_origin_is_refused(self):
        self.assertEqual(self.create("x", {})[0], 403)
        self.assertEqual(self.create("x", {"X-Studio-Token": "wrong"})[0], 403)
        self.assertEqual(self.create("x", {"X-Studio-Token": self.token, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/shutdown", b"{}")[0], 403)
        self.assertEqual(api.studio_status().running, True)

    def test_state_returns_names_raw_and_the_page_sets_them_as_text(self):
        status, body = self.create("<b>x</b>", {"X-Studio-Token": self.token,
                                                "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 200, body)
        status, body = self.request("GET", "/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual([c["project"]["name"] for c in state["cards"]], ["<b>x</b>"])
        with open(os.path.join(STUDIO, "static", "app.js")) as fh:
            script = fh.read()
        self.assertIn("textContent", script)
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(sink, script)

    def test_a_studio_error_is_a_400_with_its_code(self):
        status, body = self.create("", {"X-Studio-Token": self.token})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["code"], "invalid_input")

    def test_the_page_carries_the_token_and_only_known_static_files_are_served(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(('<meta name="studio-token" content="%s">' % self.token).encode(), body)
        self.assertEqual(self.request("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/static/app.css")[0], 200)
        self.assertEqual(self.request("GET", "/static/../web.py")[0], 404)

    def test_a_long_run_bar_shrinks_to_fit_its_card(self):
        """A 17-ticket run's bar was 17 fixed 14px segments and ran out of the card (dogfood, T05)."""
        css = self.request("GET", "/static/app.css")[1].decode()
        bar = re.search(r"\.bar\{([^}]*)\}", css).group(1)
        segment = re.search(r"\.bar i\{([^}]*)\}", css).group(1)
        self.assertIn("min-width:0", bar)
        self.assertIn("minmax(0,1fr)", re.search(r"\.run\{([^}]*)\}", css).group(1))
        self.assertNotIn("flex:none", bar)
        self.assertIn("width:14px;flex:0 1 auto", segment)
        self.assertIn(".run .st span:not(.bar){flex:none}", css)   # the words keep their width, the bar gives

    def test_the_first_event_is_a_full_snapshot(self):
        api.create_project("Alpha")
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.addCleanup(sock.close)
        sock.sendall(("GET /events HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % self.port).encode())
        data = b""
        while b"\r\n\r\n" not in data or b"\n\n" not in data.split(b"\r\n\r\n", 1)[1]:
            chunk = sock.recv(65536)
            self.assertTrue(chunk, "the stream closed before the first event")
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        self.assertIn(b"text/event-stream", head)
        first = rest.split(b"\n\n", 1)[0].decode()
        self.assertTrue(first.startswith("event: state\ndata: "), first[:40])
        state = json.loads(first.split("data: ", 1)[1])
        self.assertEqual([c["project"]["name"] for c in state["cards"]], ["Alpha"])
        for key in ("caption", "inbox_count", "source_age", "loading", "first_run", "banners"):
            self.assertIn(key, state)

    def test_stop_asks_the_server_to_go_and_clears_server_json(self):
        stopped = api.stop_studio()
        self.assertFalse(stopped.running)
        self.assertIsNone(server.read_info())
        self.assertFalse(api.studio_status().running)
