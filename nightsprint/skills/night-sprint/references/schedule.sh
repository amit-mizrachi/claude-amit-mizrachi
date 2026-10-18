#!/usr/bin/env bash
# night-sprint scheduler - starts every QUEUED tag whose dependencies have settled.
#
#   schedule.sh <WORKSPACE>
#
# The `.next` chain moves one tag at a time, and the next tag waits for the last. Two kinds of
# tag do not belong on it:
#   - an async checkpoint review (REVIEW-C<n>). It reads a snapshot of the branch while the next
#     ticket keeps building, so nothing on the chain ever waits for it;
#   - in blitz mode, every ticket. A ticket waits for the tickets that really block it, not for
#     whichever ticket happened to be numbered before it.
# Those tags are QUEUED at kickoff instead of wired, and this script starts them. The runner
# calls it on every sweep. Sessions do not: a launch can take half a minute, and a session's own
# shell call may time out and kill it halfway through a claim.
#
# Reads, per tag:
#   state/<TAG>.queued - present = start this tag once it is ready. Never removed, so the
#                        board can tell a queued tag from a chained one.
#   state/<TAG>.after  - HARD dependencies, whitespace separated. Each must end DONE (through
#                        any relays: T03 RELAYED to T03c2 is settled when T03c2 is). A dependency
#                        that ends BLOCKED or SKIPPED can never feed this tag, so the tag is
#                        written `SKIPPED: blocker <X> <word>`, and its own dependents follow it.
#   state/<TAG>.waits  - SOFT dependencies. Each must merely have ended, any way at all.
#                        REVIEW-FINAL waits like this on the checkpoint reviews and the last
#                        tickets: one blocked ticket must not stop the final review.
#   MAX_PARALLEL       - in blitz mode, how many WRITERS may run at once. A writer is any claimed,
#                        unfinished tag that is not a review finder (REVIEW-*). Finders only
#                        read, each in its own snapshot worktree, so they never count.
#   BLITZ              - `1` in blitz mode. Otherwise the cap is 1.
#   state/PAUSED       - present: start nothing, exactly like launch.sh.
# Writes state/EVENTS.log, one line per start and per skip. Always exits 0 after a clean run.

set -uo pipefail

WS="${1:?usage: schedule.sh <WORKSPACE>}"
STATE="$WS/state"
mkdir -p "$STATE"

note() { printf '%s schedule %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$STATE/EVENTS.log"; }

[ -f "$STATE/PAUSED" ] && exit 0
ls "$STATE"/*.queued >/dev/null 2>&1 || exit 0

# One scheduler at a time, or two sweeps could each count the same free slot. A lock left by a
# killed run is stale after ten minutes; no single pass takes that long.
LOCK="$STATE/.schedule.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  t="$(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0)"
  [ $(( $(date +%s) - t )) -ge 600 ] || exit 0
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null || exit 0
  note "removed a stale scheduler lock"
fi
trap 'rm -rf "$LOCK"' EXIT

BLITZ="$(tr -d '[:space:]' < "$WS/BLITZ" 2>/dev/null || echo 0)"
CAP=1
if [ "$BLITZ" = "1" ]; then
  CAP="$(tr -d '[:space:]' < "$WS/MAX_PARALLEL" 2>/dev/null || echo 3)"
  case "$CAP" in ''|*[!0-9]*|0) CAP=3 ;; esac
fi

plan="$(python3 - "$STATE" "$CAP" <<'PY'
import glob, os, re, sys

state, cap = sys.argv[1], int(sys.argv[2])

def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None

def status(tag):
    s = read(os.path.join(state, tag + ".status"))
    return s.splitlines()[0].strip() if s and s.strip() else None

def resolve(tag, seen=()):
    """PENDING until the tag (or the last session it relayed to) has ended."""
    if tag in seen:
        return "PENDING"
    s = status(tag)
    if s is None:
        return "PENDING"
    word = re.split(r"[:\s]", s, maxsplit=1)[0].upper()
    if word == "RELAYED":
        nxt = (s.split(":", 1)[1].split() or [""])[0] if ":" in s else ""
        return resolve(nxt, seen + (tag,)) if nxt else "PENDING"
    if word in ("DONE", "SKIPPED", "BLOCKED"):
        return word
    return "DONE"   # an unrecognised word is still an end; advance.sh reads it the same way

def deps(tag, kind):
    return (read(os.path.join(state, tag + "." + kind)) or "").split()

def natural(tag):
    rank = 0 if re.match(r"T\d", tag) else (1 if tag.startswith("REVIEW-C") else 2)
    return (rank, [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", tag)])

def claimed(tag):
    return os.path.isdir(os.path.join(state, "claim-" + tag))

queued = sorted((os.path.basename(p)[:-len(".queued")]
                 for p in glob.glob(os.path.join(state, "*.queued"))), key=natural)

# A blocked dependency skips its dependents, and theirs, until nothing changes.
changed = True
while changed:
    changed = False
    for tag in queued:
        if status(tag) is not None or claimed(tag):
            continue
        for d in deps(tag, "after"):
            word = resolve(d)
            if word in ("BLOCKED", "SKIPPED"):
                with open(os.path.join(state, tag + ".status"), "w") as fh:
                    fh.write("SKIPPED: blocker %s %s\n" % (d, word))
                with open(os.path.join(state, tag + ".summary"), "w") as fh:
                    fh.write("not started - it depends on %s, which ended %s\n" % (d, word))
                print("SKIP %s blocker %s %s" % (tag, d, word))
                changed = True
                break

writers = 0
for cd in glob.glob(os.path.join(state, "claim-*")):
    tag = os.path.basename(cd)[len("claim-"):]
    if status(tag) is None and not tag.startswith("REVIEW-"):
        writers += 1

for tag in queued:
    if status(tag) is not None or claimed(tag):
        continue
    if any(resolve(d) != "DONE" for d in deps(tag, "after")):
        continue
    if any(resolve(d) == "PENDING" for d in deps(tag, "waits")):
        continue
    if not tag.startswith("REVIEW-"):
        if writers >= cap:
            continue
        writers += 1
    print("LAUNCH %s" % tag)
PY
)" || { note "FAILED to read the queue"; exit 1; }

[ -n "$plan" ] || exit 0

verb="" tag="" rest=""

printf '%s\n' "$plan" | while read -r verb tag rest; do
  case "$verb" in
    SKIP)   note "$tag SKIPPED: ${rest}" ;;
    LAUNCH) note "$tag ready - launching"
            out="$(bash "$WS/launch.sh" "$WS" "$tag" 2>&1)"; rc=$?
            note "$tag launch rc=$rc $(printf '%s' "$out" | tail -1)" ;;
  esac
  printf '%s %s %s\n' "$verb" "$tag" "$rest"
done
exit 0
