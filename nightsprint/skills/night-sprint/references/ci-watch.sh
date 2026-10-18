#!/usr/bin/env bash
# night-sprint CI hand-off - give the PR's CI to a detached watcher session, and return at once.
#
#   ci-watch.sh <WORKSPACE>
#
# WHY THIS EXISTS. The sprint used to end by WAITING: FIX-FINAL ran accept.sh, which polls the
# required checks for up to 15 minutes, took a repair pass on red and polled again. The user does
# not want any sprint session, or themselves, waiting on CI. So the last session that changes code
# calls this instead, writes its status and advances (to TEST, or to the end of the chain). CI is
# then the watcher's business: it waits, fixes what is red, pushes, and reports - outside the chain.
#
# OUTSIDE THE CHAIN, ON PURPOSE. Everything lives in state/ci-watch/, never in state/*.session,
# state/*.status or state/claim-* - watch.sh globs those, and a watcher file there would be read as
# a sprint tag: revived when it ends, counted as open work, closed by close.sh. The runner never
# starts, revives or waits for the watcher, and the sprint ends whether or not CI has finished.
#
# ITS OWN WORKTREE. The watcher fixes in <WORKTREE>-ci, detached at the PR head, so a red check is
# repaired without touching the worktree TEST or FIX-TEST is running in. It pushes HEAD:<BRANCH>,
# never with force.
#
# ONE AT A TIME. A second call while a watcher is alive is a no-op: the watcher always re-reads the
# PR head, so a push made after it started (FIX-TEST) is checked by the same watcher. A watcher
# that finished (status written) or died is replaced, which is how a FIX-TEST push after a green
# result gets checked again.
#
# Writes state/ACCEPTANCE.verdict as `PENDING <sha> ...` so a report written before CI finishes says
# so instead of reading an older verdict. The watcher overwrites it through accept.sh.
#
# Exit 0 on a launch or a no-op, 2 when there is no PR yet, 1 when the launch failed.

set -uo pipefail

WS="${1:?usage: ci-watch.sh <WORKSPACE>}"

. "$WS/agents.sh"

STATE="$WS/state"
CI="$STATE/ci-watch"
mkdir -p "$CI"

note() {
  printf '%s ci-watch %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$STATE/EVENTS.log"
}

WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"
BRANCH="$(tr -d '[:space:]' < "$WS/BRANCH")"
MODE="$(tr -d '[:space:]' < "$WS/PERMISSION_MODE" 2>/dev/null || echo auto)"
SLUG="$(tr -d '[:space:]' < "$WS/SLUG" 2>/dev/null || echo sprint)"
NAME="ns-$SLUG-ci-watch"
CIWT="$WT-ci"

PR="$(cd "$WT" && gh pr view --json number -q .number 2>/dev/null || echo)"
if [ -z "$PR" ]; then
  echo "ci-watch: no PR on $BRANCH yet - nothing to watch" >&2
  note "refused: no PR"
  exit 2
fi
HEAD="$(cd "$WT" && gh pr view "$PR" --json headRefOid -q .headRefOid 2>/dev/null || echo unknown)"

# --- one watcher at a time. Alive (or unknowable) and unfinished -> leave it be.
if [ -f "$CI/session" ] && [ ! -f "$CI/status" ]; then
  sid="$(tr -d '[:space:]' < "$CI/session")"
  if [ -n "$sid" ] && [ "$sid" != "unresolved" ]; then
    pid="$(session_pid "$sid")"; rc=$?
    if [ "$rc" -eq 2 ] || [ -n "$pid" ]; then
      echo "ci-watch: watcher $sid is already on PR #$PR; it re-reads the head, so it will check $HEAD too"
      note "no-op: watcher $sid alive (head $HEAD)"
      exit 0
    fi
  fi
fi

# A previous watcher finished or died: keep its record, start fresh.
if [ -f "$CI/status" ] || [ -f "$CI/session" ]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  for f in status session summary launch.log; do
    [ -f "$CI/$f" ] && mv "$CI/$f" "$CI/$f.$stamp"
  done
fi

# --- the watcher's own worktree, detached at the pushed head. Left as it is when it exists: a
# watcher that died mid-fix may have left work there, and the next one decides what to do with it.
if [ ! -d "$CIWT" ]; then
  git -C "$WT" fetch -q origin "$BRANCH" 2>/dev/null
  if ! git -C "$WT" worktree add -q --detach "$CIWT" "origin/$BRANCH" 2>"$CI/worktree.err"; then
    echo "ci-watch: could not create $CIWT - see $CI/worktree.err" >&2
    note "FAILED: worktree $CIWT"
    exit 1
  fi
fi

printf 'PENDING %s CI handed to the watcher (PR #%s) - nobody is waiting on it\n' "$HEAD" "$PR" \
  > "$STATE/ACCEPTANCE.verdict"

# --- the prompt, filled from the template the bootstrap copied.
PROMPT="$CI/prompt.txt"
python3 - "$WS/ci-watch-prompt.md" "$PROMPT" "$WS" "$PR" "$CIWT" "$BRANCH" <<'PY'
import sys
src, dst, ws, pr, ciwt, branch = sys.argv[1:7]
text = open(src).read()
for k, v in (("<WS>", ws), ("<PR>", pr), ("<CI_WORKTREE>", ciwt), ("<BRANCH>", branch)):
    text = text.replace(k, v)
open(dst, "w").write(text)
PY

( cd "$CIWT" && claude --bg -n "$NAME" --permission-mode "$MODE" "$(cat "$PROMPT")" ) \
  > "$CI/launch.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  echo "ci-watch: FAILED to start the watcher (rc=$rc). See $CI/launch.log" >&2
  printf 'UNKNOWN %s the CI watcher did not start (rc=%s) - check PR #%s by hand\n' "$HEAD" "$rc" "$PR" \
    > "$STATE/ACCEPTANCE.verdict"
  note "FAILED rc=$rc"
  exit 1
fi

sid=""
for _ in $(seq 1 15); do
  rows="$(agents_json)" || break
  sid="$(printf '%s' "$rows" | python3 -c 'import json,sys
want=sys.argv[1]
try: rows=json.load(sys.stdin)
except Exception: sys.exit(0)
best=None
for r in rows:
    if r.get("name")==want and (best is None or r.get("startedAt",0)>best.get("startedAt",0)):
        best=r
if best: print(best.get("sessionId",""))' "$NAME")"
  [ -n "$sid" ] && break
  sleep 2
done
[ -n "$sid" ] || sid="$(sid_from_launch_log "$CI/launch.log")" || sid=""
printf '%s\n' "${sid:-unresolved}" > "$CI/session"

note "started ${sid:-unresolved} ($NAME) for PR #$PR at $HEAD"
echo "ci-watch: CI on PR #$PR handed to watcher ${sid:-unresolved} ($NAME) - do not wait for it"
