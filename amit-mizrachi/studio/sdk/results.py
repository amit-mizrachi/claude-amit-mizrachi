"""The structured values the public SDK returns. Adapters serialise them with `to_dict`.

Every field here is part of the public contract (studio/sdk/README.md). Add fields freely;
never rename or remove one without a new major version of the contract.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Project:
    """One project in the tree. The Inbox is a project too, with `is_inbox` set."""

    id: str
    name: str
    parent_id: Optional[str]
    path: List[str]                 # names from the top level down, this project last
    is_inbox: bool
    archived_at: Optional[str]      # ISO 8601 UTC, None while the project is active
    created_at: str
    updated_at: str
    child_count: int                # direct sub-projects, archived ones included
    item_count: int                 # items whose one home is this project; the Inbox: only what it shows
    linked_ids: List[str] = field(default_factory=list)


@dataclass
class ProjectList:
    """A bounded page of projects. `total` counts every match; `truncated` says some were cut.
    `run_lines` (only when asked for) maps a project id to its night-run line, "running - 3 runs, 1 active"."""

    projects: List[Project]
    total: int
    truncated: bool
    run_lines: Dict[str, str] = field(default_factory=dict)


@dataclass
class LinkResult:
    """A project-to-project link. `created` is False when the link already existed."""

    a_id: str
    b_id: str
    created: bool


@dataclass
class UnlinkResult:
    """What `unlink_projects` did. `removed` is False when the two were not linked (nothing changed)."""

    a_id: str
    b_id: str
    removed: bool


@dataclass
class DeleteResult:
    """The project that `delete_project` removed."""

    id: str
    name: str


@dataclass
class DeleteRequest:
    """What `delete_project_guarded` did. `deleted` False with `needs_confirm`: nothing changed, and
    `message` says what a confirmed call would delete (the project, `links` links, `rules` rules)."""

    id: str
    name: str
    deleted: bool
    needs_confirm: bool
    links: int
    rules: int
    message: str


@dataclass
class Export:
    """The whole store as one JSON-ready document, and the file it was written to (if any)."""

    document: Dict[str, Any]
    path: Optional[str]


@dataclass
class Item:
    """One item with exactly one home project. `data` is what its reader last said (kind-specific:
    a session's cwd and short id, a run's progress, a PR's state, ...), plus `signals` and `scope`."""

    id: str
    kind: str                       # session-bg, session-interactive, night-sprint, night-marathon, artifact, pr, worktree
    key: str                        # the stable id: session UUID, folder path, URL, owner/repo#n
    title: str
    project_id: str
    project_path: List[str]
    placed_by: str                  # manual, title, cwd, rule, inbox
    workspace_item_id: Optional[str]
    revision: int                   # bumped by every move; pass it to a move to refuse a stale one
    status: str                     # from data.status ("unknown" when its source failed)
    gone: bool
    gone_at: Optional[str]
    seen_at: Optional[str]
    data: Dict[str, Any] = field(default_factory=dict)
    dismissed: bool = False         # hidden from home, the project view's lists, the Inbox, list / status / find
    dismissed_at: Optional[str] = None
    done_marked_at: Optional[str] = None   # when a night run was marked done by hand (it may be out of date)


@dataclass
class ItemList:
    """A bounded page of items. `total` counts every match; `truncated` says some were cut."""

    items: List[Item]
    total: int
    truncated: bool


@dataclass
class SourceState:
    """What one reader said last: `ok` False means its items are kept from `good_at` and are not complete."""

    source: str
    key: str
    ok: bool
    error: str
    fetched_at: Optional[str]
    good_at: Optional[str]
    partial: bool


@dataclass
class RefreshResult:
    """One refresh: the reads it made, what the reconcile changed, and every source's state."""

    reads: List[Dict[str, Any]]
    added: int
    filed: int
    gone: int
    back: int
    sources: List[SourceState]


@dataclass
class RulePreview:
    """The rule "Always file items like this here" would save. `parts` are its (word, value) pairs,
    so the studio can set each value as code: [["repo", "shapes-platform"], ["branch", "eval/*"]]."""

    signal: str
    pattern: str
    description: str
    parts: List[List[str]] = field(default_factory=list)


@dataclass
class Rule:
    """An attach rule learned from a move. `created` is False when the same rule already existed."""

    id: str
    project_id: str
    project_name: str
    signal: str
    pattern: str
    description: str
    created_at: str
    created: bool = False
    parts: List[List[str]] = field(default_factory=list)


@dataclass
class RuleList:
    rules: List[Rule]
    total: int


@dataclass
class RuleSample:
    """One Inbox item a rule written by pattern would file now."""

    item_id: str
    title: str
    kind: str


@dataclass
class RuleFiling:
    """One Inbox item `add_rule` with apply filed: its own `move_id` for `undo_move`, and the
    auto-attached items that went with it (`followed`)."""

    item_id: str
    title: str
    move_id: Optional[int]
    followed: List[str] = field(default_factory=list)


@dataclass
class RuleAdd:
    """A rule written by pattern (`add_rule`). `preview` is the rule as it is stored and shown;
    `rule` is the saved one (None on a dry run; `created` False when the same rule was there).
    `matching` counts the Inbox items it files now, `sample` names up to 5 of them (newest first),
    `filed` holds one move per item when it was applied. `message` says it in words."""

    preview: RulePreview
    project_id: str
    project_name: str
    rule: Optional[Rule]
    dry_run: bool
    created: bool
    matching: int
    sample: List[RuleSample] = field(default_factory=list)
    filed: List[RuleFiling] = field(default_factory=list)
    message: str = ""


@dataclass
class MoveResult:
    """A move of an item (or, through `move`, a project), a dismissal or restore of an item,
    or a night run's mark-done (`kind`). `move_id` is what `undo_move` (and, for an item's move, `save_rule_from_move`) take;
    it is None when nothing changed. `followed` lists the auto-attached items that went with a run.
    `message` is the toast: "Moved to Project Studio", "Dismissed alpha", "Marked alpha done"."""

    item: Optional[Item]
    project: Optional[Project]
    move_id: Optional[int]
    from_project_id: Optional[str]
    to_project_id: Optional[str]
    followed: List[str] = field(default_factory=list)
    rule_preview: Optional[RulePreview] = None
    created: bool = False
    message: str = ""
    kind: str = "move"              # what the ledger row records: move, dismiss, restore, mark-done, unmark-done


@dataclass
class Suggestion:
    project_id: str
    project_name: str
    reason: str


@dataclass
class InboxEntry:
    item: Item
    suggestion: Optional[Suggestion]


@dataclass
class InboxList:
    entries: List[InboxEntry]
    total: int
    truncated: bool


@dataclass
class Run:
    """One night run, as a card or a run panel shows it."""

    item_id: str
    kind: str
    title: str
    project_id: str
    status: str                     # needs-you, blocked, running, paused, pending, done, unknown
    reason: str
    progress: Optional[Dict[str, Any]]   # {"current": "T03", "index": 3, "total": 5, "text": "T03 of 5"}
    stage: str
    stages: List[Dict[str, Any]]
    pr: Optional[Dict[str, Any]]    # {"key", "number", "state", "draft", "url", "good_at"}
    artifact_url: str
    started_at: str
    updated_at: str
    gone: bool
    progress_text: str = ""         # "T03 of 5", "5 of 5" once done, "at CI - 5 of 5 done", as home and show say it
    pr_text: str = ""               # "PR #12 draft - checks green", or ""
    marked_done: bool = False       # Done because a person marked it, not its files ("marked done by you")


@dataclass
class SubProject:
    project: Project
    runs: int
    runs_active: int
    top_status: Optional[str]
    text: str = ""                  # "no runs", "3 runs, 1 active", "2 runs done", as its tile says it


@dataclass
class ProjectStatus:
    """A project's night runs (ranked needs-you > blocked > running > latest), sessions, PRs,
    worktrees and artifacts, rolled up over its sub-projects, and every source's state."""

    project: Project
    runs: List[Run]
    sessions: List[Item]
    prs: List[Item]
    worktrees: List[Item]
    artifacts: List[Item]
    sub_projects: List[SubProject]
    sources: List[SourceState]
    totals: Dict[str, int] = field(default_factory=dict)   # runs/sessions/prs/worktrees/artifacts before `limit`
    truncated: bool = False                                  # some list was cut to `limit`


@dataclass
class AttachResult:
    """What the SessionStart hook did with a starting session. `item` is None when it was skipped
    (`skipped` says why: "headless"); `created` is False when the studio already knew it."""

    item: Optional[Item]
    created: bool
    skipped: Optional[str] = None


@dataclass
class PurgeResult:
    ids: List[str]
    count: int


@dataclass
class HomeRun:
    """One run line on a home card. `glyph` is night-watch's; `bar` has one cell per ticket:
    d done, r running, b blocked, w waiting on you, '' to do. `open_plan_url` is set only for a run
    waiting on you that has a plan page."""

    item_id: str
    title: str
    status: str
    glyph: str
    word: str
    reason: str
    progress: str
    bar: List[str]
    open_plan_url: str
    pr: str
    gone: bool
    sub_project_id: str = ""        # the card's sub-project the run lives in (or under), '' for the card's own
    sub_project: str = ""           # its tag: "in Machina decision units", '' for the card's own


@dataclass
class HomeSubProject:
    """One active sub-project as a line on its parent's home card: its own glyph, status word and
    run line ("3 runs, 1 active", "no runs"), and "2 inside" for the levels below it. A click
    opens `project_id`'s view."""

    project_id: str
    name: str
    status: str                     # pending (no runs), needs-you, blocked, running, paused, done, ...
    glyph: str
    word: str                       # "Running", "Done", ...; '' with no runs
    text: str
    inside: str


@dataclass
class HomeCard:
    """One top-level project on the home page: its active sub-projects in tree order, at most 3
    runs, "+ n earlier runs"."""

    project: Project
    sub_projects: List[HomeSubProject]
    runs: List[HomeRun]
    more: str
    pr: str
    attention: str                  # needs-you, blocked or ''
    empty: str
    changed_at: str


@dataclass
class HomeBanner:
    """A failed source, as the home page's banner says it. The items keep their last-good state."""

    source: str
    key: str
    text: str
    error: str


@dataclass
class HomeState:
    """The whole home page: the cards in order and the top bar's facts. `loading` is False once
    the store answered (the page shows its skeleton only before that); `first_run` is True when
    there is no project yet. `reading` names the sources still being read (say ["prs"]) and
    `reading_text` is the quiet note for them ("Still reading PRs..."), '' when none is."""

    cards: List[HomeCard]
    caption: str
    inbox_count: int
    source_age: str
    loading: bool
    first_run: bool
    first_run_text: str
    banners: List[HomeBanner]
    reading: List[str]
    reading_text: str
    generated_at: str
    archived: List[Dict[str, str]] = field(default_factory=list)   # [{"id", "name", "archived_at"}]: each
    # archived project ("Alpha / Old"), in tree order, for the page's "Show archived" list and its Unarchive


@dataclass
class StudioServer:
    """The running studio: where it listens and whether this call started it."""

    url: str
    pid: int
    port: int
    version: str
    running: bool
    started: bool = False


# ---------------------------------------------------------------- the project view and open actions (ticket 05)

@dataclass
class ViewTile:
    """One sub-project tile in "Inside <n>": glyph by its top run status, and "1 run done" / "no runs"."""

    project_id: str
    name: str
    status: str                     # its top run's status, "pending" when it has no runs
    glyph: str
    text: str


@dataclass
class ViewRun:
    """One run panel. `detail` sits before the stage bar ("REDRAW - T03 of 5"), `started` and `pr`
    after it. `terminal_item_id` is the run's live session (None: no "Open in Terminal")."""

    item_id: str
    title: str
    status: str
    glyph: str
    word: str
    detail: str
    bar: List[str]
    started: str
    pr: str
    has_plan: bool
    has_pr: bool
    terminal_item_id: Optional[str]
    gone: bool
    can_mark_done: bool = False     # a Blocked or Waiting-on-you run shows "Mark done"


@dataclass
class ViewSession:
    """One session row: bg live ("working - 2 min"), bg done ("finished - 3 h"), interactive
    ("last active 1 d") or gone ("(removed)", "gone - 9 h"). `action` is the button's text."""

    item_id: str
    kind: str                       # bg or interactive
    title: str
    status: str                     # running, done, pending, unknown (gone)
    glyph: str
    age: str
    action: str                     # "Open in Terminal" or "Resume in Terminal"
    gone: bool


@dataclass
class ViewRow:
    """One line inside a fold row (a PR, a worktree, an artifact) and the button that opens it."""

    item_id: str
    title: str
    text: str
    action: str                     # "Open", "Show in Finder", or "Restore" (a dismissed row)


@dataclass
class ViewFold:
    """One collapsed line of "Everything else": "Pull requests 2 - 1 open, 1 merged". The sessions
    fold (only when no session is active) has no `rows`: its rows are `ProjectView.sessions`."""

    kind: str                       # sessions, prs, worktrees, artifacts, dismissed
    label: str
    count: int
    summary: str
    rows: List[ViewRow]


@dataclass
class ProjectView:
    """The whole project view (`#/p/<id>`): breadcrumb, "Linked: ..." text, sub-project tiles, run
    panels, session rows (or a sessions fold when all are idle), the fold rows, and the projects
    "Link..." can offer."""

    project: Project
    crumbs: List[Dict[str, str]]    # [{"id", "name"}] from the top level down to the parent
    linked: str                     # "Linked: night-sprint plugin", or ""
    link_choices: List[Dict[str, str]]   # [{"id", "name"}]: active projects it is not linked to yet
    inside: List[ViewTile]
    runs: List[ViewRun]
    sessions: List[ViewSession]
    sessions_folded: bool
    folds: List[ViewFold]
    generated_at: str
    rules: List[Rule] = field(default_factory=list)   # this project's attach rules, each deletable
    dismissed: Optional[ViewFold] = None   # the "Dismissed" fold at the bottom (rows: Restore), None when empty
    links: List[Dict[str, str]] = field(default_factory=list)   # [{"id", "name"}]: the projects "Linked: ..."
    # names, in its order, each with an unlink control on the page


# ---------------------------------------------------------------- the Inbox drawer and the picker (ticket 06)

@dataclass
class InboxRow:
    """One row of the Inbox drawer. `revision` goes back with a drag, so a stale drop is refused."""

    item_id: str
    revision: int
    title: str
    meta: str                      # kind and one fact, joined by a middle dot: "interactive", "2 h"
    chip: str                      # an arrow and the suggested project, or '' with no suggestion
    chip_title: str                # why: "rule: repo shapes-platform + branch eval/*"
    can_accept: bool


@dataclass
class InboxView:
    """The Inbox drawer: its rows (newest first), the full count, the hint and the empty text."""

    rows: List[InboxRow]
    count: int
    truncated: bool
    hint: str
    empty: str


@dataclass
class MoveChoice:
    id: Optional[str]              # a project id; None = the top level (Set parent only)
    label: str                     # the project's path, "Project Studio / Studio MCP tools"


@dataclass
class MoveChoices:
    """What "Move to..." (an item) or "Set parent" (a project) offers, in tree order."""

    target_id: str
    kind: str                      # item or project
    name: str
    title: str                     # "Move <name> to..." or "Set parent of <name>"
    revision: Optional[int]        # an item's revision, sent back with the move
    choices: List[MoveChoice]


@dataclass
class TerminalCommand:
    """The command that opens a session again: `claude attach <short>` when `claude agents` lists it
    (`mode` attach), else `cd <cwd> && claude --resume <id>` (`mode` resume). `confirm` is set when
    the session's transcript changed in the last 5 minutes: it may still be open elsewhere."""

    item_id: str                    # the session item the command is for
    mode: str                       # attach or resume
    command: str
    session_id: str
    short: str
    cwd: str
    confirm: str


@dataclass
class TerminalOpen:
    """What Open in Terminal did. `opened`: the terminal app took the .command file. Else `copied`
    says the command went to the clipboard. `needs_confirm`: nothing ran; ask, then call again
    confirmed. `app` is the app it went to: the `terminal` setting, or "" for the default."""

    command: TerminalCommand
    opened: bool
    copied: bool
    needs_confirm: bool
    path: Optional[str]             # the .command file, when one was written
    message: str
    app: str = ""


@dataclass
class Settings:
    """The person's settings (`<data dir>/settings.json`). `terminal` is the app Open in Terminal
    uses: "Terminal", "iTerm", or "" for the default (the app that opens .command files)."""

    terminal: str
    terminals: List[str]            # the names `set_terminal` takes
    path: str
    message: str


@dataclass
class OpenResult:
    """What an open action did: `how` is url (browser), folder (Finder), file, or reveal (`open -R`)."""

    item_id: str
    target: str                     # default, plan or pr
    value: str
    how: str
    opened: bool
    message: str


def to_dict(value):
    """A JSON-ready dict (or list) for any SDK return value."""
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    return dataclasses.asdict(value)
