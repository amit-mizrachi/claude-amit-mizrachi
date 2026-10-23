"""The public SDK API for the project tree: create, list, get, move, link, archive, delete, export."""

import json
import os

from sdk import api
from sdk.errors import InvalidInput, NotFound, Refused

from .support import TempHome


class CreateAndList(TempHome):
    def test_a_fresh_store_lists_only_the_inbox(self):
        listed = api.list_projects()
        self.assertEqual([p.id for p in listed.projects], ["inbox"])
        self.assertTrue(listed.projects[0].is_inbox)
        self.assertEqual((listed.total, listed.truncated), (1, False))

    def test_create_returns_the_project_with_its_path(self):
        alpha = api.create_project("  Alpha  ")
        beta = api.create_project("Beta", alpha.id)
        self.assertEqual(alpha.name, "Alpha")
        self.assertRegex(alpha.id, r"^p_[0-9a-f]{12}$")
        self.assertEqual(beta.parent_id, alpha.id)
        self.assertEqual(beta.path, ["Alpha", "Beta"])
        self.assertEqual(api.get_project(alpha.id).child_count, 1)

    def test_list_puts_the_inbox_first_then_orders_by_path(self):
        zed = api.create_project("zed")
        api.create_project("Alpha")
        api.create_project("child", zed.id)
        self.assertEqual([p.path for p in api.list_projects().projects],
                         [["Inbox"], ["Alpha"], ["zed"], ["zed", "child"]])

    def test_list_filters_by_parent_and_top_level(self):
        alpha = api.create_project("Alpha")
        api.create_project("Beta", alpha.id)
        self.assertEqual([p.name for p in api.list_projects(parent_id=alpha.id).projects], ["Beta"])
        self.assertEqual([p.name for p in api.list_projects(top_level=True).projects], ["Inbox", "Alpha"])

    def test_list_is_bounded_and_says_so(self):
        for name in ("a", "b", "c"):
            api.create_project(name)
        page = api.list_projects(limit=2)
        self.assertEqual((len(page.projects), page.total, page.truncated), (2, 4, True))
        with self.assertRaises(InvalidInput):
            api.list_projects(limit=0)

    def test_bad_names_are_refused(self):
        for bad in ("", "   ", "x" * 121, "tab\there", 7):
            with self.assertRaises(InvalidInput, msg=repr(bad)):
                api.create_project(bad)

    def test_a_sibling_name_is_unique_ignoring_case(self):
        api.create_project("Alpha")
        with self.assertRaises(Refused):
            api.create_project("alpha")

    def test_the_inbox_holds_no_sub_projects(self):
        with self.assertRaises(Refused):
            api.create_project("x", "inbox")

    def test_an_unknown_or_malformed_id_is_not_found(self):
        for bad in ("p_000000000000", "nope", "../etc"):
            with self.assertRaises(NotFound):
                api.get_project(bad)
        with self.assertRaises(NotFound):
            api.create_project("x", "p_000000000000")


class Move(TempHome):
    def test_move_changes_the_parent_and_the_path(self):
        alpha, beta = api.create_project("Alpha"), api.create_project("Beta")
        moved = api.move_project(beta.id, alpha.id)
        self.assertEqual((moved.parent_id, moved.path), (alpha.id, ["Alpha", "Beta"]))
        self.assertIsNone(api.move_project(beta.id, None).parent_id)

    def test_a_cycle_is_refused_with_the_exact_message(self):
        alpha = api.create_project("Alpha")
        beta = api.create_project("Beta", alpha.id)
        gamma = api.create_project("Gamma", beta.id)
        with self.assertRaises(Refused) as caught:
            api.move_project(alpha.id, gamma.id)
        self.assertEqual(str(caught.exception), "Can't move Alpha into Gamma: it is inside Alpha.")
        with self.assertRaises(Refused) as itself:
            api.move_project(alpha.id, alpha.id)
        self.assertEqual(str(itself.exception), "Can't move Alpha into Alpha: it is inside Alpha.")
        self.assertIsNone(api.get_project(alpha.id).parent_id)

    def test_the_inbox_cannot_move_or_take_projects(self):
        alpha = api.create_project("Alpha")
        with self.assertRaises(Refused):
            api.move_project("inbox", alpha.id)
        with self.assertRaises(Refused):
            api.move_project(alpha.id, "inbox")

    def test_a_move_into_an_archived_project_is_refused(self):
        alpha, beta = api.create_project("Alpha"), api.create_project("Beta")
        api.archive_project(alpha.id)
        with self.assertRaises(Refused):
            api.move_project(beta.id, alpha.id)


class Link(TempHome):
    def test_link_is_symmetric_and_idempotent(self):
        alpha, beta = api.create_project("Alpha"), api.create_project("Beta")
        first = api.link_projects(beta.id, alpha.id)
        again = api.link_projects(alpha.id, beta.id)
        self.assertTrue(first.created)
        self.assertFalse(again.created)
        self.assertEqual(api.get_project(alpha.id).linked_ids, [beta.id])
        self.assertEqual(api.get_project(beta.id).linked_ids, [alpha.id])

    def test_self_links_and_the_inbox_are_refused(self):
        alpha = api.create_project("Alpha")
        with self.assertRaises(Refused):
            api.link_projects(alpha.id, alpha.id)
        with self.assertRaises(Refused):
            api.link_projects(alpha.id, "inbox")


class ArchiveAndDelete(TempHome):
    def test_archive_hides_the_project_and_everything_under_it(self):
        alpha = api.create_project("Alpha")
        api.create_project("Beta", alpha.id)
        archived = api.archive_project(alpha.id)
        self.assertIsNotNone(archived.archived_at)
        self.assertEqual([p.name for p in api.list_projects().projects], ["Inbox"])
        self.assertEqual(api.list_projects(include_archived=True).total, 3)
        self.assertEqual(api.archive_project(alpha.id).archived_at, archived.archived_at)

    def test_delete_works_only_on_an_empty_project(self):
        alpha = api.create_project("Alpha")
        beta = api.create_project("Beta", alpha.id)
        with self.assertRaises(Refused) as caught:
            api.delete_project(alpha.id)
        self.assertIn("1 sub-project", str(caught.exception))
        self.assertEqual(api.delete_project(beta.id).name, "Beta")
        api.link_projects(alpha.id, api.create_project("Other").id)
        self.assertEqual(api.delete_project(alpha.id).id, alpha.id)
        with self.assertRaises(NotFound):
            api.get_project(alpha.id)

    def test_the_inbox_cannot_be_archived_or_deleted(self):
        with self.assertRaises(Refused):
            api.archive_project("inbox")
        with self.assertRaises(Refused):
            api.delete_project("inbox")


class ExportJson(TempHome):
    def test_export_holds_the_whole_store_and_its_schema_version(self):
        alpha = api.create_project("Alpha")
        beta = api.create_project("Beta", alpha.id)
        api.link_projects(alpha.id, beta.id)
        dest = os.path.join(self.home, "out", "export.json")
        os.makedirs(os.path.dirname(dest))
        export = api.export_json(dest)
        doc = export.document
        self.assertEqual(doc["format"], "project-studio-export")
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual({p["id"] for p in doc["projects"]}, {"inbox", alpha.id, beta.id})
        self.assertEqual(len(doc["links"]), 1)
        self.assertEqual((doc["items"], doc["rules"], doc["moves"]), ([], [], []))
        self.assertEqual(export.path, dest)
        with open(dest) as fh:
            self.assertEqual(json.load(fh), doc)
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o600)

    def test_export_without_a_destination_writes_nothing(self):
        self.assertIsNone(api.export_json().path)
