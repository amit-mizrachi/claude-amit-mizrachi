#!/usr/bin/env bash
# night-sprint acceptance gate - is the thing actually green, at the sha that is actually pushed?
#
#   accept.sh <WORKSPACE> [TIMEOUT_SECONDS]
#
# Writes state/ACCEPTANCE.verdict, one line:
#   PASS <sha>                every required check passed at the pushed head
#   FAIL <sha> <what>         a required check failed, or local and remote disagree
#   UNKNOWN <sha> <why>       no PR, no checks reported, or the wait ran out
#
# Prints the same line. Exit 0 on PASS, 1 on FAIL, 2 on UNKNOWN.
#
# WHY IT EXISTS. A sprint reported all 21 of its stages complete and finished with a red PR.
# Every one of those stages was telling the truth about itself: each session ran the verify
# command, each saw green, each wrote DONE. DONE means "this session finished its work". It
# has never meant "the branch is acceptable", and a night that treats the two as the same
# thing ships a red PR with a green report on top of it.
#
# The specific way it went wrong is worth naming, because it is the common one: the local
# check and CI did not check the same things. A formatter failure came back from CI twice and
# was twice read as a warning-only lint rule. So this script asks the ONE authority that
# cannot be misread - the checks GitHub actually ran, at the sha that is actually pushed - and
# it compares the pushed sha to the local HEAD first, because a green check on a commit that
# was never pushed proves nothing at all.

set -uo pipefail

WS="${1:?usage: accept.sh <WORKSPACE> [TIMEOUT_SECONDS]}"
TIMEOUT="${2:-900}"

STATE="$WS/state"
mkdir -p "$STATE"
OUT="$STATE/ACCEPTANCE.verdict"
WT="$(tr -d '[:space:]' < "$WS/WORKTREE")"

verdict() {
  printf '%s\n' "$*" > "$OUT"
  printf '%s acceptance %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$STATE/EVENTS.log"
  printf '%s\n' "$*"
}

cd "$WT" || { verdict "UNKNOWN - no-worktree $WT"; exit 2; }

LOCAL="$(git rev-parse HEAD 2>/dev/null || echo)"
[ -n "$LOCAL" ] || { verdict "UNKNOWN - cannot read HEAD"; exit 2; }

# An unpushed commit is the cheapest way to hold a green report over a red branch: CI has
# never seen the code the report is about.
UPSTREAM="$(git rev-parse '@{upstream}' 2>/dev/null || echo)"
if [ -z "$UPSTREAM" ]; then
  verdict "FAIL $LOCAL branch has no upstream - nothing was pushed"
  exit 1
fi
if [ "$LOCAL" != "$UPSTREAM" ]; then
  verdict "FAIL $LOCAL local HEAD is not the pushed head ($UPSTREAM) - push before claiming green"
  exit 1
fi

PR="$(gh pr view --json number -q .number 2>/dev/null || echo)"
[ -n "$PR" ] || { verdict "UNKNOWN $LOCAL no PR on this branch yet"; exit 2; }

# Wait for the checks to settle, rather than reading a snapshot mid-run and calling a pending
# lane a pass. `gh pr checks --watch` exits 0 when all required checks pass, 1 when any fails,
# 8 when some are still pending - and the timeout keeps a hung lane from holding the night.
deadline=$(( $(date +%s) + TIMEOUT ))
rc=8
while [ "$(date +%s)" -lt "$deadline" ]; do
  out="$(gh pr checks "$PR" --required 2>&1)"; rc=$?
  case "$rc" in
    0|1) break ;;
    *)   sleep 30 ;;
  esac
done

# Whatever happened, record which lanes are not green - a verdict nobody can act on is half a
# verdict. Names only; the logs stay on GitHub where they cost no context.
failing="$(printf '%s\n' "${out:-}" | awk '$2=="fail"||$2=="failure"{printf "%s ", $1}')"

case "$rc" in
  0) verdict "PASS $LOCAL all required checks green (PR #$PR)"; exit 0 ;;
  1) verdict "FAIL $LOCAL required checks failing (PR #$PR): ${failing:-see gh pr checks}"; exit 1 ;;
  *) verdict "UNKNOWN $LOCAL checks still pending after ${TIMEOUT}s (PR #$PR)"; exit 2 ;;
esac
