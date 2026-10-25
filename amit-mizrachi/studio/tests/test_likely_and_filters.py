"""Finding a project's PRs that no rule filed: `find` by repo, monday id and PR state, one item by
id (`item`), a project's likely but unfiled items (`likely`), and a `monday` filing rule. Through
`sdk.api`, the CLI as a subprocess and the MCP server over stdin/stdout. Fixture homes only:
nothing here reads or writes ~/.project-studio."""

import json
import os
import subprocess
import sys

from sdk import api, rules
from sdk.errors import InvalidInput, NotFound, Refused

from . import PLUGIN
from . import test_mcp_server as mcp_tests
from .support import Sources, validate

BIN = os.path.join(PLUGIN, "bin", "project-studio")
EPIC, OTHER = "13216938828", "13344527839"
SLUG = "sis-alpha-20261020"


def pr(number, branch, title, state="OPEN", draft=False):
    return {"number": number, "title": title, "headRefName": branch, "state": state, "isDraft": draft,
            "url": "https://github.com/me/r/pull/%d" % number, "updatedAt": "2026-10-2%dT00:00:00Z" % (number % 10)}


class SisPrs(Sources):
    """A night run on feat/sis-a-<EPIC> in the project Shapes, with its PR #7, and in the Inbox: #8 on
    another branch of the same monday id, the draft #9 of another id, and the merged #10 with none."""

    def setUp(self):
        super().setUp()
        self.workspace(SLUG, facts={"REPO_SLUG": "me/r", "BRANCH": "feat/sis-a-%s" % EPIC})
        self.prs("me/r", [pr(7, "feat/sis-a-%s" % EPIC, "run's PR [%s]" % EPIC),
                          pr(8, "feat/login-alert-%s" % EPIC, "login alert"),
                          pr(9, "feat/wiring-%s" % OTHER, "wiring [%s]" % OTHER, draft=True),
                          pr(10, "fix/unrelated", "unrelated", state="MERGED")])
        api.refresh(force=True)
        self.shapes = api.create_project("Shapes")
        run = next(i for i in api.find_items(kind="night-sprint", refresh=False).items if i.title == SLUG)
        api.move_item(run.id, self.shapes.id)
        self.by_number = {i.data["number"]: i for i in api.find_items(kind="pr", refresh=False).items}

    def numbers(self, **kw):
        return sorted(i.data["number"] for i in api.find_items(kind="pr", refresh=False, **kw).items)


class MondayRules(SisPrs):
    def test_a_monday_rule_is_one_id_and_ranks_after_workspace(self):
        self.assertEqual(rules.check("monday", " %s " % EPIC), ("monday", EPIC))
        for bad in ("abc", "1234", "13216938828 x", "1321693882*"):
            with self.assertRaises(InvalidInput, msg=bad):
                rules.check("monday", bad)
        self.assertEqual(rules.describe("monday", EPIC), "monday " + EPIC)
        self.assertEqual(rules.SIGNALS, ("workspace", "monday", "repo-branch", "cwd"))

    def test_it_matches_the_id_in_a_branch_or_in_the_title_the_reader_saw(self):
        self.assertTrue(rules.matches("monday", EPIC, {"branch": "feat/x-%s--T02" % EPIC}))
        self.assertTrue(rules.matches("monday", OTHER, {"branch": "feat/y", "monday": [OTHER]}))
        self.assertFalse(rules.matches("monday", EPIC, {"branch": "feat/x-%s1" % EPIC}))     # a longer number
        self.assertFalse(rules.matches("monday", EPIC, {"branch": "feat/20261023"}))
        self.assertEqual(self.by_number[9].data["signals"]["monday"], [OTHER])

    def test_a_dry_run_names_the_inbox_pr_and_apply_files_it_undoably(self):
        dry = api.add_rule(self.shapes.id, "monday", EPIC, dry_run=True)
        self.assertEqual(([s.title for s in dry.sample if s.kind == "pr"], dry.rule), (["r#8 login alert"], None))
        done = api.add_rule(self.shapes.id, "monday", EPIC, apply=True)
        self.assertEqual(api.get_item(self.by_number[8].id).project_id, self.shapes.id)
        self.assertEqual(api.get_item(self.by_number[9].id).project_id, "inbox")
        api.undo_move(next(f.move_id for f in done.filed if f.item_id == self.by_number[8].id))
        self.assertEqual(api.get_item(self.by_number[8].id).project_id, "inbox")

    def test_a_refresh_files_a_new_pr_whose_title_alone_holds_the_id(self):
        api.add_rule(self.shapes.id, "monday", EPIC)
        self.prs("me/r", [pr(11, "feat/y", "later work [%s]" % EPIC)])
        api.refresh(force=True)
        late = next(i for i in api.find_items(kind="pr", refresh=False).items if i.data["number"] == 11)
        self.assertEqual((late.project_id, late.placed_by), (self.shapes.id, "rule"))


class Filters(SisPrs):
    def test_a_prs_status_is_its_state(self):
        self.assertEqual({n: i.status for n, i in self.by_number.items()},
                         {7: "open", 8: "open", 9: "draft", 10: "merged"})

    def test_by_monday_id_repo_and_pr_state(self):
        self.assertEqual(self.numbers(monday=EPIC), [7, 8])
        self.assertEqual(self.numbers(repo="me/r"), [7, 8, 9, 10])
        self.assertEqual(self.numbers(repo="R"), [7, 8, 9, 10])
        self.assertEqual(self.numbers(repo="other"), [])
        self.assertEqual(self.numbers(pr_state="open"), [7, 8, 9])         # drafts are open too
        self.assertEqual(self.numbers(pr_state="draft"), [9])
        self.assertEqual(self.numbers(pr_state="merged", project_id="inbox"), [10])
        self.assertEqual(api.find_items(pr_state="open", refresh=False).total, 3)     # PRs only

    def test_bad_filters_say_why(self):
        for kw in ({"pr_state": "ready"}, {"monday": "abc"}, {"monday": ""}, {"repo": " "}, {"repo": 3}):
            with self.assertRaises(InvalidInput, msg=kw):
                api.find_items(refresh=False, **kw)

    def test_one_item_by_id_or_prefix(self):
        item = api.get_item(self.by_number[9].id[:6])
        self.assertEqual((item.id, item.status, item.data["branch"]), (self.by_number[9].id, "draft",
                                                                      "feat/wiring-%s" % OTHER))
        with self.assertRaises(NotFound):
            api.get_item("i_ffffffffffff")


class Likely(SisPrs):
    def test_the_inbox_pr_sharing_the_projects_monday_id(self):
        found = api.likely_items(self.shapes.id, kind="pr", refresh=False)
        self.assertEqual(([e.item.id for e in found.entries], found.total), ([self.by_number[8].id], 1))
        entry = found.entries[0]
        self.assertEqual(entry.monday_ids, [EPIC])
        self.assertRegex(entry.reason, r"^monday %s, like \d+ items? here$" % EPIC)
        self.assertEqual(list(found.monday_ids), [EPIC])
        self.assertGreaterEqual(found.monday_ids[EPIC], 2)                      # the run and its PR
        self.assertEqual(found.project_name, "Shapes")

    def test_filed_dismissed_and_other_ids_are_left_out_and_nothing_moves(self):
        api.dismiss_item(self.by_number[8].id)
        self.assertEqual(api.likely_items(self.shapes.id, kind="pr", refresh=False).entries, [])
        self.assertEqual(api.get_item(self.by_number[8].id).project_id, "inbox")

    def test_the_inbox_and_a_bad_kind_are_refused(self):
        with self.assertRaises(Refused):
            api.likely_items("inbox", refresh=False)
        with self.assertRaises(InvalidInput):
            api.likely_items(self.shapes.id, kind="prs", refresh=False)


class TheProjectView(SisPrs):
    def test_open_prs_no_run_shows_are_listed_under_the_runs(self):
        self.assertEqual(api.project_view(self.shapes.id).open_prs, [])        # #7 is its run's: the run line shows it
        for number in (8, 9, 10):
            api.move_item(self.by_number[number].id, self.shapes.id)
        rows = api.project_view(self.shapes.id).open_prs
        self.assertEqual(sorted(r.item_id for r in rows), sorted([self.by_number[8].id, self.by_number[9].id]))
        self.assertEqual({r.text.split(" ")[0] for r in rows}, {"open", "draft"})   # merged #10 stays in the fold
        fold = next(f for f in api.project_view(self.shapes.id).folds if f.kind == "prs")
        self.assertEqual(fold.count, 4)


class FromTheCli(SisPrs):
    def cli(self, *argv):
        done = subprocess.run([sys.executable, BIN] + list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def test_find_with_the_new_filters(self):
        code, out, err = self.cli("--json", "find", "--monday", EPIC, "--pr-state", "open", "--repo", "r",
                                  "--no-refresh")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(sorted(i["data"]["number"] for i in json.loads(out)["items"]), [7, 8])
        code, out, _ = self.cli("find", "--pr-state", "draft", "--no-refresh")
        self.assertEqual(code, 0)
        self.assertIn("pr  draft", out)
        self.assertEqual(self.cli("find", "--pr-state", "ready")[0], 2)

    def test_item_prints_its_fields(self):
        code, out, _ = self.cli("item", self.by_number[8].id[:8])
        self.assertEqual(code, 0)
        for want in ("kind       pr", "status     open", "project    Inbox", "branch     feat/login-alert-" + EPIC,
                     "url        https://github.com/me/r/pull/8"):
            self.assertIn(want, out)

    def test_likely_names_the_item_and_the_commands_that_file_it(self):
        code, out, _ = self.cli("likely", "Shapes", "--kind", "pr", "--no-refresh")
        self.assertEqual(code, 0)
        self.assertIn(self.by_number[8].id[:8], out)
        self.assertIn("File one: project-studio file <item> Shapes", out)
        self.assertIn("project-studio rule-add Shapes --monday %s --dry-run" % EPIC, out)
        code, out, _ = self.cli("--json", "likely", "inbox")
        self.assertEqual((code, json.loads(out)["error"]["code"]), (1, "refused"))

    def test_rule_add_by_monday_id(self):
        code, out, _ = self.cli("--json", "rule-add", "Shapes", "--monday", EPIC)
        self.assertEqual((code, json.loads(out)["rule"]["description"]), (0, "monday " + EPIC))
        self.assertEqual(self.cli("rule-add", "Shapes", "--monday", EPIC, "--repo", "r")[0], 2)  # two signals


class OverMcp(SisPrs):
    converse = mcp_tests.McpServer.converse
    call = staticmethod(mcp_tests.McpServer.call)

    def tool(self, name):
        return next(t for t in mcp_tests.mcp_server.TOOLS if t["name"] == name)

    def test_likely_item_find_and_rule_add_with_schema_valid_output(self):
        out = self.converse(
            self.call(1, "studio_likely", {"project_id": self.shapes.id, "kind": "pr"}),
            self.call(2, "studio_item", {"item_id": self.by_number[9].id}),
            self.call(3, "studio_find", {"monday": EPIC, "pr_state": "open", "repo": "me/r"}),
            self.call(4, "studio_rule_add", {"project_id": self.shapes.id, "signal": "monday", "pattern": EPIC,
                                             "dry_run": True}),
            self.call(5, "studio_likely", {"project_id": "inbox"}))
        for rid, name in ((1, "studio_likely"), (2, "studio_item"), (3, "studio_find"), (4, "studio_rule_add")):
            result = out[rid]["result"]
            self.assertNotIn("isError", result, result)
            self.assertEqual(validate(result["structuredContent"], self.tool(name)["outputSchema"]), [], rid)
        self.assertEqual([e["item"]["id"] for e in out[1]["result"]["structuredContent"]["entries"]],
                         [self.by_number[8].id])
        self.assertEqual(out[2]["result"]["structuredContent"]["status"], "draft")
        self.assertEqual(sorted(i["data"]["number"] for i in out[3]["result"]["structuredContent"]["items"]), [7, 8])
        self.assertEqual(out[4]["result"]["structuredContent"]["matching"], 1)
        self.assertTrue(out[5]["result"]["isError"])
