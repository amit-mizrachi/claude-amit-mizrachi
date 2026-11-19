#!/usr/bin/env bash
# night-sprint requeue - put a SKIPPED or BLOCKED tag back in the queue, the one safe way.
#
#   requeue.sh <WORKSPACE> <TAG>
#
# WHY A SCRIPT. On 2026-11-19 a blocker was fixed by hand and the conductor "re-queued" the tag it
# had skipped by truncating state/T13.status to an empty file. schedule.sh reads an empty status as
# "not ended" and launched T13; watch.sh read the same file as "ended" and closed the session it
# had just started. The ticket sat dead until a STRANDED escalation an hour later. A requeue is
# several files that must change together, so it is this script, never a hand edit.
#
# What it does, for <TAG> and - recursively - every tag whose status reads
# `SKIPPED: blocker <TAG> ...` (they were skipped only because of it):
#   - refuses a tag whose session is still alive (that is revive.sh's or the session's business);
#   - removes .status, .summary, the claim, .session and the runner's advance/emit markers, so the
#     scheduler sees a queued tag that never ran and the runner has nothing stale to act on;
#   - makes sure .queued exists (a chained tag becomes a queued one: its .after/.waits still apply).
# The transcript of an earlier session is kept; a requeued tag starts FRESH. To continue a dead
# session's conversation instead, use revive.sh.
#
# Exit codes: 0 requeued; 1 usage or nothing to requeue; 3 a session for the tag is still alive.

set -uo pipefail

WS="${1:?usage: requeue.sh <WORKSPACE> <TAG>}"
TAG="${2:?usage: requeue.sh <WORKSPACE> <TAG>}"
STATE="$WS/state"
[ -d "$STATE" ] || { echo "requeue: no $STATE" >&2; exit 1; }

note() { printf '%s requeue %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$STATE/EVENTS.log"; }

alive() {   # is the session recorded for this tag still running? Unknown counts as alive.
  local sid; sid="$(tr -d '[:space:]' < "$STATE/$1.session" 2>/dev/null || true)"
  [ -n "$sid" ] || return 1
  [ -f "$WS/agents.sh" ] || return 1
  # shellcheck disable=SC1091
  . "$WS/agents.sh"
  local rows; rows="$(agents_json 2>/dev/null)" || return 0
  printf '%s' "$rows" | python3 -c 'import json,sys
sid=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
sys.exit(0 if any(str(r.get("sessionId") or r.get("id") or "").startswith(sid[:8]) and r.get("pid") and r.get("state")!="done" for r in rows) else 1)' "$sid"
}

# The tag, then everything skipped because of it, transitively.
tags="$(python3 - "$STATE" "$TAG" <<'PY'
import glob, os, sys
state, root = sys.argv[1], sys.argv[2]
out, todo = [root], [root]
while todo:
    t = todo.pop()
    for p in glob.glob(os.path.join(state, "*.status")):
        dep = os.path.basename(p)[:-len(".status")]
        line = (open(p).readline() or "").strip()
        if line.startswith("SKIPPED: blocker %s " % t) and dep not in out:
            out.append(dep); todo.append(dep)
print(" ".join(out))
PY
)"

for t in $tags; do
  if alive "$t"; then
    echo "requeue: $t still has a live session - let it finish, or use revive.sh" >&2
    note "$t refused: live session"
    exit 3
  fi
done

for t in $tags; do
  rm -f "$STATE/$t.status" "$STATE/$t.summary" "$STATE/$t.session" "$STATE/.advanced-$t"
  rm -rf "$STATE/claim-$t"
  : > "$STATE/$t.queued"
  # The runner remembers what it already said about a tag; a requeued tag starts with a clean slate.
  if [ -f "$STATE/.watch-seen" ]; then
    grep -v "^$t:" "$STATE/.watch-seen" > "$STATE/.watch-seen.tmp" 2>/dev/null || true
    cat "$STATE/.watch-seen.tmp" > "$STATE/.watch-seen"; rm -f "$STATE/.watch-seen.tmp"
  fi
  note "$t requeued"
  echo "requeued $t"
done
exit 0
