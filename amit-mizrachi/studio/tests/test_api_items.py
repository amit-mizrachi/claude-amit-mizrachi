"""Items through the public SDK: moves with revisions, Undo, remove, add, the Inbox, rules, purge."""

from sdk import api
from sdk.errors import InvalidInput, NotFound, Refused

from .support import Sources
from .test_readers import SID_A, SID_B, SID_C, agent


class Items(Sources):
    def setUp(self):
        super().setUp()
        self.agents([agent(SID_A, "alpha", "/w/proj/alpha"), agent(SID_B, "beta", "/w/proj/beta")])
        api.refresh(force=True)
        self.by_key = {i.key: i for i in api.find_items(refresh=False).items}
        self.one, self.two = api.create_project("One"), api.create_project("Two")

    def test_find_matches_title_and_kind(self):
        found = api.find_items(query="ALPHA", refresh=False)
        self.assertEqual([i.key for i in found.items], [SID_A])
        self.assertEqual(api.find_items(kind="pr", refresh=False).total, 0)
        with self.assertRaises(InvalidInput):
            api.find_items(kind="nonsense", refresh=False)

    def test_a_move_records_a_revision_and_a_stale_one_is_refused(self):
        item = self.by_key[SID_A]
        moved = api.move_item(item.id, self.one.id, expected_revision=item.revision)
        self.assertEqual((moved.item.project_id, moved.item.placed_by), (self.one.id, "manual"))
        self.assertEqual(moved.item.revision, item.revision + 1)
        self.assertIsNotNone(moved.move_id)
        with self.assertRaises(Refused) as ctx:
            api.move_item(item.id, self.two.id, expected_revision=item.revision)
        self.assertIn("changed since you looked", str(ctx.exception))

    def test_undo_puts_it_back_and_is_refused_after_a_newer_move(self):
        item = self.by_key[SID_A]
        first = api.move_item(item.id, self.one.id)
        undone = api.undo_move(first.move_id)
        self.assertEqual(undone.item.project_id, "inbox")
        second = api.move_item(item.id, self.one.id)
        api.move_item(item.id, self.two.id)                      # something moved it since
        with self.assertRaises(Refused) as ctx:
            api.undo_move(second.move_id)
        self.assertEqual(str(ctx.exception), "Can't undo: alpha was moved again since.")
        self.assertEqual(api.find_items(query="alpha", refresh=False).items[0].project_id, self.two.id)

    def test_remove_sends_it_back_to_the_inbox_and_keeps_it_there(self):
        item = self.by_key[SID_A]
        api.move_item(item.id, self.one.id)
        removed = api.remove_item(item.id)
        self.assertEqual((removed.item.project_id, removed.item.placed_by), ("inbox", "manual"))
        api.refresh(force=True)
        self.assertEqual(api.find_items(query="alpha", refresh=False).items[0].project_id, "inbox")

    def test_a_rule_saved_from_a_move_files_the_next_matching_item(self):
        moved = api.move_item(self.by_key[SID_A].id, self.one.id)
        self.assertEqual(moved.rule_preview.description, "folder /w/proj/alpha")
        rule = api.save_rule_from_move(moved.move_id)
        self.assertTrue(rule.created)
        self.assertEqual((rule.project_id, rule.signal, rule.pattern), (self.one.id, "cwd", "/w/proj/alpha"))
        self.assertFalse(api.save_rule_from_move(moved.move_id).created)          # same rule, not twice
        self.agents([agent(SID_A, "alpha", "/w/proj/alpha"), agent(SID_B, "beta", "/w/proj/beta"),
                     agent(SID_C, "alpha again", "/w/proj/alpha/sub")])
        api.refresh(force=True)
        new = api.find_items(query="alpha again", refresh=False).items[0]
        self.assertEqual((new.project_id, new.placed_by), (self.one.id, "rule"))
        self.assertEqual([r.id for r in api.list_rules(self.one.id).rules], [rule.id])
        api.delete_rule(rule.id)
        self.assertEqual(api.list_rules().total, 0)

    def test_inbox_suggests_with_a_reason_and_accept_files_it(self):
        moved = api.move_item(self.by_key[SID_A].id, self.one.id)
        api.save_rule_from_move(moved.move_id)
        api.remove_item(self.by_key[SID_A].id)                    # by hand into the Inbox: a rule matches it
        entries = {e.item.key: e for e in api.inbox(refresh=False).entries}
        self.assertEqual(entries[SID_A].suggestion.project_id, self.one.id)
        self.assertEqual(entries[SID_A].suggestion.reason, "rule: folder /w/proj/alpha")
        self.assertIsNone(entries[SID_B].suggestion)
        accepted = api.accept_suggestion(self.by_key[SID_A].id)
        self.assertEqual(accepted.item.project_id, self.one.id)
        with self.assertRaises(Refused):
            api.accept_suggestion(self.by_key[SID_B].id)

    def test_add_files_an_ad_hoc_folder_by_hand(self):
        folder = self.mkdir("ad-hoc")
        added = api.add_item("night-sprint", folder, self.one.id)
        self.assertTrue(added.created)
        self.assertEqual((added.item.placed_by, added.item.status), ("manual", "unknown"))
        api.refresh(force=True)                                   # not under a root: listed as unknown, never gone
        again = api.find_items(kind="night-sprint", refresh=False).items[0]
        self.assertEqual((again.key, again.project_id, again.status, again.gone), (folder, self.one.id, "unknown", False))
        with self.assertRaises(InvalidInput):
            api.add_item("pr", "not a pr", self.one.id)

    def test_move_dispatches_projects_and_items_and_refuses_cycles_and_archived(self):
        inner = api.create_project("Inner", parent_id=self.one.id)
        with self.assertRaises(Refused):
            api.move(self.one.id, inner.id)
        moved = api.move(inner.id, None)
        self.assertEqual((moved.project.parent_id, moved.item), (None, None))
        api.archive_project(self.two.id)
        with self.assertRaises(Refused):
            api.move(self.by_key[SID_A].id, self.two.id)
        with self.assertRaises(NotFound):
            api.move("i_000000000000", self.one.id)

    def test_project_status_rolls_up_sub_projects(self):
        inner = api.create_project("Inner", parent_id=self.one.id)
        api.move_item(self.by_key[SID_A].id, inner.id)
        status = api.project_status(self.one.id, refresh=False)
        self.assertEqual([s.key for s in status.sessions], [SID_A])
        self.assertEqual([s.project.id for s in status.sub_projects], [inner.id])
        self.assertEqual(status.runs, [])
        self.assertTrue(any(s.source == "agents" for s in status.sources))

    def test_purge_takes_only_gone_items(self):
        with self.assertRaises(Refused):
            api.purge_gone(self.by_key[SID_A].id)
        self.agents([agent(SID_B, "beta", "/w/proj/beta")])
        api.refresh(force=True)
        self.assertEqual(api.purge_gone().ids, [self.by_key[SID_A].id])
        self.assertEqual(api.find_items(include_gone=True, refresh=False).total, 1)
