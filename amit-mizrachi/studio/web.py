#!/usr/bin/env python3
"""project-studio web - the studio's local web server, a thin adapter over the Project Studio SDK.

Started by `sdk.api.open_studio()` (via `bin/project-studio` or the `studio_open` MCP tool), not by
hand. It listens on 127.0.0.1 only (port `$PROJECT_STUDIO_PORT`, else a free one), writes
`server.json` once it is bound, and stops by itself after `$PROJECT_STUDIO_IDLE` seconds (default
1800) with no live page and no request.

Each route is one SDK call:
    GET  /               static/index.html with this server's token in a meta tag
    GET  /static/<name>  app.css, app.js
    GET  /state          api.home()
    GET  /project?id=    api.project_view(id)
    GET  /inbox          api.inbox_view() (the Inbox drawer)
    GET  /choices?id=    api.move_choices(id) ("Move to..." and "Set parent")
    GET  /events         SSE: `event: state` with the full home state first, then on every change
    POST /api/projects   {"name": ...} -> api.create_project
    POST /api/refresh    api.refresh(force=True) (the banner's Retry)
    POST /api/rename     {"project_id", "name"} -> api.rename_project
    POST /api/archive    {"project_id"} -> api.archive_project
    POST /api/unarchive  {"project_id"} -> api.unarchive_project ("Show archived" and an archived project's view)
    POST /api/link       {"project_id", "other_id"} -> api.link_projects
    POST /api/unlink     {"project_id", "other_id"} -> api.unlink_projects (the x on a "Linked: ..." name)
    POST /api/open       {"item_id", "target"} -> api.open_target (the URL or path comes from the store)
    POST /api/terminal   {"item_id", "confirmed"} -> api.open_in_terminal
    POST /api/command    {"item_id"} -> api.terminal_command ("Copy command")
    POST /api/move       {"target_id", "to_project_id", "revision"} -> api.move (a drop, Move to..., Set parent)
    POST /api/undo       {"move_id"} -> api.undo_move
    POST /api/accept     {"item_id"} -> api.accept_suggestion
    POST /api/rule       {"move_id"} -> api.save_rule_from_move ("Always file items like this here")
    POST /api/rule/delete {"rule_id"} -> api.delete_rule
    POST /api/rule/add   {"project_id", "signal", "pattern", "apply", "dry_run"} -> api.add_rule (the "Add rule" form)
    POST /shutdown       stop
Every request needs `Host: 127.0.0.1:<port>`; every POST needs the token (X-Studio-Token) and, when
it sends one, this Origin. The guard and the lifecycle live in `sdk/server.py`, every rule the page
shows in `sdk/home.py`.

Zero dependencies. Python 3.9+.
"""

import html
import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sdk import api, server  # noqa: E402
from sdk.errors import ReadOnlyStore, StudioError  # noqa: E402
from sdk.results import to_dict  # noqa: E402

STATIC = os.path.join(HERE, "static")
STATIC_TYPES = {"app.css": "text/css; charset=utf-8", "app.js": "text/javascript; charset=utf-8"}
POLL, KEEPALIVE = 2.0, 15.0
MAX_BODY = 64 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


ACTIONS = {
    "/api/rename": lambda b: api.rename_project(b.get("project_id"), b.get("name")),
    "/api/archive": lambda b: api.archive_project(b.get("project_id")),
    "/api/unarchive": lambda b: api.unarchive_project(b.get("project_id")),
    "/api/link": lambda b: api.link_projects(b.get("project_id"), b.get("other_id")),
    "/api/unlink": lambda b: api.unlink_projects(b.get("project_id"), b.get("other_id")),
    "/api/open": lambda b: api.open_target(b.get("item_id"), b.get("target") or "default"),
    "/api/terminal": lambda b: api.open_in_terminal(b.get("item_id"), b.get("confirmed") is True),
    "/api/command": lambda b: api.terminal_command(b.get("item_id")),
    "/api/move": lambda b: api.move(b.get("target_id"), b.get("to_project_id"), b.get("revision")),
    "/api/undo": lambda b: api.undo_move(b.get("move_id")),
    "/api/accept": lambda b: api.accept_suggestion(b.get("item_id")),
    "/api/dismiss": lambda b: api.dismiss_item(b.get("item_id")),
    "/api/restore": lambda b: api.restore_item(b.get("item_id")),
    "/api/mark-done": lambda b: api.mark_done(b.get("item_id")),
    "/api/rule": lambda b: api.save_rule_from_move(b.get("move_id")),
    "/api/rule/delete": lambda b: api.delete_rule(b.get("rule_id")),
    "/api/rule/add": lambda b: api.add_rule(b.get("project_id"), b.get("signal"), b.get("pattern"),
                                            apply=b.get("apply") is True, dry_run=b.get("dry_run") is True),
}


def log(msg):
    sys.stderr.write("[project-studio web] %s %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def home_json():
    """The home state as JSON text, and the same without its timestamp (to tell a real change)."""
    body = to_dict(api.home())
    return json.dumps(body, sort_keys=True), json.dumps(dict(body, generated_at=""), sort_keys=True)


class Hub(object):
    """The live pages (SSE clients), the poll thread that feeds them, and the idle clock."""

    def __init__(self, idle):
        self.idle = idle
        self.lock = threading.Lock()
        self.clients = set()
        self.last = time.time()
        self.seen = None
        self.wake = threading.Event()           # run() waits on and clears this one
        self.refresh_wake = threading.Event()   # refresh() waits on and clears this one

    def touch(self):
        self.last = time.time()

    def join(self):
        q = queue.Queue(maxsize=8)
        with self.lock:
            self.clients.add(q)
        self.wake.set()
        self.refresh_wake.set()
        return q

    def leave(self, q):
        with self.lock:
            self.clients.discard(q)
        self.touch()

    def broadcast(self, text):
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(text)
            except queue.Full:   # a stuck page misses a frame; the next one is a full state again
                pass

    def refresh(self):
        """Refresh every 2 s while a page is open, in its own thread, so a slow source never holds
        back a state frame."""
        while True:
            if not self.clients:
                self.refresh_wake.wait(POLL)
                self.refresh_wake.clear()
                continue
            try:
                api.refresh()
            except ReadOnlyStore:   # a newer SDK's store: show what it holds, refresh nothing
                pass
            except Exception as exc:   # one bad refresh must not end the live view
                log("refresh failed: %r" % (exc,))
            time.sleep(POLL)

    def run(self, httpd):
        """Re-read the home state every 2 s while a page is open and send it on a change; stop when idle."""
        threading.Thread(target=self.refresh, daemon=True).start()
        while True:
            if not self.clients:
                if time.time() - self.last > self.idle:
                    log("idle for %d s, stopping" % self.idle)
                    httpd.shutdown()
                    return
                self.wake.wait(POLL)
                self.wake.clear()
                continue
            try:
                text, key = home_json()
            except Exception as exc:   # one bad poll must not end the live view
                log("poll failed: %r" % (exc,))
            else:
                if key != self.seen:
                    self.seen = key
                    self.broadcast(text)
            time.sleep(POLL)


class Handler(BaseHTTPRequestHandler):
    server_version = "project-studio"

    def log_message(self, fmt, *args):
        log("%s %s" % (self.address_string(), fmt % args))

    @property
    def port(self):
        return self.server.server_address[1]

    def send(self, status, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, value):
        self.send(status, json.dumps(value, sort_keys=True))

    def problem(self, status, code, message):
        self.send_json(status, {"code": code, "message": message})

    def guarded(self, mutation):
        self.server.hub.touch()
        if not server.host_ok(self.headers.get("Host"), self.port):
            self.problem(403, "forbidden", "Open the studio at http://127.0.0.1:%d/." % self.port)
            return False
        if mutation and not server.mutation_ok(self.headers.get(server.TOKEN_HEADER), self.headers.get("Origin"),
                                               self.port, self.server.token):
            self.problem(403, "forbidden", "This request did not come from the studio page.")
            return False
        return True

    def call(self, fn):
        try:
            self.send_json(200, to_dict(fn()))
        except StudioError as exc:
            self.problem(400, exc.code, str(exc))
        except Exception as exc:
            log("%s failed: %r" % (self.path, exc))
            self.problem(500, "error", "Project Studio error: %s" % exc)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("body too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("body must be a JSON object")
        return value

    def do_GET(self):
        if not self.guarded(False):
            return
        path, _, query = self.path.partition("?")
        if path == "/":
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
                page = fh.read().replace("{{TOKEN}}", html.escape(self.server.token, quote=True))
            self.send(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
        elif path.startswith("/static/") and path[len("/static/"):] in STATIC_TYPES:
            name = path[len("/static/"):]
            with open(os.path.join(STATIC, name), "rb") as fh:
                self.send(200, fh.read(), STATIC_TYPES[name])
        elif path == "/state":
            self.call(api.home)
        elif path == "/project":
            self.call(lambda: api.project_view((parse_qs(query).get("id") or [""])[0]))
        elif path == "/inbox":
            self.call(api.inbox_view)
        elif path == "/choices":
            self.call(lambda: api.move_choices((parse_qs(query).get("id") or [""])[0]))
        elif path == "/events":
            self.events()
        else:
            self.problem(404, "not_found", "No such page.")

    def do_POST(self):
        if not self.guarded(True):
            return
        try:
            body = self.body()
        except ValueError:
            self.problem(400, "invalid_input", "The request body must be a JSON object of at most 64 KB.")
            return
        if self.path == "/api/projects":
            self.call(lambda: api.create_project(body.get("name")))
        elif self.path == "/api/refresh":
            self.call(lambda: api.refresh(force=True))
        elif self.path in ACTIONS:
            self.call(lambda: ACTIONS[self.path](body))
        elif self.path == "/shutdown":
            self.send_json(200, {"stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self.problem(404, "not_found", "No such action.")

    def events(self):
        q = self.server.hub.join()
        try:
            text, _ = home_json()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(("event: state\ndata: %s\n\n" % text).encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    chunk = "event: state\ndata: %s\n\n" % q.get(timeout=KEEPALIVE)
                except queue.Empty:
                    chunk = ": keepalive\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (OSError, ValueError):   # the page went away
            pass
        except StudioError as exc:
            log("events failed: %s" % exc)
        finally:
            self.server.hub.leave(q)


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", server.listen_port()), Handler)
    httpd.daemon_threads = True
    httpd.token = server.new_token()
    httpd.hub = Hub(server.idle_seconds())
    pid, port = os.getpid(), httpd.server_address[1]
    server.write_info(pid, port, server.code_version(), httpd.token)
    log("listening on http://127.0.0.1:%d/ (pid %d)" % (port, pid))
    threading.Thread(target=httpd.hub.run, args=(httpd,), daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.clear_info(pid)
        httpd.server_close()
        log("stopped")


if __name__ == "__main__":
    main()
