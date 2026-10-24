"""Rules by pattern: write a filing rule directly (`rule-add Shapes --workspace 'sis-*'`), not only
learn one from a move. Through `sdk.api`, the CLI as a subprocess, the MCP server over
stdin/stdout, and the studio web server's route. Fixture homes only: nothing here reads or writes
~/.project-studio."""

import http.client
import json
import os
import subprocess
import sys

from sdk import api, server
from sdk.errors import InvalidInput, NotFound, Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, validate
from .test_readers import SID_A, SID_B, agent

BIN = os.path.join(PLUGIN, "bin", "project-studio")
SLUGS = ("sis-alpha-20261020", "sis-beta-20261021", "other-20261020")


class Inbox(Sources):
    """Three night runs (sis-alpha, sis-beta, other) and two bg sessions (in /w/proj/alpha and /w/other),
    all in the Inbox; the projects Shapes and Misc."""

    def setUp(self):
        super().setUp()
        for slug in SLUGS:
            self.workspace(slug)
        self.agents([agent(SID_A, "alpha", "/w/proj/alpha"), agent(SID_B, "beta", "/w/other")])
        api.refresh(force=True)
        self.shapes = api.create_project("Shapes")
        self.misc = api.create_project("Misc")

    def night_run(self, slug):
        return next(i for i in api.find_items(kind="night-sprint", refresh=False).items if i.title == slug)

    def homes(self):
        return {slug: self.night_run(slug).project_id for slug in SLUGS}


class WritingARule(Inbox):
    def test_a_dry_run_counts_and_names_the_matching_items_and_saves_nothing(self):
        dry = api.add_rule(self.shapes.id, "workspace", "sis-*", dry_run=True)
        self.assertEqual((dry.dry_run, dry.rule, dry.created, dry.matching), (True, None, False, 2))
        self.assertEqual(sorted(s.title for s in dry.sample), ["sis-alpha-20261020", "sis-beta-20261021"])
        self.assertEqual({s.kind for s in dry.sample}, {"night-sprint"})
        self.assertEqual(dry.preview.description, "workspace sis-*")
        self.assertTrue(dry.message.startswith("Nothing saved. The rule workspace sis-* -> Shapes would file "
                                               "2 Inbox items now: "), dry.message)
        self.assertEqual(api.list_rules().rules, [])
        self.assertEqual(set(self.homes().values()), {"inbox"})

    def test_saving_without_apply_files_nothing_now(self):
        saved = api.add_rule(self.shapes.id, "workspace", "sis-*")
        self.assertTrue(saved.created)
        self.assertEqual((saved.matching, saved.filed), (2, []))
        self.assertIn("It matches 2 Inbox items now", saved.message)
        self.assertEqual([(r.id, r.signal, r.pattern) for r in api.list_rules(self.shapes.id).rules],
                         [(saved.rule.id, "workspace", "sis-*")])
        self.assertEqual(set(self.homes().values()), {"inbox"})

    def test_apply_files_each_match_as_its_own_undoable_move(self):
        applied = api.add_rule(self.shapes.id, "workspace", "sis-*", apply=True)
        self.assertEqual(len(applied.filed), 2)
        self.assertEqual(len({f.move_id for f in applied.filed}), 2)
        self.assertIn("Filed 2 Inbox items there, one move each", applied.message)
        self.assertEqual(self.homes(), {"sis-alpha-20261020": self.shapes.id, "sis-beta-20261021": self.shapes.id,
                                        "other-20261020": "inbox"})
        self.assertEqual({self.night_run(s).placed_by for s in SLUGS[:2]}, {"manual"})
        for filing in applied.filed:
            self.assertEqual(api.undo_move(filing.move_id).to_project_id, "inbox")
        self.assertEqual(set(self.homes().values()), {"inbox"})
        self.assertEqual(len(api.list_rules().rules), 1)        # undoing a filing keeps the rule

    def test_items_already_filed_elsewhere_are_left_alone(self):
        api.move_item(self.night_run("sis-beta-20261021").id, self.misc.id)
        api.remove_item(self.night_run("other-20261020").id)          # put in the Inbox by hand: a rule leaves it
        applied = api.add_rule(self.shapes.id, "workspace", "*-2026*", apply=True)
        self.assertEqual([f.title for f in applied.filed], ["sis-alpha-20261020"])
        self.assertEqual(self.homes(), {"sis-alpha-20261020": self.shapes.id, "sis-beta-20261021": self.misc.id,
                                        "other-20261020": "inbox"})

    def test_writing_the_same_rule_twice_keeps_the_one_there(self):
        first = api.add_rule(self.shapes.id, "workspace", "sis-*")
        again = api.add_rule(self.shapes.id, "workspace", " sis-* ")
        self.assertEqual((again.created, again.rule.id), (False, first.rule.id))
        self.assertTrue(again.message.startswith("Already saved: rule workspace sis-* -> Shapes."))
        self.assertEqual(len(api.list_rules().rules), 1)

    def test_a_folder_rule_files_the_folder_and_what_is_under_it(self):
        dry = api.add_rule(self.misc.id, "cwd", "/w/proj/", dry_run=True)
        self.assertEqual((dry.preview.pattern, dry.preview.description), ("/w/proj", "folder /w/proj"))
        self.assertEqual([s.title for s in dry.sample], ["alpha"])

    def test_deleting_a_rule_leaves_what_it_filed(self):
        applied = api.add_rule(self.shapes.id, "workspace", "sis-*", apply=True)
        api.delete_rule(applied.rule.id)
        self.assertEqual(api.list_rules().rules, [])
        self.assertEqual(self.homes()["sis-alpha-20261020"], self.shapes.id)
        api.refresh(force=True)
        self.assertEqual(self.homes()["sis-beta-20261021"], self.shapes.id)


class RankingAndMatching(Inbox):
    def test_the_strongest_signal_wins_even_against_a_newer_rule(self):
        api.add_rule(self.shapes.id, "workspace", "sis-*")
        folder = api.add_rule(self.misc.id, "cwd", self.roots, dry_run=True)      # newer, but a weaker signal
        self.assertEqual([s.title for s in folder.sample], ["other-20261020"])

    def test_within_a_signal_the_newest_rule_wins(self):
        older = api.add_rule(self.shapes.id, "workspace", "sis-*")
        newer = api.add_rule(self.misc.id, "workspace", "sis-alpha-*")
        self.assertEqual(newer.matching, 1)
        self.assertEqual([r.id for r in api.list_rules().rules], [newer.rule.id, older.rule.id])

    def test_a_refresh_files_by_a_written_rule_like_a_learned_one(self):
        api.add_rule(self.shapes.id, "workspace", "sis-*")
        api.add_rule(self.misc.id, "workspace", "sis-alpha-*")
        api.refresh(force=True)
        self.assertEqual(self.homes(), {"sis-alpha-20261020": self.misc.id, "sis-beta-20261021": self.shapes.id,
                                        "other-20261020": "inbox"})
        self.assertEqual(self.night_run("sis-beta-20261021").placed_by, "rule")

    def test_a_written_rule_and_a_learned_one_are_the_same_rule(self):
        learned = api.save_rule_from_move(api.move_item(self.night_run("other-20261020").id, self.misc.id).move_id)
        self.assertEqual((learned.signal, learned.pattern), ("workspace", "other-*"))
        written = api.add_rule(self.misc.id, "workspace", "other-*")
        self.assertEqual((written.created, written.rule.id), (False, learned.id))


class Patterns(Inbox):
    def pattern(self, signal, text):
        return api.add_rule(self.shapes.id, signal, text, dry_run=True).preview.pattern

    def test_patterns_are_stored_in_the_shape_a_learned_rule_has(self):
        self.assertEqual(self.pattern("repo-branch", "shapes-platform eval/"), "shapes-platform eval/*")
        self.assertEqual(self.pattern("repo-branch", "shapes-platform eval/*"), "shapes-platform eval/*")
        self.assertEqual(self.pattern("repo-branch", "shapes-platform"), "shapes-platform *")
        self.assertEqual(self.pattern("cwd", "~/work/shapes/"), os.path.expanduser("~/work/shapes"))
        self.assertEqual(self.pattern("workspace", "claude-project-studio-2026102?"), "claude-project-studio-2026102?")

    def test_an_empty_or_match_everything_pattern_is_refused(self):
        for signal, text in (("workspace", ""), ("workspace", "  "), ("cwd", ""), ("repo-branch", "")):
            with self.assertRaises(InvalidInput, msg=(signal, text)):
                api.add_rule(self.shapes.id, signal, text)
        for signal, text in (("workspace", "*"), ("workspace", "?*"), ("cwd", "/"), ("cwd", "~")):
            with self.assertRaises(Refused, msg=(signal, text)):
                api.add_rule(self.shapes.id, signal, text)
        self.assertEqual(api.list_rules().rules, [])

    def test_a_malformed_pattern_says_why(self):
        cases = (("workspace", "sis *"), ("repo-branch", "shapes-* eval/"), ("repo-branch", "a b c"),
                 ("cwd", "work/shapes"), ("cwd", "/w/*"), ("title", "sis-*"), ("workspace", "x" * 301),
                 ("workspace", "sis-\n*"), ("workspace", None))
        for signal, text in cases:
            with self.assertRaises(InvalidInput, msg=(signal, text)):
                api.add_rule(self.shapes.id, signal, text)

    def test_the_target_must_be_an_active_project_and_flags_must_be_booleans(self):
        with self.assertRaises(Refused) as caught:
            api.add_rule("inbox", "workspace", "sis-*")
        self.assertEqual(str(caught.exception), "A rule can't file items into the Inbox.")
        api.archive_project(self.misc.id)
        with self.assertRaises(Refused) as caught:
            api.add_rule(self.misc.id, "workspace", "sis-*")
        self.assertEqual(str(caught.exception), "Can't file anything into Misc: it is archived.")
        with self.assertRaises(NotFound):
            api.add_rule("p_000000000000", "workspace", "sis-*")
        with self.assertRaises(InvalidInput):
            api.add_rule(self.shapes.id, "workspace", "sis-*", apply="yes")


class FromTheCli(Inbox):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_a_dry_run_prints_the_count_and_saves_nothing(self):
        code, out, err = self.cli("rule-add", "Shapes", "--workspace", "sis-*", "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("would file 2 Inbox items now", out)
        code, out, _ = self.cli("rule-add", "Shapes", "--workspace", "sis-*", "--dry-run", "--json")
        body = json.loads(out)
        self.assertEqual((code, body["dry_run"], body["matching"], body["rule"]), (0, True, 2, None))
        self.assertEqual(api.list_rules().rules, [])

    def test_apply_prints_one_undo_line_per_filed_item(self):
        code, out, _ = self.cli("rule-add", self.shapes.id[:8], "--workspace", "sis-*", "--apply")
        self.assertEqual(code, 0)
        rule = api.list_rules().rules[0]
        self.assertIn("Rule %s. Delete it: project-studio rule-delete %s" % (rule.id, rule.id), out)
        undo = [line for line in out.splitlines() if line.startswith("Move ")]
        self.assertEqual(len(undo), 2)
        self.assertTrue(all("Undo: project-studio undo " in line for line in undo), undo)

    def test_repo_and_branch_prefix_and_cwd_prefix(self):
        code, out, _ = self.cli("--json", "rule-add", "Misc", "--repo", "shapes-platform", "--branch-prefix", "eval/")
        self.assertEqual((code, json.loads(out)["rule"]["pattern"]), (0, "shapes-platform eval/*"))
        code, out, _ = self.cli("rule-add", "Misc", "--cwd-prefix", "/w/proj", "--json")
        self.assertEqual((code, json.loads(out)["rule"]["description"]), (0, "folder /w/proj"))

    def test_exit_codes(self):
        code, out, _ = self.cli("rule-add", "Shapes", "--workspace", "*", "--json")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (1, "refused"))
        code, _, err = self.cli("rule-add", "Shapes", "--workspace", "*")
        self.assertEqual(code, 1)
        self.assertIn("project-studio: refused: * matches every workspace", err)
        self.assertEqual(self.cli("rule-add", "Shapes")[0], 2)                                     # no signal
        self.assertEqual(self.cli("rule-add", "Shapes", "--workspace", "a", "--repo", "b")[0], 2)  # two signals
        code, _, err = self.cli("rule-add", "Shapes", "--workspace", "a", "--branch-prefix", "eval/")
        self.assertEqual(code, 2)
        self.assertIn("--branch-prefix narrows a repo rule", err)

    def test_help_names_the_command_and_its_options(self):
        code, out, _ = self.cli("help")
        self.assertEqual(code, 0)
        self.assertIn("rule-add", out)
        code, out, _ = self.cli("help", "rule-add")
        for option in ("--workspace", "--repo", "--branch-prefix", "--cwd-prefix", "--apply", "--dry-run"):
            self.assertIn(option, out)


class OverMcp(Inbox):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def test_the_tool_dry_runs_applies_and_refuses_with_schema_valid_output(self):
        tool = next(t for t in mcp_tests.mcp_server.TOOLS if t["name"] == "studio_rule_add")
        out = self.converse(
            self.call(1, "studio_rule_add", {"project_id": self.shapes.id, "signal": "workspace", "pattern": "sis-*",
                                             "dry_run": True}),
            self.call(2, "studio_rule_add", {"project_id": self.shapes.id, "signal": "workspace", "pattern": "sis-*",
                                             "apply": True}),
            self.call(3, "studio_rule_add", {"project_id": self.shapes.id, "signal": "workspace", "pattern": "*"}),
            self.call(4, "studio_rule_add", {"project_id": self.shapes.id, "pattern": "sis-*"}))
        for rid in (1, 2):
            result = out[rid]["result"]
            self.assertNotIn("isError", result, result)
            self.assertEqual(validate(result["structuredContent"], tool["outputSchema"]), [], rid)
        dry, applied = out[1]["result"]["structuredContent"], out[2]["result"]["structuredContent"]
        self.assertEqual((dry["matching"], dry["rule"]), (2, None))
        self.assertEqual((applied["created"], len(applied["filed"])), (True, 2))
        self.assertTrue(out[3]["result"]["isError"])
        self.assertIn("matches every workspace", json.dumps(out[3]["result"]))
        self.assertIn("missing argument(s): signal", json.dumps(out[4]))
        self.assertEqual(self.homes()["sis-alpha-20261020"], self.shapes.id)


class FromThePage(Inbox):
    def setUp(self):
        super().setUp()
        self.addCleanup(api.stop_studio)
        self.port = api.open_studio().port
        self.token = server.read_info()["token"]

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, json.dumps(body).encode(),
                     {"Host": "127.0.0.1:%d" % self.port, "X-Studio-Token": self.token})
        res = conn.getresponse()
        data = json.loads(res.read())
        conn.close()
        return res.status, data

    def test_the_form_checks_first_then_saves(self):
        body = {"project_id": self.shapes.id, "signal": "workspace", "pattern": "sis-*", "dry_run": True}
        status, dry = self.post("/api/rule/add", body)
        self.assertEqual((status, dry["matching"], dry["rule"]), (200, 2, None))
        status, saved = self.post("/api/rule/add", dict(body, dry_run=False, apply=True))
        self.assertEqual((status, saved["created"], len(saved["filed"])), (200, True, 2))
        status, bad = self.post("/api/rule/add", dict(body, pattern="*"))
        self.assertEqual((status, bad["code"]), (400, "refused"))
