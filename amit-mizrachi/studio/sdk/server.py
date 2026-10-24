"""The studio web server's lifecycle and its request guard. `studio/web.py` serves; this module
decides when one runs and who may talk to it.

Rules this module keeps:
- One studio per data dir. `$PROJECT_STUDIO_HOME/server.json` ({pid, port, version, token},
  mode 0600, written atomically by the server after it binds) says which one runs.
- `open_studio()` reuses a live server of the same code version. A server of an older version is
  asked to stop (POST /shutdown with its token), then a new one starts. Nothing is ever killed.
- The version is a hash of the name, size and mtime of every studio source file, so editing
  the code (or a plugin update) restarts the server on the next open.
- A lock file serialises launches, so two opens at once share one server.
- The server listens on 127.0.0.1 only. Every request must carry `Host: 127.0.0.1:<port>`
  (DNS rebinding); every POST must carry the token and, when it has an Origin, this origin (CSRF).
"""

import fcntl
import glob
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager

from . import store
from .errors import StartFailed, StudioError
from .results import StudioServer

STUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(STUDIO, "web.py")
SERVER_FILE, LOCK_FILE, LOG_FILE = "server.json", "server.lock", "studio.log"
TOKEN_HEADER = "X-Studio-Token"
START_WAIT = 5.0
STOP_WAIT = 5.0
IDLE_DEFAULT = 1800


def server_path():
    """Where the running server says where it is."""
    return os.path.join(store.home(), SERVER_FILE)


def log_path():
    """Where the server's output goes."""
    return os.path.join(store.home(), LOG_FILE)


def code_version():
    """A short hash over (relative path, size, mtime) of studio/*.py, studio/sdk/**/*.py and studio/static/*."""
    paths = (glob.glob(os.path.join(STUDIO, "*.py")) + glob.glob(os.path.join(STUDIO, "sdk", "**", "*.py"), recursive=True)
             + glob.glob(os.path.join(STUDIO, "static", "*")))
    digest = hashlib.sha256()
    for path in sorted(paths):
        st = os.stat(path)
        digest.update(("%s\0%d\0%d\n" % (os.path.relpath(path, STUDIO), st.st_size, st.st_mtime_ns)).encode())
    return digest.hexdigest()[:16]


def new_token():
    """A fresh secret for one server's lifetime."""
    return secrets.token_urlsafe(32)


def listen_port():
    """`$PROJECT_STUDIO_PORT`, else 0 (any free port)."""
    raw = os.environ.get("PROJECT_STUDIO_PORT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) < 65536 else 0


def idle_seconds():
    """`$PROJECT_STUDIO_IDLE`: stop after this long with no SSE client and no request (default 1800)."""
    raw = os.environ.get("PROJECT_STUDIO_IDLE", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else IDLE_DEFAULT


# ---------------------------------------------------------------- server.json

def read_info():
    """server.json as a dict, or None when there is none or it is malformed."""
    try:
        with open(server_path()) as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("pid"), int) or not isinstance(info.get("port"), int):
        return None
    if not isinstance(info.get("version"), str) or not isinstance(info.get("token"), str):
        return None
    return info


def write_info(pid, port, version, token):
    """Write server.json atomically, mode 0600 (the server calls this right after it binds)."""
    home = store.home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".server-", dir=home)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"pid": pid, "port": port, "version": version, "token": token}, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, server_path())
    except BaseException:
        os.unlink(tmp)
        raise


def clear_info(pid):
    """Remove server.json when it still names `pid` (the server calls this as it stops)."""
    info = read_info()
    if info and info["pid"] == pid:
        try:
            os.unlink(server_path())
        except OSError:
            pass


def alive(pid):
    """True when `pid` is a running studio web server (`ps` shows web.py in its command)."""
    try:
        out = subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return "web.py" in out


@contextmanager
def _lock():
    home = store.home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    with open(os.path.join(home, LOCK_FILE), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---------------------------------------------------------------- lifecycle

def _result(info, running, started=False):
    return StudioServer(url="http://127.0.0.1:%d/" % info["port"], pid=info["pid"], port=info["port"],
                        version=info["version"], running=running, started=started)


def _stopped():
    return StudioServer(url="", pid=0, port=0, version=code_version(), running=False)


def _ask_to_stop(info):
    request = urllib.request.Request("http://127.0.0.1:%d/shutdown" % info["port"], data=b"{}", method="POST",
                                     headers={TOKEN_HEADER: info["token"], "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a proxy
    try:
        opener.open(request, timeout=3).read()
        return True
    except (OSError, ValueError):
        return False


def _wait(condition, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def _spawn():
    with open(log_path(), "ab") as log:
        return subprocess.Popen([sys.executable, WEB], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True)


def open_studio():
    """Make sure a studio of this code version runs, and say where (see the module doc)."""
    with _lock():
        info = read_info()
        version = code_version()
        if info and alive(info["pid"]):
            if info["version"] == version:
                return _result(info, True)
            _ask_to_stop(info)
            _wait(lambda: not alive(info["pid"]), STOP_WAIT)
        proc = _spawn()
        if not _wait(lambda: (read_info() or {}).get("pid") == proc.pid or proc.poll() is not None, START_WAIT):
            raise StartFailed("The studio did not start within %d s. See %s." % (START_WAIT, log_path()))
        info = read_info()
        if not info or info["pid"] != proc.pid:
            raise StartFailed("The studio stopped as it started. See %s." % log_path())
        return _result(info, True, started=True)


def studio_status():
    """The running studio, or `running` False."""
    info = read_info()
    if info and alive(info["pid"]):
        return _result(info, True)
    return _stopped()


def stop_studio():
    """Ask the running studio to stop (POST /shutdown with its token) and wait for it. Never kills."""
    with _lock():
        info = read_info()
        if not info or not alive(info["pid"]):
            return _stopped()
        if not _ask_to_stop(info):
            raise StudioError("The studio (pid %d) did not answer the stop request." % info["pid"])
        gone = _wait(lambda: not alive(info["pid"]), STOP_WAIT)
        return _result(info, running=not gone)


# ---------------------------------------------------------------- guard

def host_ok(host, port):
    """Only `Host: 127.0.0.1:<port>` is served, so a rebinding DNS name can never reach the studio."""
    return host == "127.0.0.1:%d" % port


def mutation_ok(token_header, origin, port, token):
    """A POST needs this server's token, and an Origin (when sent) of this server."""
    if not token or not isinstance(token_header, str) or not hmac.compare_digest(token_header, token):
        return False
    return origin is None or origin == "http://127.0.0.1:%d" % port
