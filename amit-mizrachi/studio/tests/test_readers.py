"""Readers for every item kind, on fixtures, through `sdk.api.refresh` and `find_items`.

`claude` and `gh` are stubs on PATH (tests/stubs); git is real, on throwaway repos. A failed
read must leave items UNKNOWN with their last-good data, never gone.
"""

import os

from sdk import api, cache, store
from sdk.readers import git, runs, sessions

from . import STUDIO
from .support import Sources

NIGHT_WATCH_ROOTS = os.path.join(STUDIO, "tests", "fixtures", "night-watch", "roots")
SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-8222-222222222222"
SID_C = "33333333-3333-4333-8333-333333333333"
SID_D = "44444444-4444-4444-8444-444444444444"


def agent(sid, name, cwd, state="working"):
    return {"id": sid[:8], "sessionId": sid, "name": name, "cwd": cwd, "state": state, "kind": "background",
            "startedAt": 1792782380000}


class Runs(Sources):
    def by_slug(self):
        read = runs.discover()
        self.assertTrue(read.ok, read.error)
        return {r["slug"]: r for r in read.records}

    def test_night_watch_fixture_runs_read_with_status_progress_and_artifact(self):
        os.environ["PROJECT_STUDIO_ROOTS"] = ":".join(os.path.join(NIGHT_WATCH_ROOTS, r)
                                                      for r in ("claude-research", "night-sprint"))
        found = self.by_slug()
        studio = found["claude-project-studio-20261023"]
        self.assertEqual(studio["kind"], "night-marathon")
        self.assertEqual([s["name"] for s in studio["stages"]], ["Research", "Plan", "Your picks", "Build"])
        self.assertEqual(studio["artifacts"][0]["url"], "https://claude.ai/artifact/L5PR6Uqk3agwJLWyo8abg5")
        self.assertTrue(studio["artifacts"][0]["plan"])
        deel = found["deel-time-away"]
        self.assertEqual((deel["kind"], deel["status"], deel["reason"]), ("night-sprint", "blocked", "CI red"))
        self.assertEqual(deel["progress"]["text"], "T05 of 5")
        self.assertEqual(found["agents-in-shapes-v2"]["status"], "blocked")
        self.assertTrue(found["agents-in-shapes-v2"]["reason"])

    def test_old_format_workspace_is_listed_as_unknown(self):
        ws = self.mkdir("roots", "old-sprint", "state")
        self.write(os.path.join(ws, "T01.status"), "DONE\n")          # no .next files at all
        old = self.by_slug()["old-sprint"]
        self.assertEqual(old["status"], "unknown")
        self.assertIn("old format", old["reason"])

    def test_a_started_sprint_with_no_runner_or_red_ci_needs_you_as_in_night_watch(self):
        self.workspace("stopped-20261023", tags=(("T01", "DONE"), ("T02", ""), ("T03", None)), runner=False)
        self.workspace("red-20261023", tags=(("T01", "DONE"), ("T02", "DONE")),
                       files={"state/ACCEPTANCE.verdict": "FAIL at abc123\n"})
        found = self.by_slug()
        self.assertEqual((found["stopped-20261023"]["status"], found["stopped-20261023"]["reason"]),
                         ("needs-you", "runner stopped"))
        self.assertEqual((found["red-20261023"]["status"], found["red-20261023"]["reason"]), ("blocked", "CI red"))

    def test_a_fail_verdict_the_ci_ticket_passed_at_the_same_head_is_no_ci_not_red(self):
        # accept.sh writes FAIL when `gh pr checks` exits 1 on "no checks reported" (a repo with no CI)
        done = (("T01", "DONE"), ("CI", "DONE"))
        self.workspace("noci-20261023", tags=done, files={
            "state/ACCEPTANCE.verdict": "FAIL 6d6888429b29 required checks failing (PR #24): see gh pr checks\n",
            "state/CI.summary": "PASS at 6d6888429b29 (vacuous: repo has no CI workflows, 0 checks on the PR)\n"})
        self.workspace("other-head-20261023", tags=done, files={
            "state/ACCEPTANCE.verdict": "FAIL 6d6888429b29 required checks failing\n",
            "state/CI.summary": "PASS at 1a2b3c4d5e6f, 0 fixes pushed\n"})
        found = self.by_slug()
        self.assertEqual((found["noci-20261023"]["status"], found["noci-20261023"]["reason"]), ("done", "finished, no PR"))
        self.assertEqual((found["other-head-20261023"]["status"], found["other-head-20261023"]["reason"]),
                         ("blocked", "CI red"))

    def test_running_sprint_has_ticket_progress_and_per_ticket_branches_and_worktrees(self):
        self.workspace("x-20261023", facts={"BRANCH": "feat/x", "WORKTREE": "/w/x", "TOTAL": "5"},
                       tags=(("T01", "DONE"), ("T02", "DONE"), ("T03", ""), ("T04", None)),
                       files={"state/T03.cwd": "/w/x-T03\n", "state/T03.session": SID_A + "\n"})
        rec = self.by_slug()["x-20261023"]
        self.assertEqual((rec["status"], rec["stage"], rec["progress"]["text"]), ("running", "T03", "T03 of 5"))
        self.assertIn("feat/x--T03", rec["branches"])
        self.assertIn("/w/x-T03", rec["worktrees"])
        self.assertIn(SID_A, rec["sessions"])

    def test_a_waiting_marker_means_the_run_needs_you(self):
        self.workspace("y", tags=(("T01", ""),), files={"state/T01.waiting-on-user": "plan gate\n"})
        self.assertEqual(self.by_slug()["y"]["status"], "needs-you")


class Sessions(Sources):
    def test_agents_rows_parse_and_a_failed_call_is_not_an_empty_list(self):
        self.agents([agent(SID_A, "ns-x-T01", "/w")])
        read = sessions.agents()
        self.assertTrue(read.ok)
        self.assertEqual((read.records[0]["short"], read.records[0]["state"]), (SID_A[:8], "working"))
        self.agents_fail()
        read = sessions.agents()
        self.assertFalse(read.ok)
        self.assertTrue(read.error)

    def test_headless_runs_never_show_and_interactive_sessions_do(self):
        self.transcript(SID_A, "/w/a", kind="", entrypoint="sdk-cli")
        self.transcript(SID_B, "/w/b", kind="interactive", entrypoint="cli")
        api.refresh(force=True)
        found = {i.key: i for i in api.find_items(refresh=False).items}
        self.assertNotIn(SID_A, found)
        self.assertEqual(found[SID_B].kind, "session-interactive")
        self.assertEqual(found[SID_B].data["cwd"], "/w/b")

    def test_a_pruned_bg_job_is_resolved_from_its_transcript(self):
        self.transcript(SID_C, "/w/c", kind="bg", title="ns-gone-sprint-T02", branch="feat/c")
        api.refresh(force=True)                               # not in claude agents, no jobs dir
        item = {i.key: i for i in api.find_items(refresh=False).items}[SID_C]
        self.assertEqual(item.kind, "session-bg")
        self.assertEqual((item.title, item.status, item.gone), ("ns-gone-sprint-T02", "removed", False))
        self.assertEqual((item.data["cwd"], item.data["git_branch"], item.data["listed"]), ("/w/c", "feat/c", False))

    def test_a_job_without_agents_row_keeps_its_name_and_cwd(self):
        self.job(SID_D[:8], SID_D, "my job", "/w/d")
        api.refresh(force=True)
        item = {i.key: i for i in api.find_items(refresh=False).items}[SID_D]
        self.assertEqual((item.title, item.data["cwd"], item.data["short"]), ("my job", "/w/d", SID_D[:8]))

    def test_a_failed_claude_agents_read_leaves_bg_sessions_unknown_never_gone(self):
        self.agents([agent(SID_A, "ns-x-T01", "/w/a"), agent(SID_B, "solo", "/w/b")])
        api.refresh(force=True)
        self.assertEqual({i.status for i in api.find_items(kind="session-bg", refresh=False).items}, {"working"})
        self.agents_fail()
        result = api.refresh(force=True)
        self.assertEqual(result.gone, 0)
        found = api.find_items(kind="session-bg", include_gone=True, refresh=False).items
        self.assertEqual(sorted(i.key for i in found), [SID_A, SID_B])
        self.assertEqual({i.status for i in found}, {"unknown"})
        self.assertFalse(any(i.gone for i in found))
        self.assertEqual({i.data["cwd"] for i in found}, {"/w/a", "/w/b"})       # last-good data kept
        failed = [s for s in result.sources if s.source == "agents"][0]
        self.assertFalse(failed.ok)
        self.assertTrue(failed.error)
        self.assertTrue(failed.good_at)

    def test_only_a_complete_read_marks_a_session_gone(self):
        self.agents([agent(SID_A, "solo", "/w/a")])
        api.refresh(force=True)
        self.agents([])                                        # rm'd, and no transcript either
        api.refresh(force=True)
        item = api.find_items(include_gone=True, refresh=False).items[0]
        self.assertTrue(item.gone)
        self.assertEqual(item.project_id, "inbox")             # membership kept


class Git(Sources):
    def test_worktrees_list_the_linked_ones_only(self):
        repo, paths = self.git_repo("r", [("r-wt", "feat/a")])
        read = git.worktrees(repo)
        self.assertTrue(read.ok, read.error)
        self.assertEqual([(w["path"], w["branch"]) for w in read.records], [(paths[0], "feat/a")])

    def gh_calls(self):
        path = os.path.join(self.stub, "calls")
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return [c for c in fh.read().splitlines() if c.startswith("gh ")]

    def test_prs_are_a_light_list_then_the_checks_of_open_prs_only(self):
        self.prs("me/r", [
            {"number": 5, "title": "b", "headRefName": "feat/b", "state": "OPEN", "isDraft": False,
             "url": "https://github.com/me/r/pull/5", "updatedAt": "2026-10-21T00:00:00Z",
             "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"},
                                   {"status": "IN_PROGRESS", "conclusion": ""},
                                   {"status": "COMPLETED", "conclusion": "SUCCESS"}]},
            {"number": 4, "title": "a", "headRefName": "feat/a", "state": "MERGED", "isDraft": False,
             "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z",
             "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}]}])
        read = git.prs("me/r")
        self.assertTrue(read.ok, read.error)
        self.assertFalse(read.partial)
        by_number = {r["number"]: r for r in read.records}
        self.assertEqual((by_number[4]["state"], by_number[4]["branch"]), ("merged", "feat/a"))
        self.assertEqual(by_number[5]["checks"], {"total": 3, "red": 1, "pending": 1})
        self.assertEqual(by_number[4]["checks"], {"total": 0, "red": 0, "pending": 0})   # closed: not asked
        light, checks = self.gh_calls()
        self.assertIn("--repo me/r", light)
        self.assertIn("--state all", light)
        self.assertIn("--limit %d" % git.PR_LIMIT, light)
        self.assertNotIn("statusCheckRollup", light)
        self.assertIn("--state open", checks)
        self.assertIn("--limit 1", checks)                     # only as many as the light list holds open
        self.assertIn("statusCheckRollup", checks)

    def test_a_repo_with_no_open_prs_makes_one_gh_call(self):
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "CLOSED", "isDraft": False,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        read = git.prs("me/r")
        self.assertTrue(read.ok, read.error)
        self.assertEqual(len(self.gh_calls()), 1)

    def test_a_504_is_retried_once(self):
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": False,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z",
                           "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}])
        self.write(os.path.join(self.stub, "gh-504"), "1")
        read = git.prs("me/r")
        self.assertTrue(read.ok, read.error)
        self.assertEqual(read.records[0]["checks"], {"total": 1, "red": 0, "pending": 0})
        self.assertEqual(len(self.gh_calls()), 3)              # light list twice, then the checks

    def test_a_non_5xx_failure_is_not_retried(self):
        self.write(os.path.join(self.stub, "gh-fail"), "1")
        read = git.prs("me/r")
        self.assertFalse(read.ok)
        self.assertEqual(len(self.gh_calls()), 1)

    def test_a_second_504_keeps_the_cached_prs_and_gives_the_banner(self):
        repo, _ = self.git_repo("r", [])
        self.workspace("s", facts={"REPO_PATH": repo, "REPO_SLUG": "me/r", "BRANCH": "feat/a"})
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": True,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        api.refresh(force=True)
        self.write(os.path.join(self.stub, "gh-504"), "2")
        result = api.refresh(force=True)
        state = [s for s in result.sources if s.source == "prs"][0]
        self.assertEqual((state.ok, state.key), (False, "me/r"))
        self.assertIn("504", state.error)
        self.assertEqual(result.gone, 0)
        pr = api.find_items(kind="pr", refresh=False).items[0]
        self.assertEqual((pr.key, pr.data["state"], pr.gone), ("me/r#4", "open", False))
        banners = [b for b in api.home().banners if b.source == "prs"]
        self.assertEqual([b.key for b in banners], ["me/r"])
        self.assertIn("PR states below are from", banners[0].text)

    def test_a_checkout_with_no_github_remote_gets_no_pr_read_and_no_banner(self):
        repo, _ = self.git_repo("r", [])
        for slug in ("local only, no remote", "shapes-machina"):
            self.workspace("s-" + slug.split(",")[0].replace(" ", "-"),
                           facts={"REPO_PATH": repo, "REPO_SLUG": slug, "BRANCH": "feat/a"})
        result = api.refresh(force=True)
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual([s for s in result.sources if s.source == "prs" and not s.ok], [])
        self.assertEqual([b for b in api.home().banners if b.source == "prs"], [])

    def test_a_no_remote_banner_left_from_an_earlier_read_clears_on_the_next_refresh(self):
        repo, _ = self.git_repo("r", [])
        self.workspace("s", facts={"REPO_PATH": repo, "REPO_SLUG": "local only, no remote", "BRANCH": "feat/a"})
        with store.write() as conn:
            cache.put(conn, "prs", "local only, no remote", git.Read(False, [], "gh pr list exited 1: expected "
                                                                      "the \"[HOST/]OWNER/REPO\" format"))
        self.assertEqual(len([b for b in api.home().banners if b.source == "prs"]), 1)
        api.refresh(force=True)
        self.assertEqual([b for b in api.home().banners if b.source == "prs"], [])
        self.assertEqual(self.gh_calls(), [])

    def test_a_failed_gh_read_keeps_last_good_pr_states_and_records_the_error(self):
        repo, _ = self.git_repo("r", [])
        self.workspace("s", facts={"REPO_PATH": repo, "REPO_SLUG": "me/r", "BRANCH": "feat/a"})
        self.prs("me/r", [{"number": 4, "title": "a", "headRefName": "feat/a", "state": "OPEN", "isDraft": True,
                           "url": "https://github.com/me/r/pull/4", "updatedAt": "2026-10-20T00:00:00Z"}])
        api.refresh(force=True)
        self.write(os.path.join(self.stub, "gh-fail"), "1")
        result = api.refresh(force=True)
        self.assertEqual(result.gone, 0)
        pr = api.find_items(kind="pr", refresh=False).items[0]
        self.assertEqual((pr.key, pr.data["state"], pr.gone), ("me/r#4", "open", False))
        state = [s for s in result.sources if s.source == "prs"][0]
        self.assertEqual((state.ok, state.key), (False, "me/r"))
        self.assertIn("error connecting", state.error)

    def test_repo_of_path_names_the_main_checkout_from_a_linked_worktree(self):
        repo, paths = self.git_repo("main-repo", [("main-repo-wt", "feat/a")])
        self.assertEqual(git.repo_of_path(os.path.join(paths[0])), {"repo": "main-repo", "repo_path": repo})
        self.assertEqual(git.repo_of_path(repo)["repo"], "main-repo")
