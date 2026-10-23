"""The reconcile scan: manual > title > cwd/worktree > rule > Inbox, archived projects get
nothing new, a run's auto-attached items follow it, per-ticket worktrees attach to their sprint."""

import os

from sdk import api

from .support import Sources
from .test_readers import SID_A, SID_B, SID_C, SID_D, agent

SLUG = "studio-20261023"


class Reconcile(Sources):
    def setUp(self):
        super().setUp()
        self.repo, (self.wt, self.ticket_wt, self.loose_wt) = self.git_repo(
            "r", [("r-studio", "feat/s"), ("r-studio-T03", "feat/s--T03"), ("r-loose", "fix/loose")])
        self.ws = self.workspace(SLUG, facts={"REPO_PATH": self.repo, "REPO_SLUG": "me/r", "BRANCH": "feat/s",
                                              "WORKTREE": self.wt, "TOTAL": "4"},
                                 tags=(("T01", "DONE"), ("T02", "DONE"), ("T03", ""), ("T04", None)),
                                 files={"state/T03.cwd": self.ticket_wt + "\n"})
        self.prs("me/r", [{"number": 9, "title": "studio", "headRefName": "feat/s", "state": "OPEN", "isDraft": True,
                           "url": "https://github.com/me/r/pull/9", "updatedAt": "2026-10-23T00:00:00Z"}])

    def items(self):
        api.refresh(force=True)
        return {i.key: i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items}

    def run_item(self):
        return self.items()[self.ws]

    def test_title_rung_files_a_session_named_for_the_run_with_the_run(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/somewhere/else")])
        found = self.items()
        session, run = found[SID_A], found[self.ws]
        self.assertEqual((session.placed_by, session.workspace_item_id), ("title", run.id))
        self.assertEqual(session.project_id, run.project_id)

    def test_cwd_rung_files_a_session_inside_the_run_worktree(self):
        self.agents([agent(SID_B, "free-form name", os.path.join(self.wt, "pkg"))])
        session = self.items()[SID_B]
        self.assertEqual(session.placed_by, "cwd")
        self.assertEqual(session.workspace_item_id, self.items()[self.ws].id)

    def test_title_beats_cwd(self):
        other = self.workspace("other-20261023")
        self.agents([agent(SID_C, "ns-other-20261023-T01", self.wt)])
        found = self.items()
        self.assertEqual((found[SID_C].placed_by, found[SID_C].workspace_item_id), ("title", found[other].id))

    def test_per_ticket_worktree_branch_and_pr_attach_to_their_sprint(self):
        found = self.items()
        run = found[self.ws]
        for key in (self.wt, self.ticket_wt, "me/r#9"):
            self.assertEqual((found[key].workspace_item_id, found[key].placed_by), (run.id, "cwd"), key)
        self.assertEqual(found[self.loose_wt].placed_by, "inbox")             # not the run's
        self.assertIsNone(found[self.loose_wt].workspace_item_id)

    def test_one_item_found_twice_in_a_scan_is_stored_once(self):
        self.workspace("twin-20261023", facts={"REPO_PATH": self.repo + "/"})   # same repo, two cache keys
        result = api.refresh(force=True)
        self.assertGreaterEqual(sum(1 for r in result.reads if r["source"] == "worktrees"), 2)
        rows = api.find_items(query=os.path.basename(self.loose_wt), kind="worktree", refresh=False).items
        self.assertEqual([r.key for r in rows], [self.loose_wt])

    def test_a_session_added_under_its_other_kind_stays_one_item(self):
        self.agents([agent(SID_D, "stray", "/tmp/nowhere-in-particular")])
        filed = self.items()[SID_D]
        self.assertEqual(filed.kind, "session-bg")
        beta = api.create_project("Beta")
        moved = api.add_item("session-interactive", SID_D, beta.id)
        self.assertFalse(moved.created)
        self.assertEqual((moved.item.id, moved.item.project_id), (filed.id, beta.id))
        api.refresh(force=True)
        same = [i for i in api.find_items(include_gone=True, refresh=False, limit=1000).items if i.key == SID_D]
        self.assertEqual([(i.id, i.project_id) for i in same], [(filed.id, beta.id)])

    def test_undo_of_a_wrong_drag_puts_an_auto_attached_item_back_on_its_run(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/x")])
        found = self.items()
        session, run = found[SID_A], found[self.ws]
        beta, gamma = api.create_project("Beta"), api.create_project("Gamma")
        api.move_item(run.id, beta.id)
        back = api.undo_move(api.move_item(session.id, gamma.id).move_id)
        self.assertEqual((back.item.project_id, back.item.placed_by), (beta.id, "title"))
        api.move_item(run.id, gamma.id)
        self.assertEqual(self.items()[SID_A].project_id, gamma.id)

    def test_an_unmatched_item_lands_in_the_inbox(self):
        self.agents([agent(SID_D, "stray", "/tmp/nowhere-in-particular")])
        stray = self.items()[SID_D]
        self.assertEqual((stray.project_id, stray.placed_by), ("inbox", "inbox"))

    def test_moving_a_run_takes_its_auto_attached_items_and_leaves_manual_ones(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/x"), agent(SID_B, "ns-%s-T03" % SLUG, "/x")])
        found = self.items()
        here, there = api.create_project("Here"), api.create_project("There")
        api.move_item(found[SID_B].id, here.id)                        # by hand: it stays put from now on
        moved = api.move_item(found[self.ws].id, there.id)
        self.assertIn(found[SID_A].id, moved.followed)
        self.assertIn(found[self.ticket_wt].id, moved.followed)
        self.assertNotIn(found[SID_B].id, moved.followed)
        after = self.items()                                           # and a later scan agrees
        self.assertEqual(after[SID_A].project_id, there.id)
        self.assertEqual(after["me/r#9"].project_id, there.id)
        self.assertEqual((after[SID_B].project_id, after[SID_B].placed_by), (here.id, "manual"))

    def test_a_run_filed_after_its_children_pulls_them_along_on_the_next_scan(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/x")])
        found = self.items()
        project = api.create_project("Studio")
        api.move_item(found[self.ws].id, project.id)
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, "/x"), agent(SID_C, "ns-%s-T04" % SLUG, "/x")])
        after = self.items()
        self.assertEqual(after[SID_C].project_id, project.id)          # new child joins the run's home
        self.assertEqual(after[SID_A].project_id, project.id)

    def test_manual_placement_wins_over_every_rung(self):
        self.agents([agent(SID_A, "ns-%s-T02" % SLUG, self.wt)])
        found = self.items()
        mine = api.create_project("Mine")
        api.move_item(found[SID_A].id, mine.id)
        api.move_item(found[self.ws].id, api.create_project("Elsewhere").id)
        again = self.items()[SID_A]
        self.assertEqual((again.project_id, again.placed_by), (mine.id, "manual"))

    def test_rule_rung_files_a_new_item_and_an_archived_project_gets_nothing_new(self):
        self.agents([agent(SID_A, "first", "/w/notes/a")])
        first = self.items()[SID_A]
        notes = api.create_project("Notes")
        rule = api.save_rule_from_move(api.move_item(first.id, notes.id).move_id)
        self.assertEqual((rule.signal, rule.pattern), ("cwd", "/w/notes/a"))
        self.agents([agent(SID_A, "first", "/w/notes/a"), agent(SID_B, "second", "/w/notes/a/deeper")])
        second = self.items()[SID_B]
        self.assertEqual((second.project_id, second.placed_by), (notes.id, "rule"))
        api.archive_project(notes.id)
        self.agents([agent(SID_A, "first", "/w/notes/a"), agent(SID_B, "second", "/w/notes/a/deeper"),
                     agent(SID_C, "third", "/w/notes/a/b")])
        third = self.items()[SID_C]
        self.assertEqual((third.project_id, third.placed_by), ("inbox", "inbox"))

    def test_an_archived_run_home_sends_new_children_on_to_the_next_rung(self):
        found = self.items()
        old = api.create_project("Old")
        api.move_item(found[self.ws].id, old.id)
        api.archive_project(old.id)
        self.agents([agent(SID_D, "ns-%s-T04" % SLUG, "/x")])
        child = self.items()[SID_D]
        self.assertEqual(child.project_id, "inbox")
        self.assertEqual(child.workspace_item_id, found[self.ws].id)   # provenance kept

    def test_an_inbox_item_is_filed_once_a_rule_claims_it(self):
        self.agents([agent(SID_A, "a", "/w/inbox-first/a"), agent(SID_C, "c", "/w/inbox-first/a/c")])
        found = self.items()
        self.assertEqual(found[SID_C].placed_by, "inbox")
        target = api.create_project("Target")
        api.save_rule_from_move(api.move_item(found[SID_A].id, target.id).move_id)
        later = self.items()[SID_C]
        self.assertEqual((later.project_id, later.placed_by), (target.id, "rule"))

    def test_a_deleted_workspace_is_gone_but_keeps_its_home(self):
        found = self.items()
        home = api.create_project("Home")
        api.move_item(found[self.ws].id, home.id)
        os.rename(self.ws, self.ws + ".moved-away")
        run = self.items()[self.ws]
        self.assertTrue(run.gone)
        self.assertEqual(run.project_id, home.id)
        self.assertEqual(api.purge_gone(run.id).ids, [run.id])
        self.assertNotIn(self.ws, self.items())
