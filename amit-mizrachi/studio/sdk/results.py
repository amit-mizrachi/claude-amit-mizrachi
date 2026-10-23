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


def to_dict(value):
    """A JSON-ready dict (or list) for any SDK return value."""
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    return dataclasses.asdict(value)
