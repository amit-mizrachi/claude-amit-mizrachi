"""Workspace readers: what a night-sprint or night-marathon workspace says about its own progress.

Moved here from `bin/night-watch` so the studio and night-watch read workspaces the same way.
night-watch imports these back; its display filter (drop invalid runs, hide old finished ones)
and all drawing stay in night-watch. The code is unchanged from night-watch, and the parity test
(`studio/tests/test_night_watch_parity.py`) holds night-watch's output byte-identical.

A workspace holds `state/<TAG>.next` (the chain), `state/<TAG>.status` (written last by the
session that ran the tag), `state/<TAG>.queued` (a head of its own), `claim-<TAG>/` and
`<TAG>.session` (running). These readers only READ files; they never write or launch anything.

Public: `DEFAULT_ROOTS`, `TERMINAL`, `read1`, `mtime`, `facts`, `World`, `context_used`, `Stage`,
`tag_state`, `walk_chain`, `base_tag`, `Sprint`.
"""

import glob
import os
import re
import subprocess
import time

HOME = os.path.expanduser("~")
DEFAULT_ROOTS = [os.path.join(HOME, ".claude", "night-sprint"), os.path.join(HOME, "claude-research")]
TERMINAL = ("done", "skipped", "blocked")


# ---------------------------------------------------------------- small file helpers

def read1(path):
    """First line of a file, stripped, or '' when it is missing or unreadable."""
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def facts(ws):
    out = {}
    try:
        with open(os.path.join(ws, "facts.env"), "r", errors="replace") as fh:
            for line in fh:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.rstrip("\n").split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def natural_key(tag):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", tag)]




# ---------------------------------------------------------------- processes and transcripts

class World(object):
    """What one refresh knows about the machine: live processes, and transcript lookups."""

    def __init__(self):
        self.now = time.time()
        self.procs = {}
        try:
            out = subprocess.run(["ps", "-axo", "pid=,command="], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, universal_newlines=True, timeout=5).stdout
            for line in out.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    self.procs[int(parts[0])] = parts[1]
        except Exception:
            pass
        self._transcripts = {}

    def runner_alive(self, state_dir):
        """runner.sh writes the pid of watch.sh. A recycled pid must not pass for the runner."""
        pid = read1(os.path.join(state_dir, "runner.pid"))
        return pid.isdigit() and "watch.sh" in self.procs.get(int(pid), "")

    def transcript(self, sid):
        if not sid:
            return None
        if sid not in self._transcripts:
            hits = glob.glob(os.path.join(HOME, ".claude", "projects", "*", sid + "*.jsonl"))
            self._transcripts[sid] = max(hits, key=mtime) if hits else None
        return self._transcripts[sid]


def context_used(path, window):
    """Percent of the window USED, read the same way context-used.sh reads it: the last
    main-thread assistant turn's input + cache + output tokens. None when it cannot tell."""
    import json
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 400000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"assistant"' not in line or '"usage"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        msg = row.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        used = sum((usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens", "output_tokens"))
        return max(0, min(100, int(round(100.0 * used / (window or 200000)))))
    return None


# ---------------------------------------------------------------- one sprint (a chain of tags)

class Stage(object):
    def __init__(self, name):
        self.name = name
        self.tags = []
        self.status = "pending"
        self.detail = ""
        self.start = 0.0
        self.end = 0.0
        self.revivals = 0


def tag_state(state, tag):
    st = read1(os.path.join(state, tag + ".status"))
    word = re.split(r"[:\s]", st, maxsplit=1)[0].upper() if st else ""
    if word in ("DONE", "SKIPPED", "BLOCKED"):
        return word.lower(), st
    if word == "RELAYED":
        return "relayed", st
    if os.path.isdir(os.path.join(state, "claim-" + tag)) or os.path.exists(os.path.join(state, tag + ".session")):
        return "running", ""
    return "pending", ""


def walk_chain(state):
    """The tags in run order: from the head, follow RELAYED targets and `.next` files."""
    nexts = {}
    for p in glob.glob(os.path.join(state, "*.next")):
        tag = os.path.basename(p)[:-5]
        if tag and not re.search(r"\s", tag):      # a tag with a space is a broken kickoff, not a tag
            nexts[tag] = (read1(p).split() or [""])[0]
    # A QUEUED tag (an async checkpoint review, every ticket of a blitz sprint) is started by the
    # scheduler, not by a predecessor's `.next`, so it is a head of its own.
    queued = set()
    for p in glob.glob(os.path.join(state, "*.queued")):
        tag = os.path.basename(p)[:-len(".queued")]
        if tag and not re.search(r"\s", tag):
            queued.add(tag)
    if not nexts and not queued:
        return []
    targets = set(v for v in nexts.values() if v)

    def head_key(tag):    # tickets, then checkpoint reviews, then the rest (REVIEW-FINAL ...)
        rank = 0 if re.match(r"T\d", tag) else (1 if tag.startswith("REVIEW-C") else 2)
        return (rank, natural_key(tag))

    every = set(nexts) | queued
    heads = sorted((t for t in every if t not in targets), key=head_key) or sorted(every, key=head_key)
    if "T01" in heads:
        heads.remove("T01")
        heads.insert(0, "T01")
    # A relay rewrites its tag's `.next` to the continuation (T01 -> T01c2), and the continuation's
    # own `.next` only appears when it hands on. Until then nothing points at T02, so it looks like
    # a second head. Walking every head in ticket order puts it back where it belongs.
    chain, seen = [], set()
    for tag in heads:
        while tag and tag not in seen and len(chain) < 500:
            seen.add(tag)
            chain.append(tag)
            st = read1(os.path.join(state, tag + ".status"))
            if st.upper().startswith("RELAYED:"):
                tag = (st.split(":", 1)[1].split() or [""])[0]
            else:
                tag = nexts.get(tag, "")
    return chain


def base_tag(tag):
    """T03c2 -> T03. Continuations use a lowercase `c`, so FIX-C1 is left alone."""
    folded = re.sub(r"c\d+$", "", tag)
    return folded or tag


class Sprint(object):
    def __init__(self, ws, world):
        self.ws = ws
        self.state = os.path.join(ws, "state")
        self.world = world
        self.facts = facts(ws)
        self.mode = read1(os.path.join(ws, "MODE")) or self.facts.get("MODE", "code")
        try:
            self.window = int(read1(os.path.join(ws, "CONTEXT_WINDOW")) or self.facts.get("CONTEXT_WINDOW") or 200000)
        except ValueError:
            self.window = 200000
        self.stages = self._stages()
        self.runner = world.runner_alive(self.state)
        self.paused = read1(os.path.join(self.state, "PAUSED"))
        self.pr = read1(os.path.join(self.state, "PR.url"))
        self.acceptance = read1(os.path.join(self.state, "ACCEPTANCE.verdict")).split(" ")[0]
        self.golden = read1(os.path.join(self.state, "GOLDEN.verdict")).split(" ")[0]
        self.events = os.path.join(self.state, "EVENTS.log")
        self.last_event = mtime(self.events)

    def _stages(self):
        order, by_name = [], {}
        for tag in walk_chain(self.state):
            name = base_tag(tag)
            if name not in by_name:
                by_name[name] = Stage(name)
                order.append(by_name[name])
            by_name[name].tags.append(tag)
        for s in order:
            first, last = s.tags[0], s.tags[-1]
            s.status, s.detail = tag_state(self.state, last)
            if s.status == "relayed":
                s.status = "running"         # handing its ticket to the next session
            s.start = mtime(os.path.join(self.state, "claim-" + first)) or mtime(os.path.join(self.state, first + ".session"))
            if s.status in TERMINAL:
                s.end = mtime(os.path.join(self.state, last + ".status"))
            for t in s.tags:
                try:
                    with open(os.path.join(self.state, t + ".revivals")) as fh:
                        s.revivals += sum(1 for line in fh if line.split(" ", 1)[0] in ("resume", "restart"))
                except OSError:
                    pass
        return order

    # derived facts -------------------------------------------------------------------
    @property
    def started(self):
        return any(s.status != "pending" for s in self.stages)

    @property
    def finished(self):
        return bool(self.stages) and all(s.status in TERMINAL for s in self.stages)

    def count(self, *statuses):
        return sum(1 for s in self.stages if s.status in statuses)

    def current(self):
        for s in self.stages:
            if s.status == "running":
                return s
        return None

    def remaining(self):
        return [s for s in self.stages if s.status not in TERMINAL]

    def eta(self):
        spans = [s.end - s.start for s in self.stages if s.status == "done" and s.start and s.end - s.start >= 30]
        left = self.remaining()
        if not spans or not left:
            return None
        avg = sum(spans) / len(spans)
        cur = self.current()
        if not cur or not cur.start:
            return avg * len(left)
        # A stage already past the average is not "done any second now": give it a quarter more.
        return avg * (len(left) - 1) + max(avg - (self.world.now - cur.start), avg * 0.25)

    def session_of(self, stage):
        for t in reversed(stage.tags):
            sid = read1(os.path.join(self.state, t + ".session"))
            if sid:
                return t, sid
        return stage.tags[-1], ""

    def started_at(self):
        first = read1(self.events)
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", first)
        if m:
            try:
                import calendar
                return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                pass
        starts = [s.start for s in self.stages if s.start]
        return min(starts) if starts else 0.0
