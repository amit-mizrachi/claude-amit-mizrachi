"""The pieces together: two MCP server processes, the studio web server, the SessionStart hook
and night-watch, all over one store at once. Each test drives real processes, as a user's
machine would: no SDK function is mocked.

Run by name: python3 -m unittest amit-mizrachi.studio.tests.test_integration (from the repo root).
"""

import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from sdk import api, server

from . import PLUGIN, STUDIO
from .support import Sources
from .test_night_watch_parity import FIXTURES, HERE
from .test_readers import SID_A, SID_C, agent

MCP = os.path.join(STUDIO, "mcp_server.py")
HOOK = os.path.join(PLUGIN, "hooks", "attach-session.sh")
HOOK_TIMEOUT = 5            # hooks.json gives attach-session.sh 5 seconds
WRITES = 12                 # writes per writer in the concurrency test


def init(rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": "initialize", "params": {}}


def call(rid, name, arguments):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


class Machine(Sources):
    """A data dir with the studio web server running and helpers to talk to it, to fresh MCP
    server processes and to the store's file."""

    def setUp(self):
        super().setUp()
        self.addCleanup(api.stop_studio)
        self.port = api.open_studio().port
        self.token = server.read_info()["token"]

    # ------------------------------------------------------------------ web
    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": "127.0.0.1:%d" % self.port}
        data = None
        if method == "POST":
            headers.update({"X-Studio-Token": self.token, "Origin": "http://127.0.0.1:%d" % self.port,
                            "Content-Type": "application/json"})
            data = json.dumps(body or {}).encode("utf-8")
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        payload = json.loads(res.read() or b"null")
        conn.close()
        return res.status, payload

    def post(self, path, body=None):
        return self.request("POST", path, body)

    def first_event(self):
        """Open /events, read the first `event: state` frame, close the stream, return the state."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=30)
        try:
            sock.sendall(("GET /events HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % self.port).encode())
            data = b""
            while b"\r\n\r\n" not in data or b"\n\n" not in data.split(b"\r\n\r\n", 1)[1]:
                chunk = sock.recv(65536)
                self.assertTrue(chunk, "the stream closed before the first event")
                data += chunk
        finally:
            sock.close()
        head, rest = data.split(b"\r\n\r\n", 1)
        self.assertIn(b"text/event-stream", head)
        frame = rest.split(b"\n\n", 1)[0].decode("utf-8")
        self.assertTrue(frame.startswith("event: state\ndata: "), frame[:40])
        return json.loads(frame.split("data: ", 1)[1])

    # ------------------------------------------------------------------ MCP
    def converse(self, requests):
        """One fresh MCP server process: send every request, close stdin, return replies by id."""
        lines = "".join(json.dumps(r) + "\n" for r in requests)
        done = subprocess.run([sys.executable, MCP], input=lines, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, env=dict(os.environ), timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return {r["id"]: r for r in (json.loads(line) for line in done.stdout.splitlines() if line.strip())}

    def tool(self, name, arguments):
        """One tool call in its own MCP process; returns its `result` (structuredContent or error)."""
        return self.converse([init(), call(2, name, arguments)])[2]["result"]

    # ------------------------------------------------------------------ store
    def items(self):
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}


class ConcurrentWriters(Machine):
    def test_two_mcp_processes_and_the_web_write_at_once_and_lose_nothing(self):
        start = threading.Barrier(3)
        replies, web_status, errors = {}, [], []

        def mcp(tag):
            try:
                requests = [init()] + [call(i + 2, "studio_create", {"name": "%s-%02d" % (tag, i)})
                                       for i in range(WRITES)]
                start.wait()
                replies[tag] = self.converse(requests)
            except BaseException as exc:   # a thread's failure must reach the test, not vanish
                errors.append(exc)

        def web():
            try:
                start.wait()
                for i in range(WRITES):
                    web_status.append(self.post("/api/projects", {"name": "W-%02d" % i}))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=mcp, args=("A",)), threading.Thread(target=mcp, args=("B",)),
                   threading.Thread(target=web)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(180)
        self.assertEqual(errors, [])
        for tag in ("A", "B"):
            for rid in range(2, WRITES + 2):
                self.assertNotIn("isError", replies[tag][rid]["result"], replies[tag][rid])
        self.assertEqual([s for s, _ in web_status], [200] * WRITES, web_status)
        names = {p.name for p in api.list_projects(limit=200).projects}
        expected = {"%s-%02d" % (tag, i) for tag in "ABW" for i in range(WRITES)}
        self.assertEqual(expected - names, set())
        self.assertEqual(api.list_projects(limit=200).total, 3 * WRITES + 1)        # + the Inbox

    def test_racing_moves_on_one_revision_let_exactly_one_win(self):
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        api.refresh(force=True)
        item = self.items()[SID_A]
        targets = [api.create_project(n).id for n in ("To A", "To B", "To Web")]
        start = threading.Barrier(3)
        outcomes, errors = {}, []

        def mcp(tag, target):
            try:
                requests = [init(), call(2, "studio_move", {"id": item.id, "to_project_id": target,
                                                            "revision": item.revision})]
                start.wait()
                outcomes[tag] = self.converse(requests)[2]["result"]
            except BaseException as exc:
                errors.append(exc)

        def web(target):
            try:
                start.wait()
                outcomes["W"] = self.post("/api/move", {"target_id": item.id, "to_project_id": target,
                                                        "revision": item.revision})
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=mcp, args=("A", targets[0])),
                   threading.Thread(target=mcp, args=("B", targets[1])), threading.Thread(target=web, args=(targets[2],))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        won = {"A": not outcomes["A"].get("isError"), "B": not outcomes["B"].get("isError"),
               "W": outcomes["W"][0] == 200}
        self.assertEqual(sum(won.values()), 1, outcomes)
        for tag in ("A", "B"):
            if not won[tag]:
                self.assertIn("changed since you looked", outcomes[tag]["content"][0]["text"])
        if not won["W"]:
            self.assertEqual((outcomes["W"][0], outcomes["W"][1]["code"]), (400, "refused"))
        after = self.items()[SID_A]
        self.assertEqual(after.revision, item.revision + 1)
        self.assertEqual(after.project_id, dict(zip("ABW", targets))[[t for t, w in won.items() if w][0]])


class HookNeverBlocks(Machine):
    def fire(self, sid):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_JOB_DIR", "CLAUDE_CODE_ENTRYPOINT")}
        env.update(CLAUDE_PLUGIN_ROOT=PLUGIN, CLAUDE_CODE_ENTRYPOINT="cli")
        payload = json.dumps({"session_id": sid, "cwd": "/somewhere/else", "hook_event_name": "SessionStart",
                              "source": "startup"})
        began = time.time()
        done = subprocess.run(["/bin/bash", HOOK], input=payload, capture_output=True, text=True, env=env,
                              timeout=HOOK_TIMEOUT * 4)
        return done, time.time() - began

    def test_a_store_locked_by_another_writer_still_lets_the_session_start_in_time(self):
        api.list_projects()                                       # the store exists
        holder = sqlite3.connect(os.path.join(self.home, "studio.db"), isolation_level=None, timeout=1)
        self.addCleanup(holder.close)
        holder.execute("BEGIN EXCLUSIVE")                          # another process mid-write, for good
        done, took = self.fire(SID_C)
        holder.execute("ROLLBACK")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        self.assertLess(took, HOOK_TIMEOUT)
        self.assertNotIn(SID_C, self.items())                      # it gave up instead of waiting
        done, _ = self.fire(SID_C)                                 # the next start files it as usual
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.items()[SID_C].project_id, "inbox")

    def test_a_studio_and_mcp_writing_meanwhile_do_not_slow_the_hook_past_its_budget(self):
        stop, errors = threading.Event(), []

        def churn():
            i = 0
            while not stop.is_set():
                try:
                    status, body = self.post("/api/projects", {"name": "churn-%03d" % i})
                    if status != 200:
                        errors.append(body)
                except BaseException as exc:
                    errors.append(exc)
                i += 1

        worker = threading.Thread(target=churn)
        worker.start()
        try:
            self.assertNotIn("isError", self.tool("studio_create", {"name": "During the hook"}))
            done, took = self.fire(SID_C)
        finally:
            stop.set()
            worker.join(60)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        self.assertLess(took, HOOK_TIMEOUT)
        self.assertEqual(errors, [])
        self.assertEqual(self.items()[SID_C].project_id, "inbox")


class NightWatchOnTheFinalTree(Machine):
    def test_night_watch_prints_the_same_board_while_the_studio_reads_the_same_workspaces(self):
        os.environ["PROJECT_STUDIO_ROOTS"] = os.path.join(FIXTURES, "roots", "night-sprint")
        api.refresh(force=True)
        self.assertTrue(api.find_items(kind="night-sprint", refresh=False).total)    # the studio sees them too
        done = subprocess.run([sys.executable, os.path.join(HERE, "night_watch_snapshot.py"),
                               os.path.join(PLUGIN, "bin", "night-watch"), FIXTURES],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        with open(os.path.join(FIXTURES, "expected.txt"), "rb") as fh:
            self.assertEqual(done.stdout.decode("utf-8"), fh.read().decode("utf-8"))


class SseReconnect(Machine):
    def test_a_page_that_reconnects_gets_the_full_state_with_what_changed_meanwhile(self):
        self.assertNotIn("isError", self.tool("studio_create", {"name": "Alpha"}))
        first = self.first_event()
        self.assertEqual([c["project"]["name"] for c in first["cards"]], ["Alpha"])
        self.assertNotIn("isError", self.tool("studio_create", {"name": "Beta"}))   # while no page is open
        again = self.first_event()
        self.assertEqual(sorted(c["project"]["name"] for c in again["cards"]), ["Alpha", "Beta"])
        self.assertEqual(set(again) - {"generated_at"}, set(first) - {"generated_at"})   # a whole state, not a diff
        self.assertTrue(api.studio_status().running)


class StaleUndo(Machine):
    def setUp(self):
        super().setUp()
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        api.refresh(force=True)
        self.one, self.two = api.create_project("One"), api.create_project("Two")

    def test_an_item_moved_by_an_agent_since_cannot_be_undone_from_the_page(self):
        item = self.items()[SID_A]
        status, moved = self.post("/api/move", {"target_id": item.id, "to_project_id": self.one.id,
                                                "revision": item.revision})
        self.assertEqual(status, 200, moved)
        self.assertNotIn("isError", self.tool("studio_move", {"id": item.id, "to_project_id": self.two.id}))
        status, refused = self.post("/api/undo", {"move_id": moved["move_id"]})
        self.assertEqual((status, refused["code"]), (400, "refused"))
        self.assertEqual(refused["message"], "Can't undo: alpha was moved again since.")
        self.assertEqual(self.items()[SID_A].project_id, self.two.id)

    def test_a_project_moved_by_an_agent_since_cannot_be_undone_from_the_page(self):
        child = api.create_project("Child")
        status, moved = self.post("/api/move", {"target_id": child.id, "to_project_id": self.one.id})
        self.assertEqual(status, 200, moved)
        self.assertNotIn("isError", self.tool("studio_move", {"id": child.id, "to_project_id": self.two.id}))
        status, refused = self.post("/api/undo", {"move_id": moved["move_id"]})
        self.assertEqual((status, refused["message"]), (400, "Can't undo: Child was moved again since."))
        self.assertEqual(api.get_project(child.id).parent_id, self.two.id)


class FailedSources(Machine):
    def test_every_source_failing_at_once_marks_nothing_gone_anywhere(self):
        repo, _ = self.git_repo("r", [])
        ws = self.workspace("s", facts={"REPO_PATH": repo, "REPO_SLUG": "me/r", "BRANCH": "feat/a"})
        self.agents([agent(SID_A, "alpha", "/w/alpha")])
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": False,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        api.refresh(force=True)
        before = self.items()
        self.assertTrue({SID_A, "me/r#4", ws} <= set(before))

        self.agents_fail()
        self.write(os.path.join(self.stub, "gh-fail"), "1")
        status, result = self.post("/api/refresh")                 # the banner's Retry
        self.assertEqual((status, result["gone"]), (200, 0), result)

        found = self.tool("studio_find", {"include_gone": True, "limit": 200})["structuredContent"]["items"]
        by_key = {i["key"]: i for i in found}
        self.assertEqual(set(by_key), set(before))
        self.assertEqual([k for k, i in by_key.items() if i["gone"]], [])
        self.assertEqual(by_key[SID_A]["status"], "unknown")
        self.assertEqual(by_key["me/r#4"]["data"]["state"], "open")          # last-good state kept
        status, state = self.request("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["banners"], state)
