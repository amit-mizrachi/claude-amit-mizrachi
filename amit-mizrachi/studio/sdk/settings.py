"""The person's settings: one small JSON file, `<data dir>/settings.json` (mode 0600).

It is a file and not a store table because a setting is one value a person sets once, read by
every process, with no history, undo or migration to keep.

One setting today, `terminal`: the app Open in Terminal uses.
- Not set (no file, no key): `open <file>.command`, which hands it to the app that opens .command
  files (Terminal). This is the default.
- "Terminal": `open -a Terminal <file>.command`.
- "iTerm": `osascript` asks iTerm for a new window with the default profile and writes the
  .command file's quoted path into it.
`set_terminal` takes any case and the usual app names ("iterm2", "Terminal.app") and stores the
canonical name; "default" clears it. A value it does not know is refused. A value the file holds
that is not known (edited by hand) falls back to Terminal, with a message that says so.
"""

import json
import os
import tempfile

from . import store
from .errors import InvalidInput
from .results import Settings

SETTINGS_FILE = "settings.json"
TERMINALS = ("Terminal", "iTerm")
ALIASES = {"terminal": "Terminal", "terminal.app": "Terminal", "apple terminal": "Terminal",
           "iterm": "iTerm", "iterm2": "iTerm", "iterm.app": "iTerm", "iterm2.app": "iTerm"}
CLEAR = ("default", "none", "unset", "")


def path():
    return os.path.join(store.home(), SETTINGS_FILE)


def read():
    """settings.json as a dict; {} when there is none or it is malformed."""
    try:
        with open(path()) as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def write(values):
    """Write settings.json atomically, mode 0600."""
    home = store.home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=home)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(values, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path())
    except BaseException:
        os.unlink(tmp)
        raise


def terminal_app(value):
    """The canonical terminal name for `value` (any case, usual app names), or None when unknown."""
    return ALIASES.get(str(value).strip().lower()) if value is not None else None


def terminal():
    """(app, note): the app Open in Terminal uses ("" = the default) and a note when the file
    holds a name it does not know, which then falls back to Terminal."""
    stored = read().get("terminal")
    if stored in (None, ""):
        return "", ""
    app = terminal_app(stored)
    if app:
        return app, ""
    return "Terminal", "Unknown terminal %r in %s (known: %s); using Terminal." % (
        stored, path(), ", ".join(TERMINALS))


def current(message=""):
    stored = read().get("terminal")
    shown = stored if isinstance(stored, str) else ""
    return Settings(terminal=shown, terminals=list(TERMINALS), path=path(),
                    message=message or "Terminal: %s" % (shown or "default (the app that opens .command files)"))


def set_terminal(value):
    """Store the app Open in Terminal uses; "default" clears it. Refuses a name it does not know."""
    word = str(value or "").strip()
    values = read()
    if word.lower() in CLEAR:
        values.pop("terminal", None)
        write(values)
        return current("Terminal: default (the app that opens .command files)")
    app = terminal_app(word)
    if not app:
        raise InvalidInput("Unknown terminal %r. Choose one of: %s, or default." % (word, ", ".join(TERMINALS)))
    values["terminal"] = app
    write(values)
    return current("Terminal: %s. Open in Terminal now opens sessions in %s." % (app, app))
