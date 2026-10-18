#!/usr/bin/env bash
# night-sprint offline tests for async reviews and blitz mode. No network, no real `claude`.
#
#   bash tests/blitz.sh
#
# The queue (schedule.sh), the trees a tag gets of its own (launch.sh), the relay that must keep
# a continuation in its ticket's tree (advance.sh), the landing lock (land.sh, against real git
# and a bare origin), the render blocks, and the board's view of queued tags.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REF="$HERE/../references"
BIN="$HERE/../../../bin"

pass=0
fail=0
ok() { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
no() { fail=$((fail + 1)); printf '  FAIL %s\n       %s\n' "$1" "$2"; }
check() { [ "$3" = "$2" ] && ok "$1" || no "$1" "want '$2', got '$3'"; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

MBIN="$T/bin"; mkdir -p "$MBIN"
cp "$HERE/mock-claude.sh" "$MBIN/claude"; chmod +x "$MBIN/claude"
export MOCK_STATE="$T/mock"; mkdir -p "$MOCK_STATE"
export PATH="$MBIN:$PATH"

# A sprint repo: a bare origin, and the shared worktree on the sprint branch.
git init -q --bare "$T/origin.git"
git init -q -b main "$T/wt"
( cd "$T/wt" && printf 'base\n' > base.txt && git add . && git commit -q -m base \
  && git remote add origin "$T/origin.git" && git push -q origin main && git checkout -q -b feat/x )

new_ws() {   # new_ws <dir> <BLITZ> [MAX_PARALLEL]
  local ws="$1"
  mkdir -p "$ws/state"
  for f in agents.sh launch.sh advance.sh schedule.sh land.sh render.sh; do cp "$REF/$f" "$ws/"; done
  printf '%s\n' "$T/wt" > "$ws/WORKTREE"
  printf 'feat/x\n'     > "$ws/BRANCH"
  printf 'bz\n'         > "$ws/SLUG"
  printf 'auto\n'       > "$ws/PERMISSION_MODE"
  printf '%s\n' "$2"    > "$ws/BLITZ"
  printf '%s\n' "${3:-3}" > "$ws/MAX_PARALLEL"
}
prompt()  { local ws="$1"; shift; for t in "$@"; do printf 'do %s\n' "$t" > "$ws/prompt-$t.txt"; done; }
queue()   { local ws="$1"; shift; for t in "$@"; do : > "$ws/state/$t.queued"; done; }
launched() { awk '{print $1}' "$MOCK_STATE/launches" 2>/dev/null | sed 's/^ns-bz-//' | sort | tr '\n' ' ' | sed 's/ $//'; }
reset_mock() { : > "$MOCK_STATE/launches"; printf '[]' > "$MOCK_STATE/agents.json"; }

echo "== schedule.sh runs the frontier, up to the writer cap =="
W="$T/ws1"; new_ws "$W" 1 2; reset_mock
prompt "$W" T01 T02 T03 T04 T05 T06 REVIEW-C1 REVIEW-FINAL
queue "$W" T01 T02 T03 T04 T05 T06 REVIEW-C1 REVIEW-FINAL
for t in T01 T02 T03 T04 T05 T06; do : > "$W/state/$t.isolate"; done
: > "$W/state/REVIEW-C1.snapshot"
printf 'T01\n'     > "$W/state/T04.after"
printf 'T04\n'     > "$W/state/T05.after"
printf 'T05\n'     > "$W/state/T06.after"
printf 'T01\n'     > "$W/state/REVIEW-C1.waits"
printf 'T02 REVIEW-C1\n' > "$W/state/REVIEW-FINAL.waits"

bash "$W/schedule.sh" "$W" >/dev/null
check "two writers start, T03 waits for a slot, T04 for its blocker" "T01 T02" "$(launched)"
check "a blitz ticket gets its own tree" "$T/wt-T01" "$(cat "$W/state/T01.cwd" 2>/dev/null)"
check "on its own branch, cut from the sprint branch" "feat/x--T01" \
  "$(git -C "$T/wt-T01" rev-parse --abbrev-ref HEAD 2>/dev/null)"
grep -q " $T/wt-T01\$" "$MOCK_STATE/launches" && ok "the session is launched in that tree" \
  || no "the session is launched in that tree" "$(cat "$MOCK_STATE/launches")"

reset_mock
bash "$W/schedule.sh" "$W" >/dev/null
check "a second pass starts nothing while both slots are taken" "" "$(launched)"

echo DONE > "$W/state/T01.status"
reset_mock
bash "$W/schedule.sh" "$W" >/dev/null
check "T01 done: one free slot goes to T03, oldest first; the finder needs no slot" "REVIEW-C1 T03" "$(launched)"
check "the finder reads a detached snapshot" "HEAD" \
  "$(git -C "$T/wt-REVIEW-C1" rev-parse --abbrev-ref HEAD 2>/dev/null)"

echo "BLOCKED: no API" > "$W/state/T03.status"
reset_mock
bash "$W/schedule.sh" "$W" >/dev/null
check "T03 blocked frees its slot for T04" "T04" "$(launched)"

echo "BLOCKED: schema" > "$W/state/T04.status"
bash "$W/schedule.sh" "$W" >/dev/null
check "a blocked hard dependency skips its dependent" "SKIPPED: blocker T04 BLOCKED" "$(head -1 "$W/state/T05.status" 2>/dev/null)"
check "and the dependent's dependents, all the way down" "SKIPPED: blocker T05 SKIPPED" "$(head -1 "$W/state/T06.status" 2>/dev/null)"

echo "RELAYED: T02c2" > "$W/state/T02.status"
echo DONE > "$W/state/REVIEW-C1.status"
reset_mock
bash "$W/schedule.sh" "$W" >/dev/null
check "a soft wait is not settled while the ticket's continuation runs" "" "$(launched)"
echo DONE > "$W/state/T02c2.status"
bash "$W/schedule.sh" "$W" >/dev/null
check "it settles through the relay, and REVIEW-FINAL starts" "REVIEW-FINAL" "$(launched)"

: > "$W/state/PAUSED"; reset_mock
prompt "$W" T07; queue "$W" T07
bash "$W/schedule.sh" "$W" >/dev/null
check "nothing starts while the sprint is paused" "" "$(launched)"
rm -f "$W/state/PAUSED"

echo
echo "== a serial sprint: the chain owns tickets, finders still run beside them =="
W2="$T/ws2"; new_ws "$W2" 0; reset_mock
prompt "$W2" REVIEW-C1
mkdir "$W2/state/claim-T04"
queue "$W2" REVIEW-C1; printf 'T03\n' > "$W2/state/REVIEW-C1.waits"; echo DONE > "$W2/state/T03.status"
bash "$W2/schedule.sh" "$W2" >/dev/null
check "the checkpoint finder starts while T04 is writing" "REVIEW-C1" "$(launched)"

echo
echo "== advance.sh keeps a continuation in its ticket's tree =="
W3="$T/ws3"; new_ws "$W3" 1; reset_mock
prompt "$W3" T08c2
mkdir -p "$T/wt-T08"
printf '%s\n' "$T/wt-T08" > "$W3/state/T08.cwd"
echo "RELAYED: T08c2" > "$W3/state/T08.status"
bash "$W3/advance.sh" "$W3" T08 >/dev/null 2>&1
check "the relay copies the tree" "$T/wt-T08" "$(cat "$W3/state/T08c2.cwd" 2>/dev/null)"
grep -q "ns-bz-T08c2 .* $T/wt-T08\$" "$MOCK_STATE/launches" && ok "and the continuation starts there" \
  || no "and the continuation starts there" "$(cat "$MOCK_STATE/launches")"

echo
echo "== land.sh: merge under a lock, fix the combined tree, fast-forward, push =="
L="$T/ws4"; new_ws "$L" 1
branch() {   # branch <TAG> <file> <content>: a ticket tree with one commit
  git -C "$T/wt" worktree add -q -b "feat/x--$1" "$T/wt-$1" feat/x
  printf '%s\n' "$T/wt-$1" > "$L/state/$1.cwd"
  ( cd "$T/wt-$1" && printf '%s\n' "$3" > "$2" && git add . && git commit -q -m "$1" )
}
branch L1 a.txt one
branch L2 b.txt two
branch L3 c.txt three
branch L4 c.txt four

out="$(bash "$L/land.sh" "$L" L1 merge 2>&1)"; check "L1 merges" "0" "$?"
out="$(bash "$L/land.sh" "$L" L1 publish 2>&1)"; rc=$?
check "L1 publishes" "0" "$rc"
check "the sprint branch fast-forwarded to L1" "$(git -C "$T/wt-L1" rev-parse HEAD)" "$(git -C "$T/wt" rev-parse HEAD)"
check "and was pushed" "$(git -C "$T/wt" rev-parse HEAD)" "$(git -C "$T/origin.git" rev-parse feat/x 2>/dev/null)"
[ ! -d "$L/state/land.lock" ] && ok "publish releases the lock" || no "publish releases the lock" "lock still held"

out="$(bash "$L/land.sh" "$L" L2 publish 2>&1)"; check "publish without the lock is refused" "4" "$?"
bash "$L/land.sh" "$L" L2 merge >/dev/null 2>&1
bash "$L/land.sh" "$L" L2 publish >/dev/null 2>&1
[ -f "$T/wt/a.txt" ] && [ -f "$T/wt/b.txt" ] && ok "L2 lands on top of L1, both in the tree" \
  || no "L2 lands on top of L1, both in the tree" "$(ls "$T/wt")"

bash "$L/land.sh" "$L" L3 merge >/dev/null 2>&1 && bash "$L/land.sh" "$L" L3 publish >/dev/null 2>&1
out="$(bash "$L/land.sh" "$L" L4 merge 2>&1)"; rc=$?
check "L4 edits L3's line: CONFLICT" "3" "$rc"
case "$out" in *c.txt*) ok "it names the file" ;; *) no "it names the file" "$out" ;; esac
check "L4 keeps the lock while it resolves" "L4" "$(cat "$L/state/land.lock/owner" 2>/dev/null)"

branch L5 d.txt five
out="$(LAND_WAIT=1 bash "$L/land.sh" "$L" L5 merge 2>&1)"; check "another ticket waits: BUSY" "75" "$?"

( cd "$T/wt-L4" && printf 'three\nfour\n' > c.txt && git add c.txt && git commit -q --no-edit )
printf '%s\n' "$T/wt-L4" > "$L/state/L4c2.cwd"
out="$(bash "$L/land.sh" "$L" L4c2 publish 2>&1)"; rc=$?
check "its continuation publishes under the same ticket's lock" "0" "$rc"
check "the resolution is what landed" "three four" "$(tr '\n' ' ' < "$T/wt/c.txt" | sed 's/ $//')"

mkdir "$L/state/land.lock"; printf 'L9\n' > "$L/state/land.lock/owner"; echo DONE > "$L/state/L9.status"
out="$(bash "$L/land.sh" "$L" L5 merge 2>&1)"; check "a lock whose owner has ended is taken over" "0" "$?"
grep -q 'took over a stale landing lock' "$L/state/EVENTS.log" && ok "and the takeover is logged" \
  || no "and the takeover is logged" "no EVENTS.log line"
out="$(bash "$L/land.sh" "$L" L5 abort 2>&1)"; check "abort releases it" "" "$(cat "$L/state/land.lock/owner" 2>/dev/null)"

echo
echo "== render.sh resolves the mode blocks, and bootstrap resolves every template once =="
R="$T/r"; mkdir -p "$R"
printf 'A\n{{#BLITZ}}\nblitz\n{{/BLITZ}}\n{{^BLITZ}}\nserial\n{{/BLITZ}}\nZ\n' > "$R/t.md"
printf 'BLITZ=1\n' > "$R/facts.env"
bash "$REF/render.sh" "$R" "$R/t.md" "$R/o1" >/dev/null
check "BLITZ=1 keeps the blitz block only" "A blitz Z" "$(tr '\n' ' ' < "$R/o1" | sed 's/ $//')"
printf 'BLITZ=0\n' > "$R/facts.env"
bash "$REF/render.sh" "$R" "$R/t.md" "$R/o0" >/dev/null
check "BLITZ=0 keeps the serial block only" "A serial Z" "$(tr '\n' ' ' < "$R/o0" | sed 's/ $//')"
printf '{{#BLITZ}}\nopen\n' > "$R/bad.md"
bash "$REF/render.sh" "$R" "$R/bad.md" "$R/o2" >/dev/null 2>&1
check "an unclosed block is refused" "2" "$?"

B="$T/boot"; mkdir -p "$B"
cat > "$B/facts.env" <<ENV
REPO=r
REPO_PATH=$T/wt
REPO_SLUG=o/r
SLUG=bz
USER=u
WS=$B
WORKTREE=$T/wt
BRANCH=feat/x
BASE=main
TOOLCHAIN=none
VERIFY=true
FORMAT_CHECK=true
BLITZ=1
MAX_PARALLEL=4
ENV
out="$(bash "$REF/bootstrap.sh" "$B" "$REF" 2>&1)"; check "bootstrap succeeds in blitz" "0" "$?"
check "MAX_PARALLEL derived" "4" "$(cat "$B/MAX_PARALLEL" 2>/dev/null)"
[ -x "$B/schedule.sh" ] && [ -x "$B/land.sh" ] && ok "schedule.sh and land.sh copied" \
  || no "schedule.sh and land.sh copied" "missing"
left="$(grep -l '{{' "$B"/*.md 2>/dev/null | tr '\n' ' ')"
[ -z "$left" ] && ok "no workspace template keeps a block marker" || no "no workspace template keeps a block marker" "$left"
grep -q 'land.sh <WS> <CONT_TAG> merge' "$B/continuation-prompt.md" \
  && ok "the hand-filled continuation template already says how to land" \
  || no "the hand-filled continuation template already says how to land" "no land.sh step"
grep -q 'cd <WORKTREE>$' "$B/implementer-prompt.md" \
  && no "a blitz implementer never works in the shared tree" "serial WORK HERE survived" \
  || ok "a blitz implementer never works in the shared tree"

B0="$T/boot0"; mkdir -p "$B0"; grep -v '^BLITZ=\|^MAX_PARALLEL=' "$B/facts.env" | sed "s#=$B\$#=$B0#" > "$B0/facts.env"
bash "$REF/bootstrap.sh" "$B0" "$REF" >/dev/null 2>&1
check "BLITZ defaults to off" "0" "$(cat "$B0/BLITZ" 2>/dev/null)"
grep -q 'land.sh' "$B0/implementer-prompt.md" && no "a serial implementer never lands" "land.sh in a serial prompt" \
  || ok "a serial implementer never lands"

echo
echo "== night-watch draws queued tags as heads =="
S="$T/board/state"; mkdir -p "$S"
for t in T02 T01 REVIEW-C1 REVIEW-FINAL; do : > "$S/$t.queued"; done
printf 'FIX-FINAL\n' > "$S/REVIEW-FINAL.next"
printf 'T01c2\n' > "$S/T01.next"; echo "RELAYED: T01c2" > "$S/T01.status"
got="$(PYTHONDONTWRITEBYTECODE=1 python3 - "$BIN/night-watch" "$S" <<'PY'
import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("nw", sys.argv[1])
spec = importlib.util.spec_from_loader("nw", loader)
nw = importlib.util.module_from_spec(spec); loader.exec_module(nw)
print(" ".join(nw.walk_chain(sys.argv[2])))
PY
)"
check "tickets, then checkpoints, then the final chain" "T01 T01c2 T02 REVIEW-C1 REVIEW-FINAL FIX-FINAL" "$got"

echo
echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
