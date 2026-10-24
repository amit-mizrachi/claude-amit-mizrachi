"""The store: one SQLite file in WAL mode, its schema, migrations and transactions.

Where: `$PROJECT_STUDIO_HOME/studio.db`, default `~/.project-studio/studio.db`. Never under
`~/.claude`, never iCloud.

Rules this module keeps:
- Every write runs in one `BEGIN IMMEDIATE` transaction (`write()`), so two processes (the MCP
  server, the studio, a hook) never interleave a read-check-write. A writer waits up to
  BUSY_TIMEOUT seconds for the lock: a refresh that stores and reconciles a large store holds it
  for 1 to 2 s per source, back to back, so a shorter wait failed with "database is locked". The
  SessionStart hook has its own, shorter budget (session_hook.py), so it never waits this long.
- The schema version lives in `schema_version`. A store at an older version is backed up to
  `backups/` as a file first, then migrated in one `BEGIN IMMEDIATE`. A store at a NEWER version
  (written by a newer SDK) is opened read-only: reads work, `write()` raises `ReadOnlyStore`.
- The Inbox is a seeded project with the fixed id `inbox`.
- Items and projects carry a `revision` that every move bumps; a move records the revision it
  produced in `moves` (an item's or, since v2, a project's), so an Undo can refuse when something
  moved it since.
- The `moves` table is the ledger of every undoable change, one row per change, each of a
  `MOVE_KINDS` kind (since v4): `move` (a re-home), `dismiss` and `restore` (an item hidden or shown
  again, `items.dismissed_at`). A row's `data_json` keeps what its Undo needs beyond the columns.

Only the SDK touches SQL. Adapters call `sdk.api`.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import quote

from .errors import ReadOnlyStore

SCHEMA_VERSION = 4
INBOX_ID = "inbox"
INBOX_NAME = "Inbox"
DB_NAME = "studio.db"
BUSY_TIMEOUT = 30                   # seconds a connection waits for another writer's lock
ITEM_KINDS = ("session-bg", "session-interactive", "night-sprint", "night-marathon", "artifact", "pr", "worktree")
SESSION_KINDS = ("session-bg", "session-interactive")   # derived, so one session id is ONE item across both
PLACED_BY = ("manual", "title", "cwd", "rule", "inbox")
MOVE_KINDS = ("move", "dismiss", "restore")             # what a `moves` row records (v4)


def home():
    """The data dir: `$PROJECT_STUDIO_HOME`, else `~/.project-studio`."""
    return os.path.abspath(os.path.expanduser(os.environ.get("PROJECT_STUDIO_HOME") or "~/.project-studio"))


def db_path():
    """The store file inside the data dir."""
    return os.path.join(home(), DB_NAME)


def now_iso():
    """The current time as ISO 8601 UTC, to the second."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sql_list(values):
    return ", ".join("'%s'" % v for v in values)


def _schema_v1(conn):
    statements = [
        "CREATE TABLE schema_version (version INTEGER NOT NULL)",
        """CREATE TABLE projects (
             id TEXT PRIMARY KEY,
             name TEXT NOT NULL,
             parent_id TEXT REFERENCES projects(id),
             archived_at TEXT,
             created_at TEXT NOT NULL,
             updated_at TEXT NOT NULL)""",
        "CREATE INDEX projects_parent ON projects(parent_id)",
        """CREATE TABLE links (
             a_id TEXT NOT NULL REFERENCES projects(id),
             b_id TEXT NOT NULL REFERENCES projects(id),
             created_at TEXT NOT NULL,
             PRIMARY KEY (a_id, b_id),
             CHECK (a_id < b_id))""",
        """CREATE TABLE items (
             id TEXT PRIMARY KEY,
             kind TEXT NOT NULL CHECK (kind IN (%s)),
             key TEXT NOT NULL,
             title TEXT NOT NULL DEFAULT '',
             project_id TEXT NOT NULL REFERENCES projects(id),
             placed_by TEXT NOT NULL CHECK (placed_by IN (%s)),
             workspace_item_id TEXT REFERENCES items(id),
             revision INTEGER NOT NULL DEFAULT 1,
             data_json TEXT NOT NULL DEFAULT '{}',
             seen_at TEXT,
             gone_at TEXT,
             UNIQUE (kind, key))""" % (_sql_list(ITEM_KINDS), _sql_list(PLACED_BY)),
        "CREATE INDEX items_project ON items(project_id)",
        """CREATE TABLE rules (
             id TEXT PRIMARY KEY,
             project_id TEXT NOT NULL REFERENCES projects(id),
             signal TEXT NOT NULL,
             pattern TEXT NOT NULL,
             created_at TEXT NOT NULL)""",
        """CREATE TABLE moves (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             item_id TEXT NOT NULL REFERENCES items(id),
             from_project TEXT,
             to_project TEXT NOT NULL,
             revision INTEGER NOT NULL,
             at TEXT NOT NULL)""",
        """CREATE TABLE cache (
             source TEXT NOT NULL,
             key TEXT NOT NULL,
             fetched_at TEXT,
             ok INTEGER NOT NULL DEFAULT 0,
             error TEXT,
             payload_json TEXT,
             PRIMARY KEY (source, key))""",
    ]
    for sql in statements:
        conn.execute(sql)
    stamp = now_iso()
    conn.execute("INSERT INTO projects (id, name, parent_id, archived_at, created_at, updated_at) "
                 "VALUES (?, ?, NULL, NULL, ?, ?)", (INBOX_ID, INBOX_NAME, stamp, stamp))


def _schema_v2(conn):
    """Project moves get Undo: projects carry a revision, and a `moves` row is an item's move
    (item_id set) or a project's (project_id set, from/to = old/new parent, NULL = top level)."""
    conn.execute("ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
    conn.execute("""CREATE TABLE moves_v2 (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             item_id TEXT REFERENCES items(id),
             project_id TEXT REFERENCES projects(id),
             from_project TEXT,
             to_project TEXT,
             revision INTEGER NOT NULL,
             at TEXT NOT NULL,
             CHECK ((item_id IS NULL) != (project_id IS NULL)))""")
    conn.execute("INSERT INTO moves_v2 (id, item_id, project_id, from_project, to_project, revision, at) "
                 "SELECT id, item_id, NULL, from_project, to_project, revision, at FROM moves")
    conn.execute("DROP TABLE moves")
    conn.execute("ALTER TABLE moves_v2 RENAME TO moves")


def _schema_v3(conn):
    """Undo puts an item back as it was: a move keeps the placement it replaced (`from_placed_by`),
    and a rule learned from a move keeps that move's id (`move_id`), so undoing the move drops it."""
    conn.execute("ALTER TABLE moves ADD COLUMN from_placed_by TEXT")
    conn.execute("ALTER TABLE rules ADD COLUMN move_id INTEGER")


def _schema_v4(conn):
    """Dismiss and restore: an item can be hidden from every list without touching the thing itself
    (`items.dismissed_at`, NULL while shown), and the move ledger gets a `kind` per row (every older
    row is a `move`) plus `data_json`, what the row's Undo needs (a dismissal's attached items), so a
    later kind needs only its name in MOVE_KINDS and its Undo in `items.UNDO`, not a new column."""
    conn.execute("ALTER TABLE items ADD COLUMN dismissed_at TEXT")
    conn.execute("ALTER TABLE moves ADD COLUMN kind TEXT NOT NULL DEFAULT 'move'")
    conn.execute("ALTER TABLE moves ADD COLUMN data_json TEXT NOT NULL DEFAULT '{}'")


# version -> the step that takes a store from version - 1 to version. Steps run in order, all
# inside one BEGIN IMMEDIATE, after a file backup of the old store. A new version is one more
# `_schema_v<n>` (ALTER TABLE / CREATE TABLE only, never a read of the data dir) and one entry here.
MIGRATIONS = {1: _schema_v1, 2: _schema_v2, 3: _schema_v3, 4: _schema_v4}


class Store(object):
    """An open connection plus what the SDK learned while opening it."""

    def __init__(self, conn, version, read_only, backup_path=None):
        self.conn = conn
        self.version = version
        self.read_only = read_only
        self.backup_path = backup_path

    def close(self):
        self.conn.close()


def _connect(path, read_only):
    if read_only:
        conn = sqlite3.connect("file:%s?mode=ro" % quote(path), uri=True, isolation_level=None, timeout=BUSY_TIMEOUT)
    else:
        conn = sqlite3.connect(path, isolation_level=None, timeout=BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = %d" % (BUSY_TIMEOUT * 1000))
    return conn


def version_of(conn):
    """The schema version recorded in an open store, 0 for an empty file."""
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchone()
    if not row:
        return 0
    found = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    return int(found or 0)


def _backup(conn, version):
    """Copy the whole store to backups/ before a migration touches it. Returns the copy's path."""
    folder = os.path.join(home(), "backups")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    dest = os.path.join(folder, "studio-v%d-%s-%d.db" % (version, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    return dest


def _migrate(conn, version):
    backup = _backup(conn, version) if version > 0 else None
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = version_of(conn)            # another process may have migrated while we waited
        for step in range(current + 1, SCHEMA_VERSION + 1):
            MIGRATIONS[step](conn)
        if current == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        elif current < SCHEMA_VERSION:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return backup


def open_store():
    """Open (creating or migrating when needed) the store. The caller must `close()` it."""
    os.makedirs(home(), mode=0o700, exist_ok=True)
    path = db_path()
    conn = _connect(path, read_only=False)
    try:
        version = version_of(conn)
        if version > SCHEMA_VERSION:
            conn.close()
            return Store(_connect(path, read_only=True), version, read_only=True)
        conn.execute("PRAGMA journal_mode = WAL")
        backup = _migrate(conn, version) if version < SCHEMA_VERSION else None
    except BaseException:
        conn.close()
        raise
    return Store(conn, SCHEMA_VERSION, read_only=False, backup_path=backup)


@contextmanager
def read():
    """A connection holding one consistent snapshot of the store, for reads only."""
    store = open_store()
    try:
        store.conn.execute("BEGIN")
        try:
            yield store.conn
        finally:
            store.conn.execute("COMMIT")
    finally:
        store.close()


def read_only_error(version):
    """The `ReadOnlyStore` a write to a store stamped `version` (newer than this SDK) raises."""
    return ReadOnlyStore("The store at %s was written by a newer Project Studio (schema v%d); this one "
                         "knows v%d, so it can only read it. Update the amit-mizrachi plugin."
                         % (db_path(), version, SCHEMA_VERSION))


@contextmanager
def write():
    """A connection inside one BEGIN IMMEDIATE transaction: committed on success, rolled back on error."""
    store = open_store()
    try:
        if store.read_only:
            raise read_only_error(store.version)
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            yield store.conn
        except BaseException:
            store.conn.execute("ROLLBACK")
            raise
        store.conn.execute("COMMIT")
    finally:
        store.close()

