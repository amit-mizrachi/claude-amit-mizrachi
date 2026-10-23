"""Errors the public SDK raises. Every adapter shows `str(error)` to the user as it is.

Each class has a stable `code`, so an adapter can map it (an MCP tool error, an HTTP status)
without matching on the message text.
"""


class StudioError(Exception):
    """Base class for every error the SDK raises on purpose."""

    code = "error"


class NotFound(StudioError):
    """The id names no project (or no item) in the store."""

    code = "not_found"


class InvalidInput(StudioError):
    """An argument has the wrong type, shape or length."""

    code = "invalid_input"


class Refused(StudioError):
    """The input is well formed, but a rule forbids it (a cycle, a non-empty delete, the Inbox)."""

    code = "refused"


class ReadOnlyStore(StudioError):
    """The store was written by a newer SDK, so this SDK may only read it."""

    code = "read_only"
