"""The project-studio CLI's read commands, driven as a subprocess like a person at a terminal."""

import json
import os
import subprocess
import sys

from sdk import api
from sdk.results import to_dict

from . import PLUGIN
from .support import Sources
from .test_readers import SID_A, SID_B, agent

BIN = os.path.join(PLUGIN, "bin", "project-studio")


class Cli(Sources):
    def run_cli(self, *argv):
        """(exit code, stdout, stderr); the environment is TempHome's, so the store is the temp one."""
        done = subprocess.run([sys.executable, BIN] + list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        return out

    def json_ok(self, *argv):
        return json.loads(self.ok(*argv))

    def tree(self):
        self.alpha, self.beta = api.create_project("Alpha"), api.create_project("Beta")
        self.docs_a = api.create_project("Docs", parent_id=self.alpha.id)
        self.docs_b = api.create_project("Docs", parent_id=self.beta.id)

    def sessions(self):
        self.agents([agent(SID_A, "alpha work", "/w/proj/alpha"), agent(SID_B, "beta work", "/w/proj/beta")])
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(refresh=False).items}

    # ------------------------------------------------------------ list

    def test_list_prints_the_tree_with_short_ids_and_run_lines(self):
        self.tree()
        lines = self.ok("list").splitlines()
        self.assertEqual(lines[0].split(), ["inbox", "Inbox", "0", "items"])
        self.assertTrue(lines[1].startswith(self.alpha.id[:8] + "  Alpha"), lines)
        self.assertIn("    Docs", lines[2])                       # nested under Alpha
        self.assertTrue(lines[1].endswith("no runs"), lines)

    def test_list_json_is_the_sdk_shape_with_run_lines(self):
        self.tree()
        api.archive_project(self.beta.id)
        out = self.json_ok("list", "--json")
        self.assertEqual(out, json.loads(json.dumps(to_dict(api.list_projects(with_runs=True)))))
        self.assertNotIn(self.beta.id, [p["id"] for p in out["projects"]])
        self.assertEqual(out["run_lines"][self.alpha.id], "no runs")
        self.assertNotIn("inbox", out["run_lines"])
        everything = self.json_ok("--json", "list", "--all")       # --json before the command works too
        self.assertIn(self.beta.id, [p["id"] for p in everything["projects"]])
        self.assertIn("(archived)", self.ok("list", "--all"))

    def test_list_shows_a_night_run_and_a_limit_footer(self):
        self.tree()
        self.workspace("sprint-one")
        api.refresh(force=True)
        run = api.find_items(kind="night-sprint", refresh=False).items[0]
        api.move_item(run.id, self.alpha.id)
        alpha_line = [l for l in self.ok("list").splitlines() if "Alpha" in l][0]
        self.assertIn("1 run", alpha_line)
        self.assertNotIn("no runs", alpha_line)
        self.assertIn("(2 of 5 shown - raise --limit for more)", self.ok("list", "--limit", "2"))

    # ------------------------------------------------------------ show and status

    def test_show_by_name_prefix_and_id_in_text_and_json(self):
        self.tree()
        text = self.ok("show", "alpha")
        self.assertTrue(text.startswith("Alpha  %s" % self.alpha.id), text)
        self.assertIn("Inside", text)
        self.assertIn("Docs", text)
        self.assertEqual(self.ok("show", self.alpha.id[:8]), text)
        self.assertEqual(self.ok("show", self.alpha.id[2:8]), text)    # the p_ may be left out
        view = self.json_ok("show", self.alpha.id, "--json")
        self.assertEqual(view["project"]["id"], self.alpha.id)
        self.assertEqual([t["name"] for t in view["inside"]], ["Docs"])
        self.assertIn("Nothing filed here yet.", self.ok("show", "inbox"))

    def test_show_lists_a_filed_session(self):
        self.tree()
        a = self.sessions()[SID_A]
        api.move_item(a.id, self.alpha.id)
        text = self.ok("show", "Alpha")
        self.assertIn("Sessions", text)
        self.assertIn("alpha work", text)
        self.assertIn(a.id[:8], text)

    def test_status_without_a_project_is_the_server_and_with_one_is_the_project(self):
        self.tree()
        self.assertEqual(self.ok("status"), "Project Studio is not running.\n")
        self.assertFalse(self.json_ok("status", "--json")["running"])
        self.assertEqual(self.ok("stop"), "Project Studio is not running.\n")
        text = self.ok("status", "Alpha", "--no-refresh")
        self.assertTrue(text.startswith("Alpha  %s" % self.alpha.id), text)
        self.assertIn("0 runs, 0 active", text)
        status = self.json_ok("--json", "status", "alpha")
        self.assertEqual(status["project"]["id"], self.alpha.id)
        self.assertEqual(status["sub_projects"][0]["project"]["id"], self.docs_a.id)
        self.assertIn("No runs or items here yet.", self.ok("status", "Inbox"))

    def test_status_lists_inbox_sessions(self):
        self.sessions()
        text = self.ok("status", "inbox", "--no-refresh")
        self.assertIn("Sessions", text)
        self.assertIn("alpha work", text)
        self.assertIn("beta work", text)

    # ------------------------------------------------------------ find, inbox, refresh, rules

    def test_find_in_text_and_json(self):
        self.tree()
        by_key = self.sessions()
        api.move_item(by_key[SID_A].id, self.alpha.id)
        lines = self.ok("find", "--no-refresh").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(any(l.startswith(by_key[SID_A].id[:8]) and "Alpha" in l for l in lines), lines)
        found = self.json_ok("find", "ALPHA", "--json", "--no-refresh")
        self.assertEqual([i["id"] for i in found["items"]], [by_key[SID_A].id])
        in_alpha = self.json_ok("find", "--project", "alpha", "--json", "--no-refresh")
        self.assertEqual([i["id"] for i in in_alpha["items"]], [by_key[SID_A].id])
        self.assertEqual(self.ok("find", "nothing-like-this", "--no-refresh"), "No items match.\n")
        self.assertIn("(1 of 2 shown", self.ok("find", "--limit", "1", "--no-refresh"))

    def test_inbox_in_text_and_json(self):
        self.assertEqual(self.ok("inbox", "--no-refresh"), "The Inbox is empty.\n")
        by_key = self.sessions()
        text = self.ok("inbox", "--no-refresh")
        self.assertIn(by_key[SID_A].id[:8], text)
        self.assertIn("beta work", text)
        out = self.json_ok("inbox", "--json", "--no-refresh")
        self.assertEqual(out["total"], 2)
        self.assertEqual(sorted(e["item"]["id"] for e in out["entries"]), sorted(i.id for i in by_key.values()))

    def test_refresh_says_what_changed(self):
        self.agents([agent(SID_A, "alpha work", "/w/proj/alpha")])
        text = self.ok("refresh", "--force")
        self.assertIn("1 added", text)
        self.assertIn("Every source read fine.", text)
        out = self.json_ok("refresh", "--force", "--json")
        self.assertEqual(out["added"], 0)
        self.assertTrue(all(s["ok"] for s in out["sources"]))

    def test_refresh_names_a_failed_source(self):
        self.agents_fail()
        text = self.ok("refresh", "--force")
        self.assertIn("Failed sources", text)
        self.assertIn("agents", text)

    def test_rules_empty_and_one_project(self):
        self.tree()
        self.assertEqual(self.ok("rules"), "No rules yet.\n")
        self.assertEqual(self.json_ok("rules", "--project", "alpha", "--json")["rules"], [])

    # ------------------------------------------------------------ help, errors and exit codes

    def test_help_lists_every_command_and_one_command_help(self):
        text = self.ok("help")
        for name in ("open", "stop", "status", "list", "show", "find", "inbox", "refresh", "rules", "help"):
            self.assertIn(name, text)
        self.assertIn("Exit codes", text)
        self.assertIn("--refresh", self.ok("help", "show"))
        self.assertIn("--refresh", self.ok("show", "--help"))
        self.assertIn("usage: project-studio", self.ok("--help"))

    def test_usage_errors_exit_2(self):
        for argv in (["list", "--limit", "abc"], ["nonsense"], ["show"], ["find", "--kind", "bogus"],
                     ["help", "bogus"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertEqual(out, "")
            self.assertIn("usage:", err)

    def test_an_unknown_project_exits_1_with_a_coded_error(self):
        code, out, err = self.run_cli("show", "nope")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("project-studio: not_found: "), err)
        code, out, err = self.run_cli("show", "nope", "--json")
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(json.loads(out)["error"]["code"], "not_found")
        code, _, err = self.run_cli("find", "--project", "nope")
        self.assertEqual(code, 1)
        self.assertIn("not_found", err)

    def test_an_ambiguous_name_exits_1_and_lists_the_candidates(self):
        self.tree()
        code, out, err = self.run_cli("status", "docs")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("project-studio: ambiguous: "), err)
        for p in (self.docs_a, self.docs_b):
            self.assertIn(p.id, err)
        self.assertIn("(in Alpha)", err)
        code, out, _ = self.run_cli("--json", "show", "docs")
        self.assertEqual(code, 1)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "ambiguous")
        self.assertEqual(sorted(c["id"] for c in error["candidates"]), sorted([self.docs_a.id, self.docs_b.id]))
        self.assertEqual(self.json_ok("show", self.docs_b.id[:8], "--json")["project"]["id"], self.docs_b.id)

    def test_invalid_input_from_the_sdk_exits_1(self):
        code, _, err = self.run_cli("list", "--limit", "0")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("project-studio: invalid_input: "), err)
