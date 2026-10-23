"""The store: schema version, WAL, the seeded Inbox, migrations after a backup, newer stores read-only.

These reach into `sdk.store` on purpose: a migration and a newer store can only be staged from
below the public API.
"""

import os
import sqlite3
from unittest import mock

from sdk import api, store
from sdk.errors import ReadOnlyStore

from .support import TempHome


class FreshStore(TempHome):
    def test_it_lives_in_project_studio_home(self):
        api.list_projects()
        self.assertEqual(store.db_path(), os.path.join(self.home, "studio.db"))
        self.assertTrue(os.path.isfile(store.db_path()))

    def test_it_is_wal_at_the_current_schema_version_with_the_inbox(self):
        opened = store.open_store()
        try:
            self.assertEqual(opened.version, store.SCHEMA_VERSION)
            self.assertFalse(opened.read_only)
            self.assertEqual(opened.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            opened.close()
        self.assertEqual(api.get_project(store.INBOX_ID).name, "Inbox")

    def test_a_failed_write_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with store.write() as conn:
                conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p_aaaaaaaaaaaa', 'x', 't', 't')")
                raise RuntimeError("boom")
        self.assertEqual(api.list_projects().total, 1)


class Migration(TempHome):
    def test_an_older_store_is_backed_up_then_migrated(self):
        api.create_project("Alpha")
        later = store.SCHEMA_VERSION + 1

        def to_later(conn):
            conn.execute("ALTER TABLE projects ADD COLUMN colour TEXT")

        with mock.patch.object(store, "SCHEMA_VERSION", later), mock.patch.dict(store.MIGRATIONS, {later: to_later}):
            opened = store.open_store()
            try:
                self.assertEqual(opened.version, later)
                self.assertTrue(opened.backup_path and os.path.isfile(opened.backup_path))
                columns = [r[1] for r in opened.conn.execute("PRAGMA table_info(projects)")]
                self.assertIn("colour", columns)
            finally:
                opened.close()
        backup = sqlite3.connect(opened.backup_path)
        try:
            self.assertEqual(backup.execute("SELECT version FROM schema_version").fetchone()[0], later - 1)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 2)
        finally:
            backup.close()

    def test_a_v1_store_keeps_its_item_moves_and_gains_project_moves(self):
        with mock.patch.object(store, "SCHEMA_VERSION", 1):
            with store.write() as conn:
                conn.execute("INSERT INTO items (id, kind, key, title, project_id, placed_by) "
                             "VALUES ('i_aaaaaaaaaaaa', 'pr', 'o/r#1', 'PR 1', 'inbox', 'inbox')")
                conn.execute("INSERT INTO moves (item_id, from_project, to_project, revision, at) "
                             "VALUES ('i_aaaaaaaaaaaa', 'inbox', 'inbox', 2, 't')")
        with store.read() as conn:
            self.assertEqual(store.version_of(conn), 2)
            move = dict(conn.execute("SELECT * FROM moves").fetchone())
            columns = [r[1] for r in conn.execute("PRAGMA table_info(projects)")]
        self.assertEqual((move["item_id"], move["project_id"], move["revision"]), ("i_aaaaaaaaaaaa", None, 2))
        self.assertIn("revision", columns)
        alpha, beta = api.create_project("Alpha"), api.create_project("Beta")
        moved = api.move(beta.id, alpha.id)
        self.assertIsNotNone(moved.move_id)


class NewerStore(TempHome):
    def test_a_store_from_a_newer_sdk_opens_read_only(self):
        api.create_project("Alpha")
        conn = sqlite3.connect(store.db_path())
        conn.execute("UPDATE schema_version SET version = ?", (store.SCHEMA_VERSION + 1,))
        conn.commit()
        conn.close()
        self.assertEqual(api.list_projects().total, 2)
        with self.assertRaises(ReadOnlyStore):
            api.create_project("Beta")
        opened = store.open_store()
        try:
            self.assertTrue(opened.read_only)
            self.assertEqual(opened.version, store.SCHEMA_VERSION + 1)
        finally:
            opened.close()

    def test_default_reads_still_answer_from_a_newer_store(self):
        alpha = api.create_project("Alpha")
        conn = sqlite3.connect(store.db_path())
        conn.execute("UPDATE schema_version SET version = 99")
        conn.commit()
        conn.close()
        self.assertEqual(api.project_status("inbox").project.id, "inbox")
        self.assertEqual(api.project_status(alpha.id).project.name, "Alpha")
        self.assertEqual(api.find_items().total, 0)
        with self.assertRaises(ReadOnlyStore):
            api.refresh()
