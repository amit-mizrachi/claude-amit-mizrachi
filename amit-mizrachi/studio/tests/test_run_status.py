"""Ticket 01 (sprint project-studio-manage3): one status for every night run, the same everywhere.

`runstatus.decide` is the one rule: one fixture per status and the transitions between them (a
merged PR beats a frozen BLOCKED, a merge conflict a person must merge reads Waiting on you, an
open PR with no CI reads In review), the roll-up worst first and the count words. Then a fixture
home where home, the project view, `status`, `list`, `find` and the CLI all say the same word.
Fixture homes only: nothing here reads or writes ~/.project-studio."""

import json
import subprocess
import sys
import unittest

import mcp_server
from sdk import api, runstatus
from sdk.errors import InvalidInput
from sdk.results import Run

from .support import Sources
from .test_cli import BIN

CONFLICT = ("merge conflict with main (8 modify/delete test files from #722); the session classifier refuses "
            "the resolution, a human must merge origin/main (commands in the PR comment)")
SETTLED = {"chain": True, "error": "", "waiting": "", "paused": "", "blocked": [], "acceptance": "",
           "ci_summary": "", "finished": True, "started": True, "runner": False}


def state(**changes):
    return {"run_state": dict(SETTLED, **changes)}


def pr(number, state_word="open", total=0, red=0, pending=0):
    return {"number": number, "state": state_word, "url": "https://github.com/me/r/pull/%d" % number,
            "checks": {"total": total, "red": red, "pending": pending}}


def says(found):
    return found.key, found.word, found.reason


class OneRule(unittest.TestCase):
    """`decide` over a run's `run_state` and its PR: one case per status, then the transitions."""

    def test_running(self):
        data = dict(state(finished=False, runner=True), progress={"text": "T03 of 5", "total": 5})
        self.assertEqual(says(runstatus.decide(data)), ("running", "Running", "T03 of 5"))

    def test_waiting_on_you(self):
        self.assertEqual(says(runstatus.decide(state(waiting="plan gate"))), ("needs-you", "Waiting on you", "plan gate"))
        self.assertEqual(runstatus.decide(state(finished=False, paused="auth expired")).reason, "login needed")
        stopped = runstatus.decide(state(finished=False, runner=False))
        self.assertEqual((stopped.key, stopped.reason), ("needs-you", "runner stopped"))

    def test_a_merge_conflict_a_person_must_merge_waits_on_you(self):
        data = state(blocked=[{"stage": "CI", "detail": CONFLICT}], acceptance="FAIL aa6fe82 required checks failing")
        found = runstatus.decide(data, pr(733, total=4))
        self.assertEqual(says(found), ("needs-you", "Waiting on you", "merge conflict with main: merge origin/main"))

    def test_blocked(self):
        data = dict(state(blocked=[{"stage": "T11", "detail": "tests red"}]), progress={"total": 13})
        self.assertEqual(says(runstatus.decide(data)), ("blocked", "Blocked", "T11 of 13 blocked: tests red"))
        red = runstatus.decide(state(), pr(12, total=3, red=2))
        self.assertEqual((red.key, red.reason), ("blocked", "PR #12 open, 2 checks red"))
        files = runstatus.decide(state(acceptance="FAIL abc1234 required checks failing"), pr(12))
        self.assertEqual((files.key, files.reason), ("blocked", "PR #12 open, CI red"))

    def test_a_failure_that_only_names_a_person_or_a_login_is_blocked(self):
        for detail in ("T07 person-sync tests red", "login form tests still red", "manual QA step script crashed"):
            found = runstatus.decide(state(blocked=[{"stage": "T07", "detail": detail}]))
            self.assertEqual(found.key, "blocked", detail)
        for detail in ("a person must rotate the key", "login required", "needs a login", "manual step: approve"):
            found = runstatus.decide(state(blocked=[{"stage": "T07", "detail": detail}]))
            self.assertEqual(found.key, "needs-you", detail)

    def test_paused(self):
        found = runstatus.decide(state(finished=False, runner=True, paused="budget 5h retry-at 04:10"))
        self.assertEqual(says(found), ("paused", "Paused", "waiting for capacity"))

    def test_in_review(self):
        self.assertEqual(says(runstatus.decide(state(), pr(733, total=4))),
                         ("in-review", "In review", "PR #733 open, checks green"))
        self.assertEqual(runstatus.decide(state(), pr(24)).reason, "PR #24 open, no CI")
        no_checks = state(acceptance="FAIL abc1234 no checks reported", ci_summary="no CI")
        self.assertEqual(runstatus.decide(no_checks, pr(24)).key, "in-review")
        self.assertEqual(runstatus.decide(state(), pr(5, total=2, pending=1)).reason, "PR #5 open, checks running")

    def test_merged_beats_a_frozen_blocked(self):
        data = dict(state(blocked=[{"stage": "T11", "detail": "PR 733 is not merged into main"}]),
                    progress={"total": 13})
        self.assertEqual(runstatus.decide(data).key, "blocked")
        self.assertEqual(says(runstatus.decide(data, pr(738, "merged"))), ("merged", "Merged", "PR #738 merged"))

    def test_done(self):
        self.assertEqual(says(runstatus.decide(state())), ("done", "Done", "finished, no PR"))
        self.assertEqual(runstatus.decide(dict(state(), mode="research")).reason, "research finished")
        self.assertEqual(runstatus.decide(state(), pr(9, "closed")).reason, "PR #9 closed")
        marked = runstatus.decide(state(blocked=[{"stage": "T02", "detail": "tests red"}]), None, marked=True)
        self.assertEqual(says(marked), ("done", "Done", "marked done by you"))

    def test_unknown_unless_a_pr_says_more(self):
        self.assertEqual(runstatus.decide(state(chain=False)).key, "unknown")
        self.assertEqual(runstatus.decide(state(chain=False), pr(7, "merged")).key, "merged")

    def test_a_record_read_before_run_state_still_reads(self):
        self.assertEqual(runstatus.decide({"status": "blocked", "reason": CONFLICT}).key, "needs-you")
        self.assertEqual(runstatus.decide({"status": "done", "reason": ""}, pr(3)).key, "in-review")

    def test_parse_takes_keys_and_words(self):
        self.assertEqual([runstatus.parse(w) for w in ("in-review", "In review", "waiting-on-you", "nope")],
                         ["in-review", "in-review", "needs-you", None])


def run(status, gone=False):
    return Run(item_id="i_x", kind="night-sprint", title="x", project_id="p_x", status=status, reason="",
               progress=None, stage="", stages=[], pr=None, artifact_url="", started_at="", updated_at="", gone=gone)


class RollUp(unittest.TestCase):
    def test_worst_first_and_the_same_count_words(self):
        runs = [run("merged"), run("in-review"), run("needs-you"), run("done", gone=True)]
        self.assertEqual(runstatus.roll_up(runs), "needs-you")
        self.assertEqual(runstatus.counts_text(runs), "1 waiting on you, 1 in review, 1 merged, 1 gone")
        self.assertEqual(runstatus.roll_up([run("merged"), run("blocked"), run("running")]), "blocked")
        self.assertEqual(runstatus.roll_up([run("done"), run("merged")]), "merged")
        self.assertEqual(runstatus.roll_up([]), runstatus.NO_RUNS)
        self.assertEqual(runstatus.roll_up_words(runstatus.NO_RUNS), ("\u00b7", ""))


class Everywhere(Sources):
    """Machina decision units as on the real store: one run merged (its T11 froze on BLOCKED), one
    blocked only on a merge conflict a person must merge (its PR green), and Project Studio's run
    with PR #24 open and no CI."""

    def setUp(self):
        super().setUp()
        self.merged = self.workspace("toolkits-20261022", runner=False,
                                     facts={"REPO_SLUG": "me/r", "BRANCH": "feat/tk", "TOTAL": "2"},
                                     tags=(("T01", "DONE"), ("T02", "BLOCKED: PR 733 is not merged into main")))
        self.conflict = self.workspace("units-20261023", runner=False,
                                       facts={"REPO_SLUG": "me/r", "BRANCH": "feat/du"},
                                       tags=(("T01", "DONE"), ("CI", "BLOCKED: " + CONFLICT)))
        self.review = self.workspace("studio-20261024", runner=False,
                                     facts={"REPO_SLUG": "me/s", "BRANCH": "feat/ps"},
                                     tags=(("T01", "DONE"), ("T02", "DONE")))
        green = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
        self.prs("me/r", [self.pr_row(738, "feat/tk", "MERGED"), self.pr_row(733, "feat/du", "OPEN", green)])
        self.prs("me/s", [self.pr_row(24, "feat/ps", "OPEN", [])])
        api.refresh(force=True)
        found = {i.key: i for i in api.find_items(refresh=False, limit=100).items}
        self.units = api.create_project("Machina decision units")
        for ws in (self.merged, self.conflict, self.review):
            api.move_item(found[ws].id, self.units.id)
        self.ids = {ws: found[ws].id for ws in (self.merged, self.conflict, self.review)}

    @staticmethod
    def pr_row(number, branch, state_word, checks=None):
        row = {"number": number, "title": branch, "headRefName": branch, "state": state_word, "isDraft": False,
               "url": "https://github.com/me/r/pull/%d" % number, "updatedAt": "2026-10-23T00:00:00Z"}
        if checks is not None:
            row["statusCheckRollup"] = checks
        return row

    def expected(self):
        return {self.ids[self.merged]: ("merged", "Merged", "PR #738 merged"),
                self.ids[self.conflict]: ("needs-you", "Waiting on you", "merge conflict with main: merge origin/main"),
                self.ids[self.review]: ("in-review", "In review", "PR #24 open, no CI")}

    def test_home_view_and_status_say_the_same(self):
        want = self.expected()
        status = {r.item_id: (r.status, r.word, r.reason) for r in api.project_status(self.units.id, refresh=False).runs}
        self.assertEqual(status, want)
        [card] = [c for c in api.home().cards if c.project.id == self.units.id]
        self.assertEqual({r.item_id: (r.status, r.word, r.reason) for r in card.runs}, want)
        self.assertEqual((card.status, card.word), ("needs-you", "Waiting on you"))
        self.assertEqual(card.counts, "1 waiting on you, 1 in review, 1 merged")
        view = api.project_view(self.units.id)
        self.assertEqual({r.item_id: (r.status, r.word, r.detail) for r in view.runs}, want)
        actions = api.run_actions(self.ids[self.conflict])
        self.assertEqual((actions.status, actions.word), ("needs-you", "Waiting on you"))

    def test_list_and_find_use_the_same_status(self):
        lines = api.list_projects(with_runs=True).run_lines
        self.assertEqual(lines[self.units.id], "1 waiting on you, 1 in review, 1 merged")
        found = api.find_items(status="in-review", refresh=False).items
        self.assertEqual([i.id for i in found], [self.ids[self.review]])
        self.assertEqual([i.id for i in api.find_items(status="Waiting on you", refresh=False).items],
                         [self.ids[self.conflict]])
        with self.assertRaises(InvalidInput):
            api.find_items(status="stuck", refresh=False)

    def test_the_mcp_find_takes_status(self):
        for status in ("in-review", "In review"):
            out = mcp_server.call_tool("studio_find", {"status": status})
            self.assertNotIn("isError", out, out["content"])
            self.assertEqual([i["id"] for i in out["structuredContent"]["items"]], [self.ids[self.review]])
        self.assertTrue(mcp_server.call_tool("studio_find", {"status": "stuck"})["isError"])

    def test_a_mark_done_on_a_merged_run_changes_nothing(self):
        result = api.mark_done(self.ids[self.merged])
        self.assertIsNone(result.move_id)
        self.assertIn("already merged", result.message)

    def test_the_cli_says_it_too(self):
        out = subprocess.run([sys.executable, BIN, "status", self.units.id, "--no-refresh"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Waiting on you", out.stdout)
        self.assertIn("merge conflict with main: merge origin/main", out.stdout)
        self.assertIn("PR #24 open, no CI", out.stdout)
        found = subprocess.run([sys.executable, BIN, "--json", "find", "--status", "merged", "--no-refresh"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual([i["id"] for i in json.loads(found.stdout)["items"]], [self.ids[self.merged]])
