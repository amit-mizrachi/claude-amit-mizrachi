#!/usr/bin/env bash
# night-sprint offline tests for multi-repo sprints. No network, no real `claude` or `gh`.
#
#   bash tests/multi-repo.sh
#
# One feature across several repos, one branch and one PR per repo (multi-repo.md). Covered:
# bootstrap's per-repo facts and its refusals, repos.sh resolving a tag's repo (continuations
# included), launch.sh running a tag in its repo's tree and cutting trees from its repo's branch,
# land.sh landing on the right branch under a per-repo lock, accept.sh writing a per-repo
# verdict, the runner asking for one PR per repo, and single-repo workspaces left unchanged.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REF="$HERE/../references"

pass=0
fail=0
ok() { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
no() { fail=$((fail + 1)); printf '  FAIL %s\n       %s\n' "$1" "$2"; }
check() { [ "$3" = "$2" ] && ok "$1" || no "$1" "want '$2', got '$3'"; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export CLAUDE_CONFIG_DIR="$T/claude-config"; mkdir -p "$CLAUDE_CONFIG_DIR"

MBIN="$T/bin"; mkdir -p "$MBIN"
cp "$HERE/mock-claude.sh" "$MBIN/claude"; chmod +x "$MBIN/claude"
export MOCK_STATE="$T/mock"; mkdir -p "$MOCK_STATE"
# A stand-in for `gh`: one PR (#7) per branch unless $GH_STATE/no-pr exists, its head is the
# checkout's HEAD, and its required checks pass. Every call is logged with its cwd.
export GH_STATE="$T/gh"; mkdir -p "$GH_STATE"
cat > "$MBIN/gh" <<'GH'
#!/usr/bin/env bash
printf '%s | %s\n' "$PWD" "$*" >> "$GH_STATE/calls"
case "$*" in
  "pr view 7 --json headRefOid"*) git rev-parse HEAD ;;
  "pr view "*"--json number"*) [ -f "$GH_STATE/no-pr" ] && exit 1; echo 7 ;;
  "pr checks 7 --required") echo "lint pass"; exit 0 ;;
  *) exit 0 ;;
esac
GH
chmod +x "$MBIN/gh"
export PATH="$MBIN:$PATH"
reset_mock() { : > "$MOCK_STATE/launches"; printf '[]' > "$MOCK_STATE/agents.json"; }

# Two repos, each with a bare origin and a sprint worktree on feat/x.
for r in alpha beta; do
  git init -q --bare "$T/$r-origin.git"
  git init -q -b main "$T/$r-wt"
  ( cd "$T/$r-wt" && printf '%s\n' "$r" > base.txt && git add . && git commit -q -m "$r base" \
    && git remote add origin "$T/$r-origin.git" && git push -q origin main && git checkout -q -b feat/x )
done

repo_env() {   # repo_env <ws> <key>
  mkdir -p "$1/repos"
  cat > "$1/repos/$2.env" <<ENV
REPO=$2
REPO_PATH=$T/$2-wt
REPO_SLUG=o/$2
WORKTREE=$T/$2-wt
BRANCH=feat/x
BASE=main
TOOLCHAIN=none
VERIFY=make test-$2
FORMAT_CHECK=make fmt-$2
ENV
}
multi_ws() {   # multi_ws <ws> [BLITZ]
  mkdir -p "$1"
  cat > "$1/facts.env" <<ENV
MULTI_REPO=1
REPOS=alpha beta
SLUG=mr
USER=u
WS=$1
CONTEXT_WINDOW=200000
WARN_AT_USED=20
RELAY_AT_USED=30
CEILING_USED=60
BLITZ=${2:-0}
ENV
  repo_env "$1" alpha; repo_env "$1" beta
}

echo "== bootstrap.sh reads one facts file per repo =="
W="$T/ws1"; multi_ws "$W"
out="$(bash "$REF/bootstrap.sh" "$W" "$REF" 2>&1)"; check "a multi-repo workspace bootstraps" "0" "$?"
check "the repo keys derived" "alpha beta" "$(cat "$W/REPO_KEYS" 2>/dev/null)"
check "each repo's worktree derived" "$T/beta-wt" "$(cat "$W/repos/beta/WORKTREE" 2>/dev/null)"
check "each repo's verify derived whole" "make test-beta" "$(cat "$W/repos/beta/VERIFY" 2>/dev/null)"
check "the sprint's own worktree is the first repo's" "$T/alpha-wt" "$(cat "$W/WORKTREE" 2>/dev/null)"
grep -q '^REPO_KEY=beta$' "$W/repos/beta.env" && ok "REPO_KEY appended to the repo file for the templates" \
  || no "REPO_KEY appended to the repo file for the templates" "$(cat "$W/repos/beta.env")"
grep -q "| beta | o/beta | $T/beta-wt | feat/x | main |" "$W/REPOS.md" 2>/dev/null \
  && ok "REPOS.md lists every repo's tree" || no "REPOS.md lists every repo's tree" "$(cat "$W/REPOS.md" 2>/dev/null)"
[ -f "$W/repos.sh" ] && ok "repos.sh copied" || no "repos.sh copied" "absent"
grep -q 'SPANS SEVERAL REPOS' "$W/implementer-prompt.md" && ok "the multi-repo blocks are kept" \
  || no "the multi-repo blocks are kept" "no multi-repo text in the implementer template"
left="$(grep -l '{{' "$W"/*.md 2>/dev/null | tr '\n' ' ')"
[ -z "$left" ] && ok "no block marker survives" || no "no block marker survives" "$left"

# Rendered with the repo file first, a ticket prompt names that repo and leaves nothing unfilled.
printf 'TAG=T02\nNN=02\nTICKET_TITLE=t\nGOTCHAS=none\nNEXT_TAG=T03\nCONVENTIONS=AGENTS.md\nTOTAL=3\n' > "$W/vars-T02.env"
bash "$W/render.sh" "$W" "$W/implementer-prompt.md" "$W/prompt-T02.txt" "$W/repos/beta.env" "$W/vars-T02.env" >/dev/null 2>&1
check "a ticket prompt renders from its repo file" "0" "$?"
grep -q "cd $T/beta-wt\$" "$W/prompt-T02.txt" && ok "and works in that repo's tree" \
  || no "and works in that repo's tree" "$(grep -n 'cd ' "$W/prompt-T02.txt")"
grep -q 'yours is beta (o/beta)' "$W/prompt-T02.txt" && ok "and names its repo" || no "and names its repo" "no key"
printf 'TAG=CI-beta\nNEXT_TAG=\n' > "$W/vars-CI-beta.env"
bash "$W/render.sh" "$W" "$W/ci-prompt.md" "$W/prompt-CI-beta.txt" "$W/repos/beta.env" "$W/vars-CI-beta.env" >/dev/null 2>&1
grep -q 'accept.sh .* 540 "" beta$' "$W/prompt-CI-beta.txt" && ok "a repo's CI ticket checks its own repo's PR" \
  || no "a repo's CI ticket checks its own repo's PR" "$(grep -n accept.sh "$W/prompt-CI-beta.txt")"

echo "== bootstrap.sh refuses a half-described multi-repo sprint =="
refuse() {   # refuse <name> <word in the error> <edit command run in the ws>
  local ws="$T/refuse-$RANDOM"; multi_ws "$ws"
  ( cd "$ws" && eval "$3" )
  out="$(bash "$REF/bootstrap.sh" "$ws" "$REF" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ] && [[ "$out" == *"$2"* ]]; then ok "$1"; else no "$1" "rc=$rc: $out"; fi
}
refuse "a per-repo fact in facts.env" "belong in repos" "echo WORKTREE=/x >> facts.env"
refuse "a missing repo file" "no $T" "sed -i.bak 's/^REPOS=.*/REPOS=alpha beta gamma/' facts.env"
refuse "a repo file missing a fact" "FORMAT_CHECK" "sed -i.bak '/^FORMAT_CHECK=/d' repos/beta.env"
refuse "two repos named but MULTI_REPO unset" "set MULTI_REPO=1" "sed -i.bak '/^MULTI_REPO=/d' facts.env"
refuse "MULTI_REPO with one repo" "at least two" "sed -i.bak 's/^REPOS=.*/REPOS=alpha/' facts.env"
refuse "a key with a hyphen" "letters and digits" "sed -i.bak 's/^REPOS=.*/REPOS=alpha be-ta/' facts.env; cp repos/beta.env repos/be-ta.env"
refuse "two repos in one worktree" "share a worktree" "sed -i.bak 's#^WORKTREE=.*#WORKTREE=$T/alpha-wt#' repos/beta.env"
refuse "multi-repo research" "research" "echo MODE=research >> facts.env"

echo "== a single-repo workspace is unchanged =="
S="$T/single"; mkdir -p "$S"
cat > "$S/facts.env" <<ENV
REPO=r
REPO_PATH=$T/alpha-wt
REPO_SLUG=o/r
SLUG=sr
USER=u
WS=$S
WORKTREE=$T/alpha-wt
BRANCH=feat/x
BASE=main
TOOLCHAIN=none
VERIFY=true
FORMAT_CHECK=true
ENV
bash "$REF/bootstrap.sh" "$S" "$REF" >/dev/null 2>&1; check "a single-repo workspace bootstraps" "0" "$?"
[ ! -e "$S/REPO_KEYS" ] && [ ! -e "$S/REPOS.md" ] && [ ! -e "$S/repos" ] && ok "no repo files appear" \
  || no "no repo files appear" "$(ls "$S")"
hits="$(grep -l 'SEVERAL REPOS\|REPOS.md\|REPO_KEY' "$S"/*.md 2>/dev/null | tr '\n' ' ')"
[ -z "$hits" ] && ok "no template keeps multi-repo text" || no "no template keeps multi-repo text" "$hits"

echo "== repos.sh: a tag's repo, and a continuation's =="
R="$T/ws-r"; mkdir -p "$R/state"; cp "$REF/repos.sh" "$R/"
echo beta > "$R/state/T03.repo"; echo alpha > "$R/state/CI-alpha.repo"
ro() { ( . "$R/repos.sh"; repo_of "$R" "$1" ); }
check "a tag reads its own .repo" "beta" "$(ro T03)"
check "a continuation inherits its ticket's" "beta" "$(ro T03c2)"
check "and a continuation of a continuation" "beta" "$(ro T03c2c3)"
check "a tag with no repo prints nothing" "" "$(ro TEST)"
check "a key that ends in c<n> is read whole" "alpha" "$(ro CI-alpha)"
check "repo_fact without a key reads the sprint's file" "$T/alpha-wt" \
  "$( cd "$S" && . "$S/repos.sh"; repo_fact "$S" "" WORKTREE )"

echo "== launch.sh runs a tag in its repo, and cuts its trees from its repo's branch =="
W="$T/ws2"; multi_ws "$W" 1; bash "$REF/bootstrap.sh" "$W" "$REF" >/dev/null 2>&1; reset_mock
for t in T01 T02 REVIEW-C1-beta; do printf 'do %s\n' "$t" > "$W/prompt-$t.txt"; done
echo alpha > "$W/state/T01.repo"
echo beta > "$W/state/T02.repo"; : > "$W/state/T02.isolate"
echo beta > "$W/state/REVIEW-C1-beta.repo"; : > "$W/state/REVIEW-C1-beta.snapshot"
bash "$W/launch.sh" "$W" T01 >/dev/null 2>&1
grep -q "^ns-mr-T01 .* $T/alpha-wt\$" "$MOCK_STATE/launches" && ok "a serial ticket runs in its repo's tree" \
  || no "a serial ticket runs in its repo's tree" "$(cat "$MOCK_STATE/launches")"
bash "$W/launch.sh" "$W" T02 >/dev/null 2>&1
check "a blitz ticket's tree sits beside its repo's" "$T/beta-wt-T02" "$(cat "$W/state/T02.cwd" 2>/dev/null)"
check "on a branch cut from its repo's sprint branch" "feat/x--T02" \
  "$(git -C "$T/beta-wt-T02" rev-parse --abbrev-ref HEAD 2>/dev/null)"
check "holding that repo's history" "beta" "$(cat "$T/beta-wt-T02/base.txt" 2>/dev/null)"
( cd "$T/beta-wt" && echo more > more.txt && git add more.txt && git commit -q -m more )
bash "$W/launch.sh" "$W" REVIEW-C1-beta >/dev/null 2>&1
check "a repo's checkpoint reads a snapshot of that repo" "$(git -C "$T/beta-wt" rev-parse HEAD)" \
  "$(git -C "$T/beta-wt-REVIEW-C1-beta" rev-parse HEAD 2>/dev/null)"

echo "== land.sh lands on the ticket's repo, under that repo's lock =="
( cd "$T/beta-wt-T02" && echo t02 > t02.txt && git add t02.txt && git commit -q -m t02 )
echo "RELAYED: T02c2" > "$W/state/T02.status"
bash "$W/advance.sh" "$W" T02 >/dev/null 2>&1
check "the continuation keeps its ticket's tree" "$T/beta-wt-T02" "$(cat "$W/state/T02c2.cwd" 2>/dev/null)"
mkdir "$W/state/land-alpha.lock"; echo T09 > "$W/state/land-alpha.lock/owner"   # alpha is busy landing
out="$(LAND_WAIT=0 bash "$W/land.sh" "$W" T02c2 merge 2>&1)"; check "beta lands while alpha holds its own lock" "0" "$?"
[ -f "$W/state/land-beta.lock/owner" ] && [ ! -e "$W/state/land.lock" ] && ok "the lock taken is beta's" \
  || no "the lock taken is beta's" "$(ls "$W/state")"
out="$(bash "$W/land.sh" "$W" T02c2 publish 2>&1)"; check "publish fast-forwards" "0" "$?"
check "beta's sprint branch now holds the ticket" "t02" "$(git -C "$T/beta-wt" show feat/x:t02.txt 2>/dev/null)"
check "and beta's origin has it" "t02" "$(git -C "$T/beta-origin.git" show feat/x:t02.txt 2>/dev/null)"
git -C "$T/alpha-wt" show feat/x:t02.txt >/dev/null 2>&1 && no "alpha is untouched" "t02.txt reached alpha" \
  || ok "alpha is untouched"

echo "== accept.sh checks a repo's own PR and writes that repo's verdict =="
git -C "$T/beta-wt" push -q origin feat/x 2>/dev/null
: > "$GH_STATE/calls"
out="$(bash "$W/accept.sh" "$W" 5 "" beta 2>&1)"; check "beta is green" "0" "$?"
case "$(cat "$W/state/ACCEPTANCE-beta.verdict" 2>/dev/null)" in
  "PASS $(git -C "$T/beta-wt" rev-parse HEAD) "*) ok "the verdict is beta's file, at beta's head" ;;
  *) no "the verdict is beta's file, at beta's head" "$(cat "$W/state/ACCEPTANCE-beta.verdict" 2>/dev/null)" ;;
esac
[ ! -e "$W/state/ACCEPTANCE.verdict" ] && ok "the shared verdict file is not written" \
  || no "the shared verdict file is not written" "ACCEPTANCE.verdict exists"
grep -q "^$T/beta-wt | pr view feat/x --json number" "$GH_STATE/calls" && ok "asked from beta's tree, by branch name" \
  || no "asked from beta's tree, by branch name" "$(cat "$GH_STATE/calls")"

echo "== the runner asks for one draft PR per repo =="
W="$T/ws3"; multi_ws "$W"; bash "$REF/bootstrap.sh" "$W" "$REF" >/dev/null 2>&1; reset_mock
: > "$GH_STATE/no-pr"
sweep() { (cd "$T" && HOME="$T/home" bash "$W/watch.sh" "$W" 0 25 --once 2>/dev/null); }
mkdir -p "$T/home/.claude/projects"
for t in T01 T02; do
  printf '%s\n' "aaaaaaaa-0000-4000-8000-00000000000${t#T0}" > "$W/state/$t.session"
  : > "$W/state/.advanced-$t"; : > "$W/state/.closed-$t"
done
echo alpha > "$W/state/T01.repo"; echo beta > "$W/state/T02.repo"
echo DONE > "$W/state/T01.status"
out="$(sweep)"
case "$out" in *"NEEDS-PR alpha "*) ok "alpha's first landing asks for alpha's PR" ;;
  *) no "alpha's first landing asks for alpha's PR" "$out" ;; esac
case "$out" in *"NEEDS-PR beta"*) no "beta is not asked before it lands" "$out" ;;
  *) ok "beta is not asked before it lands" ;; esac
out="$(sweep)"
case "$out" in *NEEDS-PR*) no "each repo is asked once" "$out" ;; *) ok "each repo is asked once" ;; esac
echo "RELAYED: T02c2" > "$W/state/T02.status"; echo DONE > "$W/state/T02c2.status"
printf 'aaaaaaaa-0000-4000-8000-000000000009\n' > "$W/state/T02c2.session"
: > "$W/state/.advanced-T02c2"; : > "$W/state/.closed-T02c2"
out="$(sweep)"
case "$out" in *"NEEDS-PR beta "*) ok "a continuation's landing counts for its ticket's repo" ;;
  *) no "a continuation's landing counts for its ticket's repo" "$out" ;; esac
[ ! -e "$W/state/.pr-asked" ] && ok "the single-repo ask is never raised" || no "the single-repo ask is never raised" ".pr-asked exists"

echo
echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
