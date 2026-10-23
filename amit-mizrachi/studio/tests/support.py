"""Shared test helpers: a fresh, private PROJECT_STUDIO_HOME per test."""

import os
import shutil
import tempfile
import unittest


class TempHome(unittest.TestCase):
    """Each test gets its own empty data dir in PROJECT_STUDIO_HOME, removed afterwards."""

    def setUp(self):
        super().setUp()
        self.home = tempfile.mkdtemp(prefix="studio-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        saved = os.environ.get("PROJECT_STUDIO_HOME")
        os.environ["PROJECT_STUDIO_HOME"] = self.home
        self.addCleanup(self._restore, saved)

    @staticmethod
    def _restore(saved):
        if saved is None:
            os.environ.pop("PROJECT_STUDIO_HOME", None)
        else:
            os.environ["PROJECT_STUDIO_HOME"] = saved
