"""A night run's ONE status: the only place that decides what a run is, for every surface.

Home, the project view, `status`, `show`, `list`, `find`, the Inbox drawer and the MCP tools all
show `decide`'s answer and nothing else. It reads the run item's data (the reader's `run_state`:
what the state files say) and the run's PR (the PR item the studio already reads), plus whether a
person marked it done. The statuses, checked in this order:

| key | word | when |
|---|---|---|
| merged | Merged | its PR is merged ("PR #738 merged"), whatever its files froze on |
| done | Done | marked done by hand ("marked done by you"), while its files hold still |
| needs-you | Waiting on you | a gate a person answers ("plan gate", "waiting on you"), a login stop, a stage BLOCKED on what only a person can do ("merge conflict with main: merge origin/main"), a runner that stopped |
| blocked | Blocked | a stage BLOCKED or ABANDONED on a failure no person was asked for ("T11 of 13 blocked: ..."), or CI red once every stage settled ("PR #12 open, 2 checks red") |
| running | Running | its runner is alive and a stage runs ("T03 of 5") |
| paused | Paused | a budget wait its runner resumes by itself ("waiting for capacity") |
| in-review | In review | every stage settled, its PR is open and not red ("PR #733 open, checks green", "PR #24 open, no CI") |
| done | Done | every stage settled and it has no PR ("finished, no PR"), or its PR was closed |
| unknown | Unknown | the studio cannot read its state files and it has no PR ("old format: no .next files") |

A project rolls its runs up worst first (`roll_up`): Waiting on you > Blocked > Running > Paused >
In review > Unknown > Merged > Done; "pending" (a middle dot, no word) when it has no runs. The
count words use the same set and order (`counts_text`): "1 waiting on you, 1 in review, 1 merged".
"""

import re

from .results import RunStatus

KEYS = ("needs-you", "blocked", "running", "paused", "in-review", "unknown", "merged", "done")
WORDS = {"needs-you": "Waiting on you", "blocked": "Blocked", "running": "Running", "paused": "Paused",
         "in-review": "In review", "merged": "Merged", "done": "Done", "unknown": "Unknown"}
GLYPHS = {"needs-you": "!", "blocked": "\u2717", "running": "\u25cf", "paused": "\u2016", "in-review": "\u25d0",
          "merged": "\u2713", "done": "\u2713", "unknown": "?", "pending": "\u00b7"}
COUNT_WORDS = {"needs-you": "waiting on you", "blocked": "blocked", "running": "running", "paused": "paused",
               "in-review": "in review", "unknown": "unknown", "merged": "merged", "done": "done", "gone": "gone"}
NO_RUNS = "pending"                 # a project's roll-up with no runs: a middle dot and no word
MARKED_DONE = "marked done by you"
SETTLED = ("in-review", "merged", "done")   # what the files say no longer changes by itself
MARKABLE = ("needs-you", "blocked")         # what a person may mark done by hand

CI_PASS = re.compile(r"^PASS at ([0-9a-f]{7,40})\b")
NO_CI = re.compile(r"\bno CI\b|\b0 checks\b|\bno checks\b", re.I)
PR_NUMBER = re.compile(r"/pull/(\d+)")
# A BLOCKED detail that asks a person to act: a merge a session refused, a login, a manual step. Bare
# "person", "manual" or "login" do not count ("person-sync tests red", "login form tests red").
HUMAN = re.compile(r"\bhuman\b|\bby hand\b|\bmerge conflict|\bconflicts? with\b|\bre-?auth"
                   r"|\b(?:a |the )?person (?:must|needs? to|has to|should)\b|\bmanual steps?\b|\bmanually\b"
                   r"|\blog ?in (?:needed|required|expired)\b|\bneeds? (?:a |to )?log ?in\b", re.I)
HUMAN_ACTION = re.compile(r"\b(?:human|person|you)\s+(?:must|needs? to|has to|should)\s+([^(;.,]+)", re.I)


def status(key, reason=""):
    """A `RunStatus` for `key` (one of KEYS) with its word and glyph."""
    return RunStatus(key=key, word=WORDS[key], reason=reason, glyph=GLYPHS[key])


def parse(word):
    """The key for a status as a person types it ("in-review", "In review", "waiting-on-you"), or None."""
    folded = re.sub(r"[\s_]+", "-", str(word or "").strip().lower())
    by_word = {re.sub(r"\s+", "-", w.lower()): k for k, w in WORDS.items()}
    return folded if folded in KEYS else by_word.get(folded)


def _human_reason(detail):
    """"merge conflict with main: merge origin/main" from a BLOCKED detail a person must act on."""
    head = re.split(r"\s*[(;]|\s+-\s+|,\s", detail, maxsplit=1)[0].strip()
    found = HUMAN_ACTION.search(detail)
    action = found.group(1).strip() if found else ""
    return "%s: %s" % (head, action) if action and action not in head else head or detail


def _stage_label(stage, progress):
    """"T11 of 13" for a ticket stage when the total is known, else the stage's name ("CI")."""
    total = (progress or {}).get("total")
    return "%s of %d" % (stage, total) if total and re.match(r"^T\d+$", stage) else stage


def ci_red(state):
    """True for a FAIL acceptance verdict that the CI ticket did not overrule and that is not "no CI".
    accept.sh writes FAIL whenever `gh pr checks` exits 1, which it also does on a PR with no checks;
    the CI ticket writes "PASS at <sha>" to state/CI.summary when nothing at that head is red."""
    line, summary = str(state.get("acceptance") or ""), str(state.get("ci_summary") or "")
    if line.split(" ")[0] != "FAIL" or NO_CI.search(line) or NO_CI.search(summary):
        return False
    words, passed = line.split(" "), CI_PASS.match(summary)
    sha = words[1] if len(words) > 1 else ""
    return not (sha and passed and (sha.startswith(passed.group(1)) or passed.group(1).startswith(sha)))


def _legacy(data):
    """(key, reason) from a record read before `run_state` existed: its stored word, as the files said it."""
    key, reason = str(data.get("status") or "unknown"), str(data.get("reason") or "")
    if key == "done":
        return "settled", reason
    if key == "blocked" and HUMAN.search(reason):
        return "needs-you", _human_reason(reason)
    if key == "pending":
        return "running", "starting"
    return (key, reason) if key in KEYS else ("unknown", reason)


def _from_files(data):
    """(key, reason) from the state files alone; key "settled" when every stage settled cleanly."""
    st = data.get("run_state")
    if not isinstance(st, dict):
        return _legacy(data)
    if st.get("error"):
        return "unknown", st["error"]
    if not st.get("chain"):
        return "unknown", "old format: no .next files"
    if st.get("waiting"):
        return "needs-you", st["waiting"]
    paused = str(st.get("paused") or "")
    if paused.split(" ")[0].lower().startswith("auth"):
        return "needs-you", "login needed"
    for stop in st.get("blocked") or []:
        detail = str(stop.get("detail") or "")
        if HUMAN.search(detail):
            return "needs-you", _human_reason(detail)
        label = _stage_label(str(stop.get("stage") or ""), data.get("progress"))
        return "blocked", "%s blocked: %s" % (label, detail) if detail else "%s blocked" % label
    if st.get("finished"):
        return "settled", ""
    if st.get("runner") is False:                 # nothing advances, revives or resumes it
        return ("needs-you", "runner stopped") if st.get("started") else ("needs-you", "not started")
    if paused:
        return "paused", "waiting for capacity"
    if not st.get("started"):
        return "running", "starting"
    return "running", (data.get("progress") or {}).get("text") or str(data.get("stage") or "")


def _settled(data, pr):
    """The status of a run whose every stage settled: its PR decides, then CI, then Done."""
    url = str((pr or {}).get("url") or data.get("pr_url") or "")
    number = (pr or {}).get("number") or (int(PR_NUMBER.search(url).group(1)) if PR_NUMBER.search(url) else None)
    name = "PR #%d" % number if number else "its PR"
    state = str((pr or {}).get("state") or "")
    files = data.get("run_state") if isinstance(data.get("run_state"), dict) else {}
    if state == "closed":
        return status("done", "%s closed" % name)
    if not url and not state:
        if ci_red(files):
            return status("blocked", "CI red")
        return status("done", "research finished" if data.get("mode") == "research" else "finished, no PR")
    checks = (pr or {}).get("checks") or {}
    if checks.get("total"):
        if checks.get("red"):
            red = checks["red"]
            return status("blocked", "%s open, %d check%s red" % (name, red, "" if red == 1 else "s"))
        return status("in-review", "%s open, %s" % (name, "checks running" if checks.get("pending") else "checks green"))
    if ci_red(files):
        return status("blocked", "%s open, CI red" % name)
    if not state:
        return status("in-review", "%s, not read yet" % name)
    return status("in-review", "%s open, no CI" % name)


def decide(data, pr=None, marked=False):
    """The one `RunStatus` of a night run. `data` is its item's data (the reader's `run_state`,
    `progress`, `stage`, `mode`, `pr_url`), `pr` its newest PR as `items` reads it ({"number",
    "state", "url", "checks": {"total", "red", "pending"}}) or None, `marked` whether a person's
    mark-done still holds. Order: merged, marked done, then what the files say, then the PR."""
    if pr and pr.get("state") == "merged":
        return status("merged", "PR #%d merged" % pr["number"] if pr.get("number") else "PR merged")
    if marked:
        return status("done", MARKED_DONE)
    key, reason = _from_files(data)
    if key == "settled" or (key == "unknown" and pr and pr.get("state")):
        return _settled(data, pr)
    return status(key, reason)


def files_status(data):
    """The status the state files alone give (no PR, no mark): what the reader stores as `status`."""
    return decide(data)


def rank(key):
    """A status's place in the roll-up, 0 the worst (needs-you); an unknown key sorts with "unknown"."""
    return KEYS.index(key) if key in KEYS else KEYS.index("unknown")


def roll_up(runs):
    """The worst status key over `runs` (anything with `status` and `gone`), gone runs only when
    every run is gone; NO_RUNS for none."""
    live = [r for r in runs if not getattr(r, "gone", False)] or list(runs)
    return min((r.status or "unknown" for r in live), key=rank) if live else NO_RUNS


def roll_up_words(key):
    """(glyph, word) for a roll-up key: a middle dot and '' for NO_RUNS."""
    return (GLYPHS[NO_RUNS], "") if key == NO_RUNS else (GLYPHS.get(key, "?"), WORDS.get(key, key.title()))


def counts_text(runs):
    """"1 waiting on you, 2 blocked, 4 done" for `runs`, worst first; a gone run counts as "gone"
    (last), whatever its last word was; "no runs" for none."""
    counts = {}
    for run in runs:
        key = "gone" if getattr(run, "gone", False) else (run.status or "unknown")
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "no runs"
    keys = sorted(counts, key=lambda k: (len(KEYS) if k == "gone" else rank(k), k))
    return ", ".join("%d %s" % (counts[k], COUNT_WORDS.get(k, k)) for k in keys)
