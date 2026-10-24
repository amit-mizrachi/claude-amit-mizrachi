"""The studio web server over a real socket: the launcher reuses a running server, the Host and
token/Origin guards, /state, the first SSE event, and the page script writing text only as text."""

import http.client
import json
import os
import re
import socket
import threading
import time

import web
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
        self.assertIn("minmax(min(40%,140px),1fr)", re.search(r"\.run\{([^}]*)\}", css).group(1))   # sprint 3
        # ticket 02: the name keeps a little room beside its links and wraps in it, never past the cell
        self.assertNotIn("flex:none", bar)
        self.assertIn("width:14px;flex:0 1 auto", segment)
        self.assertIn(".run .st span:not(.bar){flex:none}", css)   # the words keep their width, the bar gives

    def test_a_sub_project_block_opens_the_sub_project_not_its_row(self):
        script = self.request("GET", "/static/app.js")[1].decode()
        line = re.search(r"function subBlock\(s\) \{(.*?)\n  \}\n", script, re.S).group(1)
        self.assertIn('var href = "#/p/" + encodeURIComponent(s.project_id);', line)
        self.assertIn("function go(e) { e.stopPropagation(); window.location.hash = href; }", line)
        self.assertIn('node.addEventListener("click", go);', line)
        self.assertIn('if (e.key === "Enter") { go(e); }', line)
        self.assertIn("c.sub_projects.forEach(function (s) { blocks.appendChild(subBlock(s)); });", script)
        css = self.request("GET", "/static/app.css")[1].decode()
        name = re.search(r"\.bh \.nm\{([^}]*)\}", css).group(1)
        self.assertIn("text-overflow:ellipsis", name)
        self.assertIn("max-width:100%", name)
        self.assertIn("min-width:0", re.search(r"\.run \.st span\.in\{([^}]*)\}", css).group(1))

    def test_nothing_in_a_row_runs_past_its_edge(self):
        """D3: a chip cut to "in Ma..." and a line past the card's edge. A row clips, its head line and a
        run's status line wrap, and every word in them is capped at the row's width."""
        css = self.request("GET", "/static/app.css")[1].decode()
        self.assertIn(".prow{overflow:hidden}", css)
        self.assertIn(".prow .run .st{flex-wrap:wrap", css)
        self.assertIn("flex-wrap:wrap", re.search(r"\.prow \.ct\{([^}]*)\}", css).group(1))
        self.assertIn("max-width:100%", re.search(r"\.run \.st span\{([^}]*)\}", css).group(1))
        self.assertIn("minmax(min(100%,300px),1fr)", re.search(r"\.runs\{([^}]*)\}", css).group(1))

    def test_the_rows_keep_their_load_order_until_re_sort(self):
        script = self.request("GET", "/static/app.js")[1].decode()
        self.assertIn("if (!pinned) { pin(s); }", script)
        self.assertIn('button("Re-sort", "ghost", function () { pin(lastState); render(lastState); })', script)
        self.assertIn('<span id="resort"></span>', self.request("GET", "/")[1].decode())

    def test_a_read_shows_only_in_the_header_and_a_poll_keeps_what_did_not_change(self):
        """Ticket 03: "Still reading PRs..." was a line above the rows that pushed them down and up on
        every read. The read is now the header's fixed-width status line, and a poll redraws through
        keep(), which leaves a row, a banner or a list whose data did not change in the page."""
        script = self.request("GET", "/static/app.js")[1].decode()
        render = re.search(r"  function render\(s\) \{(.*?)\n  \}\n", script, re.S).group(1)
        self.assertIn('text($("age"), s.status_text);', render)
        self.assertIn('keep($("banners"), s.banners.map(banner));', render)
        self.assertIn('keep($("body"), nodes);', render)
        for gone in ("reading", "clear(", "appendChild"):
            self.assertNotIn(gone, render)
        self.assertIn('return keyed(node, b.source + " " + b.key, JSON.stringify(b));', script)
        self.assertIn("c.project.id, JSON.stringify(c));", script)
        css = self.request("GET", "/static/app.css")[1].decode()
        self.assertIn("flex:none;width:18em", re.search(r"#age\{([^}]*)\}", css).group(1))

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


class RefreshThread(TempHome):
    def test_the_refresh_thread_sleeps_once_every_page_is_gone(self):
        hub = web.Hub(idle=60)
        waits = []
        wait = hub.refresh_wake.wait
        hub.refresh_wake.wait = lambda timeout: waits.append(timeout) or wait(timeout)
        hub.leave(hub.join())   # join sets both events; run() has not cleared its own one
        threading.Thread(target=hub.refresh, daemon=True).start()
        time.sleep(0.3)
        self.assertLessEqual(len(waits), 2, "the refresh thread spins on a set event")
        self.assertFalse(hub.refresh_wake.is_set())
