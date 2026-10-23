#!/usr/bin/env python3
"""Print night-watch's board over the fixture workspaces, with the clock and `ps` pinned.

    python3 night_watch_snapshot.py <path to bin/night-watch> <fixtures/night-watch dir>

The fixtures are copied to a temp dir, every file gets the mtime its MTIMES line gives it, HOME
points at the fixture `home/` (for transcripts), `ps` answers from the fixture `PS` file, and the
clock is frozen 10 minutes after T0. So the output depends only on night-watch's own code, and
the parity test can compare it byte for byte with `expected.txt`, captured before the readers
moved into the SDK.
"""

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

WIDTH = 110


def pin_mtimes(root):
    with open(os.path.join(root, "MTIMES")) as fh:
        lines = [line.rstrip("\n") for line in fh if not line.startswith("#")]
    t0 = int(lines[0])
    for line in lines[1:]:
        offset, rel = line.split(" ", 1)
        os.utime(os.path.join(root, rel), (t0 + int(offset), t0 + int(offset)))
    return t0


def fake_ps(root):
    with open(os.path.join(root, "PS")) as fh:
        out = fh.read()

    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(["ps"], 0, stdout=out, stderr="")
    return run


def load(path):
    loader = importlib.machinery.SourceFileLoader("night_watch_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main(argv):
    night_watch, fixtures = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    work = tempfile.mkdtemp(prefix="nw-snapshot-")
    try:
        root = os.path.join(work, "fx")
        shutil.copytree(fixtures, root)
        t0 = pin_mtimes(root)
        now = t0 + 600
        os.environ["HOME"] = os.path.join(root, "home")
        os.environ["TZ"] = "UTC"
        time.tzset()
        time.time = lambda: float(now)
        subprocess.run = fake_ps(root)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(now, tz)

        nw = load(night_watch)
        nw.datetime = FixedDatetime
        os.chdir(root)      # relative roots, so no temp path reaches the output
        roots = [os.path.join("roots", r) for r in ("night-sprint", "claude-research", "empty-root")]
        sty = nw.Style(False)
        out = []
        for title, filters, show_all in (("recent", [], False), ("all", [], True),
                                         ("filtered", ["studio", "deel"], False),
                                         ("empty", [], False)):
            use = roots if title != "empty" else [os.path.join("roots", "empty-root")]
            out.append("=== %s ===" % title)
            out.extend(nw.board(use, filters, show_all, WIDTH, sty, 1))
        sys.stdout.write("\n".join(out) + "\n")
    finally:
        os.chdir("/")
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
