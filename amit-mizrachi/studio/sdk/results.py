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
    item_count: int                 # items whose one home is this project
    linked_ids: List[str] = field(default_factory=list)


@dataclass
class ProjectList:
    """A bounded page of projects. `total` counts every match; `truncated` says some were cut."""

    projects: List[Project]
    total: int
    truncated: bool


@dataclass
class LinkResult:
    """A project-to-project link. `created` is False when the link already existed."""

    a_id: str
    b_id: str
    created: bool


@dataclass
class DeleteResult:
    """The project that `delete_project` removed."""

    id: str
    name: str


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
    """The rule "Always file items like this here" would save."""

    signal: str
    pattern: str
    description: str


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


@dataclass
class RuleList:
    rules: List[Rule]
    total: int


@dataclass
class MoveResult:
    """A move of an item (or, through `move`, a project). `move_id` is what `undo_move` and
    `save_rule_from_move` take; it is None when nothing moved. `followed` lists the auto-attached
    items that moved with a run."""

    item: Optional[Item]
    project: Optional[Project]
    move_id: Optional[int]
    from_project_id: Optional[str]
    to_project_id: Optional[str]
    followed: List[str] = field(default_factory=list)
    rule_preview: Optional[RulePreview] = None
    created: bool = False


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


@dataclass
class SubProject:
    project: Project
    runs: int
    runs_active: int
    top_status: Optional[str]


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


@dataclass
class HomeCard:
    """One top-level project on the home page: at most 3 runs, "+ n earlier runs", "2 inside"."""

    project: Project
    runs: List[HomeRun]
    more: str
    inside: str
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
    """The whole home page: the cards in order and the top bar's facts. `loading` is True until
    the first scan; `first_run` is True when there is no project yet."""

    cards: List[HomeCard]
    caption: str
    inbox_count: int
    source_age: str
    loading: bool
    first_run: bool
    first_run_text: str
    banners: List[HomeBanner]
    generated_at: str


@dataclass
class StudioServer:
    """The running studio: where it listens and whether this call started it."""

    url: str
    pid: int
    port: int
    version: str
    running: bool
    started: bool = False


def to_dict(value):
    """A JSON-ready dict (or list) for any SDK return value."""
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    return dataclasses.asdict(value)
