"""Night-run counts in words, the one wording home, the project view, `list`, `show` and `status` use.

"2 blocked, 1 running, 4 done": one count per status, in rank order (waiting on you, blocked,
running, paused, then the rest, done last), so the first word is the most urgent. A gone run
counts as "gone", whatever its last word was. No runs at all is "no runs".
"""

ORDER = ("needs-you", "blocked", "running", "paused", "pending", "unknown", "done", "gone")
COUNT_WORDS = {"needs-you": "waiting on you", "blocked": "blocked", "running": "running", "paused": "paused",
               "pending": "pending", "unknown": "unknown", "done": "done", "gone": "gone"}


def _key(run):
    return "gone" if getattr(run, "gone", False) else (run.status or "unknown")


def run_counts_text(runs):
    """"2 blocked, 1 running, 4 done" for `Run`s (anything with `status` and `gone`); "no runs" for none."""
    counts = {}
    for run in runs:
        key = _key(run)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "no runs"
    other = ORDER.index("done")      # a word the studio does not know sorts just before "done"
    keys = sorted(counts, key=lambda k: (ORDER.index(k) if k in ORDER else other - 0.5, k))
    return ", ".join("%d %s" % (counts[k], COUNT_WORDS.get(k, k)) for k in keys)
