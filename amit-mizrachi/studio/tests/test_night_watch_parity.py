"""night-watch prints exactly what it printed before its readers moved into the SDK.

`fixtures/night-watch/expected.txt` was captured from the night-watch of the base commit, before
the move, by `night_watch_snapshot.py` over trimmed copies of real workspaces. Re-capture it only
for an intended change to night-watch's output, never to make this test pass.
"""

import os
import subprocess
import sys
import unittest

from . import PLUGIN

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "night-watch")


class NightWatchParity(unittest.TestCase):
    def test_board_output_is_byte_identical(self):
        done = subprocess.run([sys.executable, os.path.join(HERE, "night_watch_snapshot.py"),
                               os.path.join(PLUGIN, "bin", "night-watch"), FIXTURES],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        with open(os.path.join(FIXTURES, "expected.txt"), "rb") as fh:
            expected = fh.read()
        self.assertEqual(done.stdout.decode("utf-8"), expected.decode("utf-8"))
