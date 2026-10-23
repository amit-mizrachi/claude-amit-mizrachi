"""The plugin wiring: the .mcp.json entries, and build rule 1 (no SQL outside studio/sdk/)."""

import ast
import glob
import json
import os
import unittest

from . import PLUGIN, STUDIO


class McpJson(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(PLUGIN, ".mcp.json")) as fh:
            self.servers = json.load(fh)["mcpServers"]

    def test_project_studio_is_registered(self):
        self.assertEqual(self.servers["project-studio"],
                         {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/studio/mcp_server.py"]})

    def test_codex_bridge_is_unchanged(self):
        self.assertEqual(self.servers["codex-bridge"],
                         {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/mcp/codex-bridge/server.py"]})

    def test_the_registered_server_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(STUDIO, "mcp_server.py")))


class OneLayer(unittest.TestCase):
    """Build rule 1: adapters parse, call one SDK function, serialise. SQL lives only in studio/sdk/."""

    MARKERS = ("sqlite3", "SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "BEGIN IMMEDIATE")

    def adapters(self):
        sdk = os.path.join(STUDIO, "sdk") + os.sep
        tests = os.path.join(STUDIO, "tests") + os.sep
        files = [p for p in glob.glob(os.path.join(STUDIO, "**", "*.py"), recursive=True)
                 if not p.startswith(sdk) and not p.startswith(tests)]
        return files + [os.path.join(PLUGIN, "bin", "night-watch")]

    def test_no_sql_outside_the_sdk(self):
        for path in self.adapters():
            with open(path) as fh:
                text = fh.read()
            for marker in self.MARKERS:
                self.assertNotIn(marker, text, "%s holds %r - move it into studio/sdk/" % (path, marker))

    def test_every_mcp_handler_is_one_sdk_call(self):
        """Each studio_* handler is `return api.<function>(...)` and nothing else: no branch, loop or rule."""
        with open(os.path.join(STUDIO, "mcp_server.py")) as fh:
            tree = ast.parse(fh.read())
        handlers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("tool_")]
        self.assertGreaterEqual(len(handlers), 9)
        for fn in handlers:
            self.assertEqual(len(fn.body), 1, fn.name)
            ret = fn.body[0]
            self.assertIsInstance(ret, ast.Return, fn.name)
            self.assertIsInstance(ret.value, ast.Call, fn.name)
            self.assertEqual(ast.unparse(ret.value.func).split(".")[0], "api", fn.name)
            calls = [n for n in ast.walk(ret) if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("api.")]
            self.assertEqual(len(calls), 1, fn.name)
            self.assertFalse([n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.For, ast.While, ast.IfExp))], fn.name)
