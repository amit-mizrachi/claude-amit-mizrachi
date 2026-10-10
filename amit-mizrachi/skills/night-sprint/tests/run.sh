#!/usr/bin/env bash
# night-sprint offline tests. No network, no `claude`, no live sprint.
#
#   bash tests/run.sh
#
# Every case here was a real night that went wrong. The two the audit of 2026-09-19 named
# are the reason the file exists:
#   - a spending cap classified as a generic api-error, so the reviver spent its whole
#     ladder against a wall and the log recorded a two-hour outage as a permission stall;
#   - `revive.sh` referencing an undefined variable on its "still working" path, which
#     under `set -u` turned the one guard against two agents in one worktree into a crash.
# Both are asserted below. A guard nobody can test offline is a guard that rots.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REF="$HERE/../references"
FIX="$HERE/fixtures"

pass=0
fail=0

ok() { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
no() { fail=$((fail + 1)); printf '  FAIL %s\n       %s\n' "$1" "$2"; }

check() {
  local name="$1" want="$2" got="$3"
  [ "$got" = "$want" ] && ok "$name" || no "$name" "want '$want', got '$got'"
}

echo "== every reference script parses =="
for f in "$REF"/*.sh; do
  if out="$(bash -n "$f" 2>&1)"; then ok "bash -n $(basename "$f")"
  else no "bash -n $(basename "$f")" "$out"; fi
done

echo
echo "== classify-error.sh names the class, not just 'an error' =="
c() { bash "$REF/classify-error.sh" "$FIX/$1"; }
check "org spend cap"                 "quota-spend"                 "$(c spend-limit.jsonl)"
check "logged out"                    "auth logged-out"             "$(c logged-out.jsonl)"
check "subscription disabled"         "auth subscription-disabled"  "$(c subscription-disabled.jsonl)"
check "dropped connection"            "transient connection-closed" "$(c connection-closed.jsonl)"
# The exact line that killed the shapes-platform build conductor on 2026-10-02.
check "lost connection"               "transient connection-lost"   "$(c connection-lost.jsonl)"
check "529 overloaded"                "transient overloaded"        "$(c overloaded.jsonl)"
check "no error at all"               "none"                        "$(c clean.jsonl)"
# The REVIEW-01 shape. Reporting the old error here would send the reviver after a session
# that is alive and working, which is precisely how two agents end up in one worktree.
check "hit the cap, then carried on"  "none"                        "$(c spend-limit-recovered.jsonl)"
# A subagent hitting the cap is not the parent dying of it.
check "sidechain error ignored"       "none"                        "$(c sidechain-only.jsonl)"

got="$(c session-limit.jsonl)"
case "$got" in
  "quota-session "*)
    epoch="${got#quota-session }"
    # 4:20pm Asia/Jerusalem, resolved against the error's own timestamp (10:00Z, so 13:00
    # local) - the next 16:20 local is the same afternoon, not tomorrow.
    local_hm="$(TZ=Asia/Jerusalem date -r "$epoch" +%H:%M 2>/dev/null \
             || TZ=Asia/Jerusalem date -d "@$epoch" +%H:%M 2>/dev/null)"
    check "session limit resolves its reset clock" "16:20" "$local_hm"
    ;;
  *) no "session limit resolves its reset clock" "want 'quota-session <epoch>', got '$got'" ;;
esac

got="$(c session-limit-no-tz.jsonl)"
case "$got" in
  "quota-session "*) ok "session limit without a timezone still classifies" ;;
  *) no "session limit without a timezone still classifies" "got '$got'" ;;
esac

echo
echo "== no script reads a variable nothing defines (set -u) =="
# The regression: that branch printed ${ACTIVE_WITHIN_MIN}, a name defined nowhere. Under
# `set -u` it aborted instead of refusing, so the one check standing between the sprint and
# two agents in one worktree failed open. Assert every name on the path is defined.
for script in "$REF"/*.sh; do
  undef="$(python3 - "$script" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
# Anything that is assigned anywhere, or declared local, counts as defined. Deliberately
# generous: the bug this guards against is a name that appears ONLY inside ${...}, which no
# amount of generosity can hide.
defined = set(re.findall(r'(?<![$\w{])([A-Za-z_][A-Za-z0-9_]*)=', src))
defined |= {w for line in re.findall(r'\blocal\s+([^=\n]+)', src) for w in line.split()}
defined |= {w for line in re.findall(r'\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b', src) for w in line.split()}
env = {"HOME", "TMPDIR", "PATH", "USER", "SHELL", "PWD", "RANDOM", "TZ", "CLAUDE_CODE_SESSION_ID"}
used = set(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)[:}\[]', src))
print(" ".join(sorted(used - defined - env)))
PY
)"
  name="$(basename "$script")"
  if [ -z "$undef" ]; then ok "no undefined \${...} names in $name"
  else no "no undefined \${...} names in $name" "undefined: $undef"; fi
done

echo
echo "== no 'local a=\$1 b=\$a' - the second assignment does not see the first =="
# This bit the revive cooldown in watch.sh: `local tag="$1" f="$STATE/.acted-$tag"` built a path
# with no tag in it, so the guard against reviving the same tag twice a minute never fired once.
# It is invisible at a glance and silent at runtime, which is exactly why it gets a test.
for script in "$REF"/*.sh; do
  hits="$(python3 - "$script" <<'PY'
import re, sys
# chr(36) rather than a literal dollar sign: bash 3.2 scans for quotes inside a heredoc that
# sits in a command substitution, and a dollar next to a double quote derails its parser.
D = chr(36)

def refers_to(value, name):
    # Match $name and ${name}, but not $namely - a shorter name must not flag a longer one.
    return re.search(re.escape(D) + r'\{?' + re.escape(name) + r'\}?(?![A-Za-z0-9_])', value)

bad = []
for n, line in enumerate(open(sys.argv[1]), 1):
    m = re.search(r'(?:^|[;{]|\bthen\b|\bdo\b)\s*local\s+([^\n;]*)', line)
    if not m:
        continue
    seen = []
    for part in m.group(1).split():
        name, eq, value = part.partition("=")
        if eq and any(refers_to(value, s) for s in seen):
            bad.append(str(n))
            break
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            seen.append(name)
print(" ".join(bad))
PY
)"
  name="$(basename "$script")"
  if [ -z "$hits" ]; then ok "no self-referencing single \`local\` in $name"
  else no "no self-referencing single \`local\` in $name" "lines: $hits"; fi
done

echo
echo "== advance.sh is the single transition owner =="
WS="$(mktemp -d)"
trap 'rm -rf "$WS"' EXIT
mkdir -p "$WS/state"
printf '%s\n' "$WS/wt" > "$WS/WORKTREE"
printf 'testslug\n' > "$WS/SLUG"
printf 'auto\n' > "$WS/PERMISSION_MODE"
cp "$REF/advance.sh" "$WS/"
# A fake launcher, so the test can observe exactly which tag advance.sh tried to start
# without a `claude` on the box. It keeps the one behaviour that matters: the atomic claim,
# so a second advance for the same tag is a no-op here exactly as it is in the real script.
cat > "$WS/launch.sh" <<'FAKE'
#!/usr/bin/env bash
mkdir "$1/state/claim-$2" 2>/dev/null || exit 0
printf '%s\n' "$2" >> "$1/state/.launched"
FAKE

run_advance() { bash "$WS/advance.sh" "$WS" "$1" >/dev/null 2>&1; echo "$?"; }
launched() { tr '\n' ' ' < "$WS/state/.launched" 2>/dev/null | sed 's/ $//'; }

: > "$WS/state/.launched"
printf 'T02\n' > "$WS/state/T01.next"
rc="$(run_advance T01)"
check "no status yet: launches nothing" "" "$(launched)"
check "no status yet: exits 3"          "3" "$rc"

printf 'DONE\n' > "$WS/state/T01.status"
run_advance T01 >/dev/null
check "DONE launches the wired successor" "T02" "$(launched)"

# Called again - by the watcher this time, after the session already called it. The claim
# inside launch.sh is what makes the second call harmless, so T02 must appear exactly once.
run_advance T01 >/dev/null
check "advancing twice starts the successor exactly once" "T02" "$(launched)"

: > "$WS/state/.launched"
printf 'T04\n' > "$WS/state/T03.next"
printf 'RELAYED: T03c2\n' > "$WS/state/T03.status"
run_advance T03 >/dev/null
# The bug that put two agents on one ticket: RELAYED read as DONE, so the sprint launched
# T04 on top of half of T03. The continuation tag wins over the wired successor, always.
check "RELAYED launches the continuation, never the next ticket" "T03c2" "$(launched)"

: > "$WS/state/.launched"
printf 'T06\n' > "$WS/state/T05.next"
printf 'BLOCKED: missing credential\n' > "$WS/state/T05.status"
rc="$(run_advance T05)"
check "BLOCKED launches nothing" "" "$(launched)"
check "BLOCKED exits 2 so the conductor decides" "2" "$rc"

: > "$WS/state/.launched"
printf 'SKIPPED: nothing to address\n' > "$WS/state/FIX-C1.status"
printf 'T07\n' > "$WS/state/FIX-C1.next"
run_advance FIX-C1 >/dev/null
check "a skipped stage still advances the chain" "T07" "$(launched)"

: > "$WS/state/.launched"
printf 'DONE\n' > "$WS/state/TEST.status"
: > "$WS/state/TEST.next"
rc="$(run_advance TEST)"
check "an empty successor ends the sprint quietly" "" "$(launched)"
check "end of chain exits 0"                       "0" "$rc"

: > "$WS/state/.launched"
printf 'DONE\n' > "$WS/state/T08.status"
printf 'T09\n' > "$WS/state/T08.next"
: > "$WS/state/PAUSED"
rc="$(run_advance T08)"
# Quota is the one state where launching more work is actively harmful: every new session
# burns a request against a cap that is already refusing them.
check "PAUSED blocks the launch" "" "$(launched)"
check "PAUSED exits 4"           "4" "$rc"
rm -f "$WS/state/PAUSED"

echo
echo "== render.sh fills every slot, or refuses =="
RWS="$(mktemp -d)"
cat > "$RWS/facts.env" <<'ENV'
# comments and blank lines are ignored
REPO=shapes-platform
VERIFY=pnpm nx affected -t typecheck test lint
WS=/tmp/ws
TAG=T01
TAG_SUFFIX=should-not-be-used
ENV
printf 'Repo <REPO>, check with `<VERIFY>`, tag <TAG>, ws <WS>.\n' > "$RWS/t.md"
out="$(bash "$REF/render.sh" "$RWS" "$RWS/t.md" "$RWS/out.txt" 2>&1)"; rc=$?
check "a fully filled template renders, exit 0" "0" "$rc"
check "every slot substituted" \
  'Repo shapes-platform, check with `pnpm nx affected -t typecheck test lint`, tag T01, ws /tmp/ws.' \
  "$(cat "$RWS/out.txt")"

# Longest-key-first matters: <TAG> must not eat the front of <TAG_SUFFIX>.
printf '<TAG_SUFFIX>\n' > "$RWS/t2.md"
bash "$REF/render.sh" "$RWS" "$RWS/t2.md" "$RWS/out2.txt" >/dev/null 2>&1
check "a longer key is not eaten by a shorter prefix" "should-not-be-used" "$(cat "$RWS/out2.txt")"

# The check at the end is the point. An unfilled <VERIFY> is a session that wakes at 3am not
# knowing how to check its own work, and it must not be allowed to reach that session.
printf 'Build <TICKET_TITLE> and verify with <NOT_A_FACT>.\n' > "$RWS/bad.md"
out="$(bash "$REF/render.sh" "$RWS" "$RWS/bad.md" "$RWS/bad.txt" 2>&1)"; rc=$?
check "an unfilled slot fails the render" "2" "$rc"
case "$out" in
  *NOT_A_FACT*TICKET_TITLE*|*TICKET_TITLE*NOT_A_FACT*) ok "it names every unfilled slot" ;;
  *) no "it names every unfilled slot" "got: $out" ;;
esac

# Lower-case angle brackets are prose addressed to the session, not slots.
printf 'Reply with <what is wrong> at <file>:<line>.\n' > "$RWS/prose.md"
bash "$REF/render.sh" "$RWS" "$RWS/prose.md" "$RWS/prose.txt" >/dev/null 2>&1
check "prose placeholders are left alone" "Reply with <what is wrong> at <file>:<line>." \
  "$(cat "$RWS/prose.txt")"

echo
echo "== every template's slots are fillable from the documented fact set =="
# A slot in a template that bootstrap.sh does not require and no per-tag vars file supplies is
# a slot that reaches a session unfilled. Assert the two sets line up.
python3 - "$REF" <<'PY'
import glob, os, re, sys
ref = sys.argv[1]
facts = set(re.findall(r'"([A-Z][A-Z0-9_]*)"', open(os.path.join(ref, "bootstrap.sh")).read()))
per_tag = {"TAG", "NN", "TICKET_TITLE", "GOTCHAS", "NEXT_TAG", "TOTAL", "CONVENTIONS",
           "SCOPE", "REVIEW_LANES", "CHECKPOINT", "FIX_TAG", "FIND_TAG", "IMPL_TAG",
           "NEXT_AFTER_FIX", "FIND_FINAL_TAG", "PR", "CONT_TAG", "PREV_TAG", "SCRIPT_PATH",
           "FEATURE_TITLE"}
bad = {}
for f in sorted(glob.glob(os.path.join(ref, "*prompt*.md"))):
    slots = set(re.findall(r'<([A-Z][A-Z0-9_]*)>', open(f).read()))
    unknown = slots - facts - per_tag
    if unknown:
        bad[os.path.basename(f)] = sorted(unknown)
for k, v in bad.items():
    print("%s: %s" % (k, " ".join(v)))
PY
unknown="$(python3 - "$REF" <<'PY'
import glob, os, re, sys
ref = sys.argv[1]
facts = set(re.findall(r'"([A-Z][A-Z0-9_]*)"', open(os.path.join(ref, "bootstrap.sh")).read()))
per_tag = {"TAG", "NN", "TICKET_TITLE", "GOTCHAS", "NEXT_TAG", "TOTAL", "CONVENTIONS",
           "SCOPE", "REVIEW_LANES", "CHECKPOINT", "FIX_TAG", "FIND_TAG", "IMPL_TAG",
           "NEXT_AFTER_FIX", "FIND_FINAL_TAG", "PR", "CONT_TAG", "PREV_TAG", "SCRIPT_PATH",
           "FEATURE_TITLE"}
out = set()
for f in glob.glob(os.path.join(ref, "*prompt*.md")):
    out |= set(re.findall(r'<([A-Z][A-Z0-9_]*)>', open(f).read())) - facts - per_tag
print(" ".join(sorted(out)))
PY
)"
if [ -z "$unknown" ]; then ok "no template slot is unknown to bootstrap.sh or the per-tag set"
else no "no template slot is unknown to bootstrap.sh or the per-tag set" "orphans: $unknown"; fi

echo
echo "== bootstrap.sh assembles a workspace or fails loudly =="
BWS="$(mktemp -d)"
out="$(bash "$REF/bootstrap.sh" "$BWS" "$REF" 2>&1)"; rc=$?
check "no facts.env: bootstrap refuses" "1" "$rc"

cat > "$BWS/facts.env" <<ENV
REPO=shapes-platform
REPO_PATH=/tmp/repo
REPO_SLUG=owner/repo
SLUG=testsprint
USER=Amit
WS=$BWS
WORKTREE=/tmp/wt
BRANCH=feat/x
BASE=origin/main
TOOLCHAIN=source ~/.nvm/nvm.sh && nvm use 22
VERIFY=pnpm nx affected -t typecheck test lint
FORMAT_CHECK=pnpm format:check
CONTEXT_WINDOW=1000000
WARN_AT_USED=20
RELAY_AT_USED=30
CEILING_USED=60
ENV
out="$(bash "$REF/bootstrap.sh" "$BWS" "$REF" 2>&1)"; rc=$?
check "with facts.env: bootstrap succeeds" "0" "$rc"
# agents.sh is sourced on the first line of four scripts. A workspace without it has a
# launcher, a reviver, a runner and a closer that all fail before doing anything.
for need in agents.sh launch.sh advance.sh watch.sh runner.sh revive.sh classify-error.sh \
            context-used.sh schedule.sh land.sh accept.sh ci-watch.sh ci-watch-prompt.md render.sh continuation-prompt.md; do
  [ -f "$BWS/$need" ] && ok "copied $need" || no "copied $need" "absent from $BWS"
done
check "PERMISSION_MODE defaults to auto" "auto" "$(cat "$BWS/PERMISSION_MODE")"
check "CONTEXT_WINDOW derived from facts.env" "1000000" "$(cat "$BWS/CONTEXT_WINDOW")"
check "VERIFY derived whole, spaces and all" "pnpm nx affected -t typecheck test lint" "$(cat "$BWS/VERIFY")"
check "FORMAT_CHECK derived" "pnpm format:check" "$(cat "$BWS/FORMAT_CHECK" 2>/dev/null)"

# The full suite never runs locally. Every prompt says so, and none tells a session to run it.
for f in implementer-prompt.md continuation-prompt.md review-fix-prompt.md review-find-prompt.md; do
  grep -q 'THE FULL SUITE NEVER RUNS LOCALLY IN THIS SPRINT' "$REF/$f" \
    && ok "$f carries the no-local-suite rule" || no "$f carries the no-local-suite rule" "rule missing"
done
if grep -q '^ *<VERIFY> *$' "$REF/review-fix-prompt.md"; then
  no "FIX-FINAL does not run the full suite" "review-fix-prompt.md still has a <VERIFY> command line"
else
  ok "FIX-FINAL does not run the full suite"
fi
# The repo's own "run the tests before you commit" must not win over the sprint's rule.
for f in implementer-prompt.md continuation-prompt.md review-fix-prompt.md; do
  grep -q 'skip that entirely' "$REF/$f" \
    && ok "$f overrides a repo rule to test before commit" || no "$f overrides a repo rule to test before commit" "override missing"
done
if grep -q 'verify green' "$REF/revive.sh"; then
  no "revive does not tell a resumed session to run the suite" "revive.sh still says verify green"
else
  ok "revive does not tell a resumed session to run the suite"
fi
[ -x "$BWS/launch.sh" ] && ok "scripts are executable" || no "scripts are executable" "launch.sh not +x"

# A missing required fact must stop kickoff, not surface at 3am.
sed '/^FORMAT_CHECK=/d' "$BWS/facts.env" > "$BWS/facts.env.tmp" && mv "$BWS/facts.env.tmp" "$BWS/facts.env"
out="$(bash "$REF/bootstrap.sh" "$BWS" "$REF" 2>&1)"; rc=$?
check "a missing required fact fails bootstrap" "1" "$rc"
case "$out" in
  *FORMAT_CHECK*) ok "it names the missing fact" ;;
  *) no "it names the missing fact" "got: $out" ;;
esac


echo
echo "== the review of 2026-09-19: eight findings, each asserted =="

# --- F1 + F2: the kickoff render contract has to be satisfiable.
grep -q 'prompt-FIX-TEST.txt' "$HERE/../SKILL.md" \
  && ok "F1 kickoff renders a prompt for FIX-TEST" \
  || no "F1 kickoff renders a prompt for FIX-TEST" "launch.sh refuses a tag with no prompt file"

leak="$(grep -l '<PR>' "$REF"/*prompt*.md 2>/dev/null | tr '\n' ' ')"
# The draft PR opens only after T01 lands, so a <PR> slot can never be filled at kickoff and
# render.sh exits 2 on it. The prompts discover the number themselves instead.
if [ -z "$leak" ]; then ok "F2 no template carries an unfillable <PR> slot"
else no "F2 no template carries an unfillable <PR> slot" "still in: $leak"; fi
grep -q 'gh pr view <BRANCH> --json number' "$REF/review-find-prompt.md" \
  && ok "F2 the finder discovers the PR number at runtime" \
  || no "F2 the finder discovers the PR number at runtime" "no discovery line"

# Every slot must appear in SKILL.md's per-role table or be a fact bootstrap requires.
orphans="$(python3 - "$REF" "$HERE/../SKILL.md" <<'PY'
import glob, os, re, sys
ref, skill = sys.argv[1], sys.argv[2]
facts = set(re.findall(r'"([A-Z][A-Z0-9_]*)"', open(os.path.join(ref, "bootstrap.sh")).read()))
# Anything named in a `vars-<TAG>.env` row of the kickoff table counts as documented.
documented = set(re.findall(r'`([A-Z][A-Z0-9_]*)(?:=[^`]*)?`', open(skill).read()))
out = set()
for f in glob.glob(os.path.join(ref, "*prompt*.md")):
    out |= set(re.findall(r'<([A-Z][A-Z0-9_]*)>', open(f).read())) - facts - documented
print(" ".join(sorted(out)))
PY
)"
if [ -z "$orphans" ]; then ok "F2 every template slot is documented in the kickoff contract"
else no "F2 every template slot is documented in the kickoff contract" "undocumented: $orphans"; fi

# --- F4: the setup verdict must wait for a pending repair pass.
if grep -q 'SKIP STEP 6' "$REF/test-prompt.md" && grep -q 'only when no repair pass is pending' "$REF/test-prompt.md"; then
  ok "F4 the setup verdict is conditional on no pending repair"
else
  no "F4 the setup verdict is conditional on no pending repair" "the verdict still runs unconditionally"
fi
grep -q '## STEP 5 - FIX-TEST ONLY' "$REF/review-fix-prompt.md" \
  && ok "F4 FIX-TEST inherits the setup verdict and the golden-path re-run" \
  || no "F4 FIX-TEST inherits the setup verdict and the golden-path re-run" "no FIX-TEST section in the fixer"

# --- F5: cooldown is checked BEFORE the death marker is consumed.
order="$(python3 - "$REF/watch.sh" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
i = src.find("done|\"\")")
block = src[i:i+2000] if i >= 0 else ""
cool = block.find("recently_acted")
died = block.find('did_once "$tag:DIED"')
print("ok" if 0 <= cool < died else "bad cool=%d died=%d" % (cool, died))
PY
)"
check "F5 cooldown precedes consuming the death" "ok" "$order"

# --- F6: the acceptance gate reads the PR head, not a cached tracking ref.
# Strip comments first: accept.sh explains in prose why it no longer reads @{upstream}, and a
# grep that cannot tell code from commentary fails on its own documentation.
code="$(sed 's/[[:space:]]*#.*$//' "$REF/accept.sh")"
if printf '%s' "$code" | grep -q 'headRefOid' && ! printf '%s' "$code" | grep -q 'upstream'; then
  ok "F6 acceptance compares against the PR head, not a local tracking ref"
else
  no "F6 acceptance compares against the PR head, not a local tracking ref" "still reading a local ref"
fi
grep -q 'AFTER="\$(pr_head)"' "$REF/accept.sh" \
  && ok "F6 the head is re-read after the wait" \
  || no "F6 the head is re-read after the wait" "a PASS could name a commit the checks never ran on"

# --- F7: a unique launch generation per revive, and pre-launch ids excluded.
MWS="$(mktemp -d)"
MBIN="$MWS/bin"; mkdir -p "$MBIN" "$MWS/ws/state" "$MWS/wt"
cp "$HERE/mock-claude.sh" "$MBIN/claude"; chmod +x "$MBIN/claude"
for f in agents.sh revive.sh classify-error.sh context-used.sh launch.sh advance.sh; do
  cp "$REF/$f" "$MWS/ws/$f"
done
printf '%s\n' "$MWS/wt" > "$MWS/ws/WORKTREE"
printf 'mslug\n'        > "$MWS/ws/SLUG"
printf 'auto\n'         > "$MWS/ws/PERMISSION_MODE"
printf 'dummy\n'        > "$MWS/ws/prompt-T01.txt"
export MOCK_STATE="$MWS/mock"
mkdir -p "$MOCK_STATE"

# A finished earlier retry, already named -r1, sitting in the harness's list. This is the exact
# shape that made the second budget retry resolve the FIRST retry's session id.
cat > "$MOCK_STATE/agents.json" <<'JSON'
[{"sessionId":"OLD-R1-SID","id":"OLD-R1-S","name":"ns-mslug-T01-r1","state":"done","status":"idle","pid":null,"startedAt":10}]
JSON
printf 'OLD-SID\n' > "$MWS/ws/state/T01.session"
# Two budget waits and one budget resume already happened. Under the old arithmetic - which
# counted only `resume `/`restart ` lines - attempt was still 1 and the name still -r1.
cat > "$MWS/ws/state/T01.revivals" <<'LEDGER'
budget-blocked quota-spend OLD-SID quota-spend retry-at=1
resume-budget budget-retry OLD-SID OLD-R1-SID
budget-blocked quota-spend OLD-R1-SID quota-spend retry-at=2
LEDGER
out="$(PATH="$MBIN:$PATH" bash "$MWS/ws/revive.sh" "$MWS/ws" T01 budget-retry 2>&1)"; rc=$?
launched_name="$(awk 'END{print $1}' "$MOCK_STATE/launches" 2>/dev/null)"
recorded="$(tr -d '[:space:]' < "$MWS/ws/state/T01.session" 2>/dev/null)"
check "F7 a repeated budget retry gets a fresh launch generation" "ns-mslug-T01-r4" "$launched_name"
if [ "$recorded" != "OLD-R1-SID" ] && [ -n "$recorded" ]; then
  ok "F7 the recorded session is the new one, not the finished -r1"
else
  no "F7 the recorded session is the new one, not the finished -r1" "recorded '$recorded' (rc=$rc)"
fi

# Pre-launch exclusion, independent of the name: even with a colliding name already present,
# resolve_sid must not hand back an id that existed before the launch.
grep -q 'exclude=set(sys.argv\[2\].split())' "$REF/revive.sh" \
  && ok "F7 resolve_sid excludes pre-launch session ids" \
  || no "F7 resolve_sid excludes pre-launch session ids" "name collisions can still resolve an old session"

# --- F8: auth writes no terminal status, and auth-retry is a real recovery path.
rm -rf "$MWS/ws/state"; mkdir -p "$MWS/ws/state"
printf 'AUTH-SID\n' > "$MWS/ws/state/T01.session"
: > "$MOCK_STATE/launches"
cat > "$MOCK_STATE/agents.json" <<'JSON'
[]
JSON
# A transcript whose last breath is a logged-out error, where the classifier will find it.
PROJ="$HOME/.claude/projects/ns-test-authfix"
mkdir -p "$PROJ"
cp "$FIX/logged-out.jsonl" "$PROJ/AUTH-SID.jsonl"
out="$(PATH="$MBIN:$PATH" bash "$MWS/ws/revive.sh" "$MWS/ws" T01 api-error 2>&1)"; rc=$?
check "F8 an auth failure exits 6" "6" "$rc"
if [ ! -f "$MWS/ws/state/T01.status" ]; then
  ok "F8 auth writes NO terminal status, so the tag can still come back"
else
  no "F8 auth writes NO terminal status, so the tag can still come back" \
     "wrote '$(head -1 "$MWS/ws/state/T01.status")' - the guard at the top then blocks every recovery"
fi
[ -f "$MWS/ws/state/T01.auth-blocked" ] && ok "F8 it records an auth-blocked marker" \
  || no "F8 it records an auth-blocked marker" "nothing marks the hold"
case "$(head -1 "$MWS/ws/state/PAUSED" 2>/dev/null)" in
  auth*) ok "F8 the sprint is paused on auth" ;;
  *) no "F8 the sprint is paused on auth" "PAUSED is '$(head -1 "$MWS/ws/state/PAUSED" 2>/dev/null)'" ;;
esac

# Now the documented recovery: after /login, revive with auth-retry. It must clear the hold and
# actually resume, rather than tripping the classifier and parking the tag again.
out="$(PATH="$MBIN:$PATH" bash "$MWS/ws/revive.sh" "$MWS/ws" T01 auth-retry 2>&1)"; rc=$?
check "F8 auth-retry succeeds" "0" "$rc"
[ ! -f "$MWS/ws/state/PAUSED" ] && ok "F8 auth-retry clears the sprint-wide hold" \
  || no "F8 auth-retry clears the sprint-wide hold" "PAUSED survives"
[ ! -f "$MWS/ws/state/T01.auth-blocked" ] && ok "F8 auth-retry clears the tag marker" \
  || no "F8 auth-retry clears the tag marker" "marker survives"
if grep -q 'ns-mslug-T01' "$MOCK_STATE/launches" 2>/dev/null; then
  ok "F8 auth-retry actually resumes the conversation"
else
  no "F8 auth-retry actually resumes the conversation" "no launch recorded: $(cat "$MOCK_STATE/launches" 2>/dev/null)"
fi
rm -rf "$PROJ"

# --- F3 (async reviews): a checkpoint finder launches nothing, and FIX-FINAL is always a fresh
# session, because its rendered prompt carries the acceptance gate a resumed session would drop.
grep -q 'A CHECKPOINT review (REVIEW-C<n>) launches nothing' "$REF/review-find-prompt.md" \
  && ok "F3 a checkpoint finder launches no fixer" || no "F3 a checkpoint finder launches no fixer" "no such rule"
grep -q 'always a fresh fixer, because its rendered prompt carries the acceptance gate' "$REF/review-find-prompt.md" \
  && ok "F3 REVIEW-FINAL always launches its rendered fixer" \
  || no "F3 REVIEW-FINAL always launches its rendered fixer" "no such rule"
[ ! -e "$REF/handback.sh" ] && ok "F3 handback.sh is gone with the checkpoint fixers" \
  || no "F3 handback.sh is gone with the checkpoint fixers" "still shipped"

# --- Finished sessions are removed from the agent list, and only once their last turn has ended.
CWS="$MWS/cl"; mkdir -p "$CWS/state"
for f in agents.sh close.sh; do cp "$REF/$f" "$CWS/"; done
printf 'c1053d00-0000-4000-8000-000000000001\n' > "$CWS/state/T01.session"
: > "$MOCK_STATE/stops"; : > "$MOCK_STATE/rms"
# The real harness shape of a session that ended its turn: `state:done`, but a process still up.
row() { printf '[{"sessionId":"c1053d00-0000-4000-8000-000000000001","id":"c1053d00","name":"ns-mslug-T01","state":"done","status":"%s","pid":%s,"startedAt":1}]' "$1" "$2" > "$MOCK_STATE/agents.json"; }
cl() { PATH="$MBIN:$PATH" bash "$CWS/close.sh" "$CWS" T01 "$@" >/dev/null 2>&1; echo $?; }
stops() { wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]'; }
rms() { wc -l < "$MOCK_STATE/rms" | tr -d '[:space:]'; }
listed() { python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$MOCK_STATE/agents.json"; }
reset_close() { rm -f "$CWS/state/.closed-T01"; : > "$MOCK_STATE/stops"; : > "$MOCK_STATE/rms"; }

row idle 999999
check "close refuses a tag with no status" "3" "$(cl)"
check "close stopped nothing for a live ticket" "0" "$(stops)"
check "close removed nothing for a live ticket" "0" "$(rms)"

printf 'DONE\n' > "$CWS/state/T01.status"
row busy 999999
check "close waits while the session is still finishing its turn" "1" "$(cl)"
check "close stopped nothing mid-turn - that turn launches the successor" "0" "$(stops)"
check "close removed nothing mid-turn" "0" "$(rms)"

check "close --force removes it anyway (the runner's last pass)" "0" "$(cl --force)"
check "close stops by the SHORT id" "stop c1053d00" "$(cat "$MOCK_STATE/stops")"
check "close removes by the SHORT id" "rm c1053d00" "$(cat "$MOCK_STATE/rms")"
check "the removed session is off the agent list" "0" "$(listed)"
[ -f "$CWS/state/.closed-T01" ] && ok "close marks the tag closed" \
  || no "close marks the tag closed" "no .closed-T01"
check "close is once per tag" "0" "$(cl)"
check "a second close sends no second stop" "1" "$(stops)"
check "a second close sends no second rm" "1" "$(rms)"

reset_close
row idle 999999
check "close removes an idle finished session" "0" "$(cl)"
check "close sent exactly one rm" "1" "$(rms)"
check "the idle session is off the agent list" "0" "$(listed)"

# A stopped session is still a listed job - taking it off the list is the whole point.
reset_close
row idle null
check "close removes a session that exited but is still listed" "0" "$(cl)"
check "close sent rm to the exited session" "rm c1053d00" "$(cat "$MOCK_STATE/rms")"
check "the exited session is off the agent list" "0" "$(listed)"

reset_close
printf '[]' > "$MOCK_STATE/agents.json"
check "close of a session already off the list succeeds" "0" "$(cl)"
check "close sends no stop to a session that is off the list" "0" "$(stops)"
check "close sends no rm to a session that is off the list" "0" "$(rms)"
[ -f "$CWS/state/.closed-T01" ] && ok "close marks a session that is off the list closed" \
  || no "close marks a session that is off the list closed" "no .closed-T01"

# An rm that does not take: the row stays, so close fails and leaves the tag for the next sweep.
reset_close
row idle null
printf '1\n' > "$MOCK_STATE/rm-sticks"
check "close fails when the session stays listed after rm" "1" "$(cl)"
[ -f "$CWS/state/.closed-T01" ] && no "close leaves a still-listed tag unmarked" "marked closed" \
  || ok "close leaves a still-listed tag unmarked"
rm -f "$MOCK_STATE/rm-sticks"

# rm keeps the shared worktree only because a sprint session did not create it. The flags that
# delete a worktree anyway must never appear.
grep -n -e '--force-remove-worktree' -e '--discard-unpushed' "$REF"/*.sh >/dev/null \
  && no "no script deletes a worktree through claude rm" "found --force-remove-worktree or --discard-unpushed" \
  || ok "no script deletes a worktree through claude rm"
order="$(python3 - "$REF/watch.sh" <<'PY'
import sys
src = open(sys.argv[1]).read()
adv = src.find('do_advance "$tag"; arc=$?')
cls = src.find('do_close "$tag" || true')
force = src.find('do_close "$tag" --force')
sweep0 = src.find('say "SWEEP 0')
print("ok" if 0 <= adv < cls and 0 <= force < sweep0 else "bad adv=%d close=%d force=%d sweep0=%d" % (adv, cls, force, sweep0))
PY
)"
check "the runner closes after advancing, and force-closes before it exits" "ok" "$order"

unset MOCK_STATE
rm -rf "$MWS" "$RWS" "$BWS"

echo
echo "== research mode: bootstrap builds a local repo, no PR, and its own fact set =="
QWS="$(mktemp -d)"
research_facts() {
  cat > "$QWS/facts.env" <<ENV
MODE=research
SLUG=pricing-20261001
USER=Amit
WS=$QWS
WORKTREE=$QWS/work
BRANCH=research/pricing-20261001
VERIFY=bash $QWS/research-check.sh $QWS
RESEARCH_TITLE=How competitors price seats
QUESTION=How do the top five competitors price per seat?
DECISION=Whether to move to per-seat pricing
AUDIENCE=the product team
SOURCES=Web (WebSearch, WebFetch); Slack; Google Drive
TOTAL=3
CONTEXT_WINDOW=200000
WARN_AT_USED=20
RELAY_AT_USED=30
CEILING_USED=60
ENV
}
drop_fact() { grep -v "^$1=" "$QWS/facts.env" > "$QWS/facts.env.tmp"; mv "$QWS/facts.env.tmp" "$QWS/facts.env"; }

research_facts
out="$(bash "$REF/bootstrap.sh" "$QWS" "$REF" 2>&1)"; rc=$?
check "research bootstrap succeeds without any repo facts" "0" "$rc"
check "MODE derived" "research" "$(cat "$QWS/MODE" 2>/dev/null)"
check "the worktree is a local repo on the sprint branch" "research/pricing-20261001" \
  "$(git -C "$QWS/work" rev-parse --abbrev-ref HEAD 2>/dev/null)"
check "it has a HEAD for launch.sh to record" "0" \
  "$(git -C "$QWS/work" rev-parse HEAD >/dev/null 2>&1; echo $?)"
check "it has no remote" "" "$(git -C "$QWS/work" remote 2>/dev/null)"
[ -f "$QWS/state/.pr-asked" ] && ok "the runner's NEEDS-PR ask is pre-answered" \
  || no "the runner's NEEDS-PR ask is pre-answered" "no state/.pr-asked"
for need in research-check.sh research-ticket-prompt.md research-continuation-prompt.md \
            research-review-find-prompt.md research-review-fix-prompt.md research-synth-prompt.md \
            research-plan-template.md; do
  [ -f "$QWS/$need" ] && ok "copied $need" || no "copied $need" "absent from $QWS"
done
out="$(bash "$REF/bootstrap.sh" "$QWS" "$REF" 2>&1)"; rc=$?
check "re-running bootstrap keeps the existing repo" "0" "$rc"
check "and does not add a second root commit" "1" "$(git -C "$QWS/work" rev-list --count HEAD)"

drop_fact QUESTION
out="$(bash "$REF/bootstrap.sh" "$QWS" "$REF" 2>&1)"; rc=$?
check "a missing research fact fails bootstrap" "1" "$rc"
case "$out" in *QUESTION*) ok "it names the missing research fact" ;; *) no "it names the missing research fact" "got: $out" ;; esac
research_facts
drop_fact MODE
printf 'MODE=essay\n' >> "$QWS/facts.env"
out="$(bash "$REF/bootstrap.sh" "$QWS" "$REF" 2>&1)"; rc=$?
check "an unknown MODE fails bootstrap" "1" "$rc"
research_facts
bash "$REF/bootstrap.sh" "$QWS" "$REF" >/dev/null 2>&1

CWS="$(mktemp -d)"
cat > "$CWS/facts.env" <<ENV
REPO=r
REPO_PATH=/tmp/repo
REPO_SLUG=owner/repo
SLUG=codesprint
USER=Amit
WS=$CWS
WORKTREE=/tmp/wt
BRANCH=feat/x
BASE=origin/main
TOOLCHAIN=none
VERIFY=true
FORMAT_CHECK=true
ENV
bash "$REF/bootstrap.sh" "$CWS" "$REF" >/dev/null 2>&1
check "a code sprint defaults to MODE=code" "code" "$(cat "$CWS/MODE" 2>/dev/null)"
[ ! -f "$CWS/state/.pr-asked" ] && ok "a code sprint still gets its NEEDS-PR ask" \
  || no "a code sprint still gets its NEEDS-PR ask" "code-mode bootstrap wrote .pr-asked"
rm -rf "$CWS"

echo
echo "== research-check.sh: every claim names its source =="
F="$QWS/work/findings/01-acme.md"
rc_of() { bash "$QWS/research-check.sh" "$QWS" "$@" >/dev/null 2>&1; echo $?; }
# edit <old> <new>: one literal replacement in the findings file.
edit() { python3 -c 'import sys; p,a,b=sys.argv[1:4]; s=open(p).read(); assert a in s, a; open(p,"w").write(s.replace(a,b,1))' "$F" "$1" "$2"; }
good() {
  cat > "$F" <<'MD'
# 01: How Acme prices

**Question:** How does Acme price seats?

## Answer
Acme charges per seat with a volume discount [S1][S2].
**Confidence:** medium - two sources, one is a forum post.

## Findings
- Acme lists $12 per seat per month on its pricing page [S1]
- Customers in Slack say the discount starts at 50 seats [S2]
- So a 100-seat team likely pays under $1,200 a month [INFERENCE]

## Gaps
- Enterprise pricing is not public.

## Sources
- [S1] Acme pricing - https://acme.example/pricing - accessed 2026-10-01
- [S2] #sales thread - connector:Slack #sales 2026-09-30 p1727700000 - accessed 2026-10-01
MD
}
check "no findings files: FAIL" "1" "$(rc_of)"
good
check "a well-cited findings file: PASS" "0" "$(rc_of)"
good; edit "- So a 100-seat team" "- An uncited claim
- So a 100-seat team"
check "an uncited finding: FAIL" "1" "$(rc_of)"
good; edit "page [S1]" "page [S3]"
check "citing a source Sources does not define: FAIL" "1" "$(rc_of)"
good; edit "https://acme.example/pricing" "the pricing page"
check "a source with no locator: FAIL" "1" "$(rc_of)"
good; edit "https://acme.example/pricing" "repo:web/src/pricing/table.tsx:42 @8a2256f"
check "a repo:<path>:<line> @<sha> locator: PASS" "0" "$(rc_of)"
good; edit "https://acme.example/pricing" "repo: see the code"
check "a bare repo: with no path: FAIL" "1" "$(rc_of)"
good; edit "## Gaps" "## Holes"
check "a missing section: FAIL" "1" "$(rc_of)"
good
check "--final with no artifact: FAIL" "1" "$(rc_of --final)"
mkdir -p "$QWS/artifact" && echo '<!doctype html><title>x</title>' > "$QWS/artifact/index.html"
check "--final with an artifact but no URL: FAIL" "1" "$(rc_of --final)"
echo "https://claude.ai/artifact/abc" > "$QWS/state/ARTIFACT.url"
check "--final with an artifact and its URL: PASS" "0" "$(rc_of --final)"

echo
echo "== research templates render with nothing left unfilled =="
cat > "$QWS/vars-T01.env" <<'ENV'
TAG=T01
NN=01
TICKET_TITLE=How Acme prices
GOTCHAS=None known.
NEXT_TAG=T02
TOTAL=3
ENV
cat > "$QWS/vars-REVIEW-FINAL.env" <<'ENV'
TAG=REVIEW-FINAL
FIX_TAG=FIX-FINAL
NEXT_AFTER_FIX=SYNTH
ENV
cat > "$QWS/vars-FIX-FINAL.env" <<'ENV'
TAG=FIX-FINAL
FIND_TAG=REVIEW-FINAL
NEXT_TAG=SYNTH
ENV
printf 'TAG=SYNTH\n' > "$QWS/vars-SYNTH.env"
cat > "$QWS/vars-T01c2.env" <<'ENV'
CONT_TAG=T01c2
PREV_TAG=T01
NN=01
TICKET_TITLE=How Acme prices
NEXT_TAG=T02
ENV
for pair in "research-ticket-prompt.md:T01" "research-review-find-prompt.md:REVIEW-FINAL" \
            "research-review-fix-prompt.md:FIX-FINAL" "research-synth-prompt.md:SYNTH" \
            "research-continuation-prompt.md:T01c2"; do
  tpl="${pair%%:*}"; tag="${pair##*:}"
  bash "$QWS/render.sh" "$QWS" "$QWS/$tpl" "$QWS/prompt-$tag.txt" "$QWS/vars-$tag.env" >/dev/null 2>&1
  check "renders $tpl" "0" "$?"
done
grep -q 'READ ONLY' "$QWS/prompt-T01.txt" && ok "the ticket prompt carries the read-only connector rule" \
  || no "the ticket prompt carries the read-only connector rule" "no READ ONLY line"
CP="$HERE/../../product-research/references/conductor-prompt.md"
printf 'NS_DIR=%s\n' "$HERE/.." > "$QWS/vars-CONDUCTOR.env"
bash "$QWS/render.sh" "$QWS" "$CP" "$QWS/prompt-CONDUCTOR.txt" "$QWS/vars-CONDUCTOR.env" >/dev/null 2>&1
check "product-research's conductor prompt renders from the same facts" "0" "$?"
NM="$HERE/../../night-marathon/references"
cat >> "$QWS/facts.env" <<ENV
FEATURE=Seat-based pricing table on the billing page
MARATHON_MODE=review
REPO_PATH=$QWS/repo-src
BASE=main
REPO_SNAPSHOT=$QWS/repo
REPO_SHA=8a2256f
BUILD_TEST=none
SPEED=serial
BLITZ=0
MAX_PARALLEL=3
DEPTH=5
NS_DIR=$HERE/..
NM_DIR=$HERE/../../night-marathon
ENV
for pair in "conductor-prompt.md:NM-CONDUCTOR" "plan-synth-prompt.md:SYNTH" "build-prompt.md:NM-BUILD"; do
  tpl="${pair%%:*}"; tag="${pair##*:}"
  bash "$QWS/render.sh" "$QWS" "$NM/$tpl" "$QWS/prompt-$tag.txt" "$QWS/vars-SYNTH.env" >/dev/null 2>&1
  check "night-marathon's $tpl renders from the research facts" "0" "$?"
done
grep -q 'night-marathon picks: pricing-20261001' "$QWS/prompt-SYNTH.txt" \
  && ok "the plan prompt pins the picks header the conductor parses" \
  || no "the plan prompt pins the picks header the conductor parses" "header missing"
grep -q 'gpt-6-astra' "$QWS/prompt-SYNTH.txt" && grep -q '`effort`: `medium`' "$QWS/prompt-SYNTH.txt" \
  && ok "the plan prompt asks Codex gpt-6-astra at medium effort" \
  || no "the plan prompt asks Codex gpt-6-astra at medium effort" "model or effort missing"
grep -q 'does not start with `ready: yes`' "$QWS/prompt-SYNTH.txt" && grep -q 'Skipped - <codex-bridge is not connected' "$QWS/prompt-SYNTH.txt" \
  && ok "the plan prompt runs without Codex when the bridge is not connected" \
  || no "the plan prompt runs without Codex when the bridge is not connected" "no skip rule"
grep -q 'Ask again ONCE with the same arguments and no `model`' "$QWS/prompt-SYNTH.txt" \
  && ok "an account without gpt-6-astra falls back to its default Codex model, once" \
  || no "an account without gpt-6-astra falls back to its default Codex model, once" "no fallback rule"
s3=$(grep -n '^## STEP 3 - A SECOND OPINION FROM CODEX' "$QWS/prompt-SYNTH.txt" | cut -d: -f1)
s4=$(grep -n '^## STEP 4 - DRAW THE UI' "$QWS/prompt-SYNTH.txt" | cut -d: -f1)
[ -n "$s3" ] && [ -n "$s4" ] && [ "$s3" -lt "$s4" ] \
  && ok "Codex reviews the plan before the mockups are drawn" \
  || no "Codex reviews the plan before the mockups are drawn" "STEP 3 at '$s3', STEP 4 at '$s4'"
rm -rf "$QWS"

echo
echo "== phase chain: one runner over the conductors, and a dead conductor comes back =="
# The night of 2026-10-02: the machina build conductor launched the platform build conductor
# with a bare `claude --bg`, saw it busy, and ended. The new conductor died 2.5 minutes later on
# "Connection lost mid-response", nothing watched it, and six hours went by. Each case below is
# a piece of the run-level runner that now owns that hop and that death.
PCW="$(mktemp -d)"
PBIN="$PCW/bin"; mkdir -p "$PBIN" "$PCW/runws" "$PCW/repo-a"
cp "$HERE/mock-claude.sh" "$PBIN/claude"; chmod +x "$PBIN/claude"
export MOCK_STATE="$PCW/mock"; mkdir -p "$MOCK_STATE"
: > "$MOCK_STATE/launches"; : > "$MOCK_STATE/stops"; : > "$MOCK_STATE/rms"
P="$PCW/phases"
PC() { PATH="$PBIN:$PATH" bash "$REF/phase-chain.sh" "$@" >/dev/null 2>&1; echo $?; }
pw() { PATH="$PBIN:$PATH" bash "$P/watch.sh" "$P" 0 0 --once >/dev/null 2>&1; }
prv() { PATH="$PBIN:$PATH" bash "$P/revive.sh" "$P" BUILD "$1" >/dev/null 2>&1; echo $?; }
nlaunch() { wc -l < "$MOCK_STATE/launches" | tr -d '[:space:]'; }
lastl() { tail -1 "$MOCK_STATE/launches"; }
agent() { printf '[{"sessionId":"%s","id":"%s","name":"%s","state":"working","status":"%s","pid":null,"startedAt":1}]' \
            "$1" "${1:0:8}" "$2" "$3" > "$MOCK_STATE/agents.json"; }
PROJ="$HOME/.claude/projects/ns-test-phasechain"
mkdir -p "$PROJ"

check "phase-chain init succeeds" "0" "$(PC init "$P" "$REF" pslug)"
[ -x "$P/phase-chain.sh" ] && ok "init copies phase-chain.sh, so a conductor can restart the runner" \
  || no "init copies phase-chain.sh, so a conductor can restart the runner" "absent from $P"
[ -f "$P/PHASE_CHAIN" ] && ok "init marks the workspace a phase chain" \
  || no "init marks the workspace a phase chain" "no PHASE_CHAIN marker"
check "add CONDUCTOR -> BUILD" "0" "$(PC add "$P" CONDUCTOR "$PCW/runws" BUILD)"
check "add BUILD, the last phase" "0" "$(PC add "$P" BUILD "$PCW/repo-a")"
check "add refuses a cwd that does not exist" "1" "$(PC add "$P" X "$PCW/nope")"
printf 'research conductor role\n' > "$P/prompt-CONDUCTOR.txt"
printf 'build conductor role\n'    > "$P/prompt-BUILD.txt"
grep -q 'os.setsid()' "$REF/runner.sh" && grep -q 'runner.sh" start' "$REF/phase-chain.sh" \
  && ok "the runner is detached into its own session, so no conductor's death takes it down" \
  || no "the runner is detached into its own session, so no conductor's death takes it down" "no setsid"
[ -x "$P/runner.sh" ] && ok "init copies runner.sh, which the phase runner starts through" \
  || no "init copies runner.sh, which the phase runner starts through" "absent from $P"
[ ! -f "$P/CONTEXT_WINDOW" ] && ok "init without a window writes none (watch.sh keeps its default)" \
  || no "init without a window writes none (watch.sh keeps its default)" "$(cat "$P/CONTEXT_WINDOW")"
P2="$PCW/phases-1m"
PC init "$P2" "$REF" pslug 1000000 >/dev/null
check "init with a window pins it, so a 1M conductor is not read as 90% full" "1000000" \
      "$(cat "$P2/CONTEXT_WINDOW" 2>/dev/null)"

# --- the hop: a conductor writes DONE, the RUNNER starts the next phase in the next repo.
printf 'c0d0c0d0-0000-4000-8000-000000000001\n' > "$P/state/CONDUCTOR.session"
agent c0d0c0d0-0000-4000-8000-000000000001 ns-pslug-CONDUCTOR idle
printf 'DONE\n' > "$P/state/CONDUCTOR.status"
printf 'b1b1b1b1-0000-4000-8000-000000000001\n' > "$MOCK_STATE/next-sid"
pw
check "DONE on a conductor launches the next phase" "ns-pslug-BUILD" "$(lastl | cut -d' ' -f1)"
check "the next phase runs in its own cwd" "$PCW/repo-a" "$(lastl | cut -d' ' -f4)"
check "its session id is recorded for the runner" "b1b1b1b1-0000-4000-8000-000000000001" \
      "$(tr -d '[:space:]' < "$P/state/BUILD.session" 2>/dev/null)"
check "a finished conductor is not removed - its last message is the report" "0" \
      "$(wc -l < "$MOCK_STATE/rms" | tr -d '[:space:]')"

# --- the incident: the new conductor dies on "Connection lost" and shows working/idle.
DEAD=d6d4bdb8-2007-42c6-a51b-6c432c131d06
cp "$FIX/connection-lost.jsonl" "$PROJ/$DEAD.jsonl"
printf '%s\n' "$DEAD" > "$P/state/BUILD.session"
agent "$DEAD" ns-pslug-BUILD idle
printf 'e2e2e2e2-0000-4000-8000-000000000001\n' > "$MOCK_STATE/next-sid"
pw
check "a conductor dead on a lost connection is RESUMED, not restarted" "ns-pslug-BUILD-r1 $DEAD" \
      "$(lastl | cut -d' ' -f1-2)"
check "the resume runs in the conductor's own cwd, where its transcript lives" "$PCW/repo-a" \
      "$(lastl | cut -d' ' -f4)"
check "the session file is repointed at the resumed session" "e2e2e2e2-0000-4000-8000-000000000001" \
      "$(tr -d '[:space:]' < "$P/state/BUILD.session")"
grep -q 'phase CONDUCTOR' "$MOCK_STATE/last-prompt" \
  && ok "the resumed conductor is sent back to its LOG.md, not told to commit a ticket" \
  || no "the resumed conductor is sent back to its LOG.md, not told to commit a ticket" "$(head -3 "$MOCK_STATE/last-prompt")"
grep -q "^resume api-error $DEAD" "$P/state/BUILD.revivals" 2>/dev/null \
  && ok "the revive is in the ledger the report reads" \
  || no "the revive is in the ledger the report reads" "no resume line in BUILD.revivals"
grep -q "STALLED BUILD .*class=transient connection-lost" "$P/state/EVENTS.log" \
  && ok "the death and its class are in EVENTS.log" \
  || no "the death and its class are in EVENTS.log" "no STALLED line"

# --- turn_ended: the transcript says whether the session closed its turn or stopped mid-turn.
te() { ( . "$REF/agents.sh"; turn_ended "$FIX/$1" ) && echo ended || echo mid-turn; }
check "turn_ended: a turn closed by the harness marker" "ended"    "$(te gate-wait.jsonl)"
check "turn_ended: stopped on a pending tool call"      "mid-turn" "$(te permission-prompt.jsonl)"
check "turn_ended: no marker after the last message"    "mid-turn" "$(te clean.jsonl)"

# --- a conductor that ended its own turn (review gate, Monitor wait, relay) is NOT dead.
WAIT=a1a1a1a1-0000-4000-8000-000000000001
cp "$FIX/gate-wait.jsonl" "$PROJ/$WAIT.jsonl"
printf '%s\n' "$WAIT" > "$P/state/BUILD.session"
agent "$WAIT" ns-pslug-BUILD idle
before="$(nlaunch)"; stops_before="$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
pw
check "the runner does not revive a waiting conductor" "$before" "$(nlaunch)"
grep -q "WAITING BUILD $WAIT" "$P/state/EVENTS.log" \
  && ok "it logs the wait once instead" || no "it logs the wait once instead" "no WAITING line"
check "revive.sh itself leaves a waiting conductor alone" "0" "$(prv ended-without-signal)"
check "no stop reached the waiting conductor" "$stops_before" "$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
check "and nothing was launched for it" "$before" "$(nlaunch)"

# --- the review gate, 2026-10-02: the conductor posted the plan link and ended its turn to wait
#     for the user's picks. The harness labels that `state:blocked`, the runner read it as a
#     permission prompt, and the conductor the user was answering was stopped and restarted.
agent_s() { printf '[{"sessionId":"%s","id":"%s","name":"%s","state":"%s","status":"%s","pid":null,"startedAt":1}]' \
              "$1" "${1:0:8}" "$2" "$3" "$4" > "$MOCK_STATE/agents.json"; }
rm -f "$P/state/.acted-BUILD"; : > "$P/state/.watch-seen"
agent_s "$WAIT" ns-pslug-BUILD blocked idle
before="$(nlaunch)"; stops_before="$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
pw
check "a conductor waiting at the review gate (blocked) is not revived" "$before" "$(nlaunch)"
check "and not stopped" "$stops_before" "$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
grep -q "WAITING BUILD $WAIT .*state blocked" "$P/state/EVENTS.log" \
  && ok "the gate wait is logged as WAITING, not STUCK" || no "the gate wait is logged as WAITING, not STUCK" \
     "$(grep "BUILD" "$P/state/EVENTS.log" | tail -2)"
check "revive.sh refuses a permission-prompt revive of a conductor whose turn closed" "0" "$(prv permission-prompt)"
check "no stop reached it from revive.sh either" "$stops_before" "$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"

# --- a conductor waiting on its Monitor reads `busy`. Silent for 30 minutes, turn closed: waiting.
rm -f "$P/state/BUILD.revivals" "$P/state/.acted-BUILD" "$P/state/BUILD.status"; : > "$P/state/.watch-seen"
printf '%s\n' "$WAIT" > "$P/state/BUILD.session"
python3 -c 'import os,sys,time; t=time.time()-1800; os.utime(sys.argv[1],(t,t))' "$PROJ/$WAIT.jsonl"
agent_s "$WAIT" ns-pslug-BUILD working busy
before="$(nlaunch)"
pw
check "a conductor waiting on its Monitor (busy, turn closed) is not revived" "$before" "$(nlaunch)"
check "revive.sh leaves it alone too" "0" "$(prv idle)"
check "nothing was launched for it" "$before" "$(nlaunch)"

# --- a REAL permission prompt stops mid-turn, and that conductor still gets revived.
PERM=f0f0f0f0-0000-4000-8000-000000000001
cp "$FIX/permission-prompt.jsonl" "$PROJ/$PERM.jsonl"
printf '%s\n' "$PERM" > "$P/state/BUILD.session"
rm -f "$P/state/BUILD.revivals" "$P/state/.acted-BUILD"; : > "$P/state/.watch-seen"
agent_s "$PERM" ns-pslug-BUILD blocked idle
pw
check "a conductor stuck on a real permission prompt is still resumed" "ns-pslug-BUILD-r1 $PERM" \
      "$(lastl | cut -d' ' -f1-2)"
printf '%s\n' "$WAIT" > "$P/state/BUILD.session"

# --- busy, silent for 30 minutes, no error, turn never closed: a call that hung. That one IS dead.
rm -f "$P/state/BUILD.revivals" "$P/state/.acted-BUILD"
cp "$FIX/clean.jsonl" "$PROJ/$WAIT.jsonl"
python3 -c 'import os,sys,time; t=time.time()-1800; os.utime(sys.argv[1],(t,t))' "$PROJ/$WAIT.jsonl"
agent "$WAIT" ns-pslug-BUILD busy
check "a hung conductor is revived" "0" "$(prv idle)"
check "by a resume" "ns-pslug-BUILD-r1 $WAIT" "$(lastl | cut -d' ' -f1-2)"

# --- resume budget spent: restart on the role prompt, told to resume from its LOG.md.
printf '%s\n' "$DEAD" > "$P/state/BUILD.session"
agent "$DEAD" ns-pslug-BUILD idle
printf 'resume api-error a b\nresume api-error b c\n' > "$P/state/BUILD.revivals"
check "past the resume budget the conductor is restarted" "0" "$(prv api-error)"
check "the restart is a fresh session on the phase name, in its cwd" "ns-pslug-BUILD none" \
      "$(lastl | cut -d' ' -f1-2)"
grep -q '^## RESUME - the earlier conductor session died' "$P/prompt-BUILD.txt" \
  && ok "the restarted conductor is told to resume at the step its LOG.md names" \
  || no "the restarted conductor is told to resume at the step its LOG.md names" "no RESUME block"

# --- machina-api, 2026-10-02: will anything wake a conductor whose turn is closed?
# Stand-in session processes. The harness runs every tool command (Monitor scripts, background
# Bash) as a direct child of the session's process, through its shell snapshot, so an "armed"
# stand-in has a child whose command line carries `shell-snapshots`. A "bare" one has a child too,
# but not a tool: MCP servers and the status line are children of a real session as well.
# `sleep 317` marks every process this section starts, so the cleanup below finds all of them.
fake_session() {
  if [ "$1" = armed ]; then
    bash -c '/bin/sh -c "sleep 317; : shell-snapshots" & wait' >/dev/null 2>&1 &
  else
    bash -c 'sleep 317 & wait' >/dev/null 2>&1 &
  fi
  FAKE_PID=$!
}
agent_p() { printf '[{"sessionId":"%s","id":"%s","name":"%s","state":"%s","status":"%s","pid":%s,"startedAt":1}]' \
              "$1" "${1:0:8}" "$2" "$3" "$4" "$5" > "$MOCK_STATE/agents.json"; }
na() { ( PATH="$PBIN:$PATH"; . "$P/agents.sh"; nothing_armed "$1" ) && echo nothing || echo armed; }
ago() { python3 -c 'import os,sys,time; t=time.time()-60*int(sys.argv[2]); os.utime(sys.argv[1],(t,t))' "$PROJ/$1.jsonl" "$2"; }
reset_build() {
  rm -f "$P/state/BUILD.revivals" "$P/state/.acted-BUILD" "$P/state/BUILD.status" \
        "$P/state/BUILD.summary" "$P/state/BUILD.waiting-on-user"
  : > "$P/state/.watch-seen"
  printf '%s\n' "$1" > "$P/state/BUILD.session"
}

U=0a0a0a0a-0000-4000-8000-000000000001
fake_session armed; ARMED=$FAKE_PID
fake_session bare;  BARE=$FAKE_PID
sleep 1
agent_p "$U" ns-pslug-BUILD working busy "$ARMED"
check "nothing_armed: a Monitor or background command is running" "armed" "$(na "$U")"
agent_p "$U" ns-pslug-BUILD working busy "$BARE"
check "nothing_armed: only non-tool children (MCP servers, status line)" "nothing" "$(na "$U")"
agent_p "$U" ns-pslug-BUILD working busy null
check "nothing_armed: no pid to look at counts as armed - never revive on a guess" "armed" "$(na "$U")"

# The marker: a review-mode conductor at the gate waits on a person, for hours if need be.
cp "$FIX/gate-wait.jsonl" "$PROJ/$U.jsonl"; ago "$U" 40
reset_build "$U"; : > "$P/state/BUILD.waiting-on-user"
agent_p "$U" ns-pslug-BUILD blocked idle "$BARE"
before="$(nlaunch)"
pw
check "a conductor at the review gate (marker set) is not revived after 40m" "$before" "$(nlaunch)"
grep -q "WAITING BUILD $U" "$P/state/EVENTS.log" \
  && ok "the gate wait is logged as WAITING" || no "the gate wait is logged as WAITING" "no WAITING line"

# Armed: its Monitor will wake it. Left alone however long the turn has been closed.
reset_build "$U"
agent_p "$U" ns-pslug-BUILD working busy "$ARMED"
pw
check "a conductor with its Monitor armed is not revived after 40m" "$before" "$(nlaunch)"

# Unarmed: turn closed 40m ago, no tool running, no marker. Nothing will ever wake it.
reset_build "$U"
agent_p "$U" ns-pslug-BUILD working busy "$BARE"
printf '0b0b0b0b-0000-4000-8000-000000000001\n' > "$MOCK_STATE/next-sid"
pw
check "an UNARMED conductor (closed 40m, nothing to wake it) is resumed" "ns-pslug-BUILD-r1 $U" \
      "$(lastl | cut -d' ' -f1-2)"
grep -q "UNARMED BUILD $U" "$P/state/EVENTS.log" \
  && ok "it is logged as UNARMED" || no "it is logged as UNARMED" "$(grep BUILD "$P/state/EVENTS.log" | tail -2)"
grep -q 'nothing armed to wake you' "$MOCK_STATE/last-prompt" \
  && ok "the resume tells it to re-arm" || no "the resume tells it to re-arm" "$(head -3 "$MOCK_STATE/last-prompt")"
grep -q "^resume unarmed $U .* at=[0-9]" "$P/state/BUILD.revivals" \
  && ok "the rung is in the ledger with its time" || no "the rung is in the ledger with its time" \
     "$(cat "$P/state/BUILD.revivals" 2>/dev/null)"

# Only 30 minutes closed: inside the Monitor's cap, so its expiry may still be on the way.
reset_build "$U"; ago "$U" 30
fake_session bare; BARE=$FAKE_PID; sleep 1
agent_p "$U" ns-pslug-BUILD working busy "$BARE"
before="$(nlaunch)"
pw
check "a closed turn inside the 30-minute Monitor cap is still a wait" "$before" "$(nlaunch)"

# revive.sh checks again: a conductor that re-armed since the watcher looked is waiting.
reset_build "$U"; ago "$U" 40
agent_p "$U" ns-pslug-BUILD working busy "$ARMED"
check "revive.sh refuses an unarmed revive of a conductor that has re-armed" "0" "$(prv unarmed)"
check "and launches nothing" "$before" "$(nlaunch)"

# --- out of rungs: the abandon writes the status and stops nothing. On 2026-10-02 the abandon
#     stopped a healthy BUILD conductor, and the sprint runner under its Monitor died with it.
H=0c0c0c0c-0000-4000-8000-000000000001
cp "$FIX/clean.jsonl" "$PROJ/$H.jsonl"; ago "$H" 30
reset_build "$H"
fake_session bare; LIVE=$FAKE_PID; sleep 1
agent_p "$H" ns-pslug-BUILD working busy "$LIVE"
now="$(date +%s)"
printf 'resume idle a b at=%s\nrestart idle b - at=%s\n' "$now" "$now" > "$P/state/BUILD.revivals"
stops_before="$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
check "a conductor out of rungs is abandoned" "0" "$(prv idle)"
case "$(head -1 "$P/state/BUILD.status" 2>/dev/null)" in
  "BLOCKED: ABANDONED after 2 revive attempts in 60m"*"left running"*) ok "the status says it was left running" ;;
  *) no "the status says it was left running" "$(head -1 "$P/state/BUILD.status" 2>/dev/null)" ;;
esac
check "no stop reached the abandoned conductor" "$stops_before" "$(wc -l < "$MOCK_STATE/stops" | tr -d '[:space:]')"
kill -0 "$LIVE" 2>/dev/null && ok "its process is still alive" || no "its process is still alive" "pid $LIVE is gone"

# --- the ladder is per incident: rungs older than 60 minutes do not count for a conductor.
reset_build "$H"
old=$(( $(date +%s) - 7200 ))
printf 'resume idle a b at=%s\nrestart idle b - at=%s\n' "$old" "$old" > "$P/state/BUILD.revivals"
check "two rungs two hours ago leave the ladder whole" "0" "$(prv idle)"
check "so the conductor is resumed, not abandoned" "ns-pslug-BUILD-r3 $H" "$(lastl | cut -d' ' -f1-2)"
kill -0 "$LIVE" 2>/dev/null && no "the resume stopped the old process first" "pid $LIVE still alive" \
  || ok "the resume stopped the old process first"

# Rows from before the time field have no time, so they still count.
reset_build "$H"
agent "$H" ns-pslug-BUILD busy
printf 'resume idle a b\nrestart idle b -\n' > "$P/state/BUILD.revivals"
prv idle >/dev/null
case "$(head -1 "$P/state/BUILD.status" 2>/dev/null)" in
  "BLOCKED: ABANDONED"*) ok "rungs with no time still count" ;;
  *) no "rungs with no time still count" "$(head -1 "$P/state/BUILD.status" 2>/dev/null)" ;;
esac

# --- a refusal is not a rung. 13 of these in the ledger made the second rung "attempt 15".
reset_build "$H"
cp "$FIX/clean.jsonl" "$PROJ/$H.jsonl"
agent "$H" ns-pslug-BUILD busy
check "a session still working is refused" "1" "$(prv idle)"
rows="$(cat "$P/state/BUILD.revivals" 2>/dev/null | wc -l | tr -d '[:space:]')"
check "and the refusal writes no ledger row" "0" "$rows"

pkill -f 'sleep 317' 2>/dev/null
printf '%s\n' "$WAIT" > "$P/state/BUILD.session"

# --- the marathon prompts hand the hop to the runner; no conductor launches the next by hand.
NMR="$HERE/../../night-marathon/references"
if grep -n 'claude --bg -n' "$NMR/conductor-prompt.md" "$NMR/build-prompt.md" >/dev/null; then
  no "no marathon conductor launches its successor with a bare claude --bg" \
     "$(grep -n 'claude --bg -n' "$NMR/conductor-prompt.md" "$NMR/build-prompt.md")"
else
  ok "no marathon conductor launches its successor with a bare claude --bg"
fi
for f in conductor-prompt.md build-prompt.md; do
  grep -q 'phases/state/' "$NMR/$f" \
    && ok "$f writes its session and status into the phase chain" \
    || no "$f writes its session and status into the phase chain" "no phases/state/ path"
done

unset MOCK_STATE
rm -rf "$PCW" "$PROJ"

echo
echo "== runner.sh: the runner lives on its own, the conductor only listens =="
# machina-api, 2026-10-02: the build runner ran as the conductor's Monitor command, so it died at
# every 30-minute Monitor expiry and with the conductor. When the conductor was stopped at 14:53Z,
# FIX-C2 lost its connection three minutes later and nothing resumed it for four hours.
RN="$(mktemp -d)"; mkdir -p "$RN/state"
cp "$REF/runner.sh" "$RN/"
rn() { FOLLOW_POLL=1 bash "$RN/runner.sh" "$@"; }
# A stand-in runner: two lines a few seconds apart, then the end of the sprint.
cat > "$RN/watch.sh" <<'W'
#!/usr/bin/env bash
echo "L1 first"
sleep 3
echo "L2 second"
sleep 1
echo "SWEEP 0 tags= all-sessions-terminal (quiet for 3 sweeps)"
W
# wait_for PID SECONDS -> the exit code, or 124 if it was still running and was killed
wait_for() {
  local i
  for i in $(seq 1 $(( $2 * 4 ))); do
    kill -0 "$1" 2>/dev/null || { wait "$1"; return $?; }
    sleep 0.25
  done
  kill "$1" 2>/dev/null; wait "$1" 2>/dev/null; return 124
}

out="$(rn start "$RN" 7 9)"
case "$out" in "runner: running"*) ok "start brings the runner up" ;; *) no "start brings the runner up" "$out" ;; esac
RPID="$(tr -d '[:space:]' < "$RN/state/runner.pid")"
check "the runner is in its own process session" "own" \
  "$(python3 -c 'import os,sys; print("own" if os.getsid(int(sys.argv[1])) != os.getsid(0) else "shared")' "$RPID" 2>/dev/null)"
case "$(rn start "$RN")" in *"already running"*) ok "a second start starts no second runner" ;; *) no "a second start starts no second runner" "" ;; esac
check "status says running" "0" "$(rn status "$RN" >/dev/null; echo $?)"

# A follower killed after the first line, the way the harness kills a Monitor at its cap.
FOLLOW_POLL=1 bash "$RN/runner.sh" follow "$RN" > "$RN/f1.out" 2>&1 &
F1=$!
sleep 1.5
kill "$F1" 2>/dev/null; wait "$F1" 2>/dev/null
grep -q '^L1 first$' "$RN/f1.out" && ok "the follower prints what the runner said" \
  || no "the follower prints what the runner said" "$(cat "$RN/f1.out")"
check "killing the follower leaves the runner running" "0" "$(rn status "$RN" >/dev/null; echo $?)"

# The next follower - a re-armed Monitor, or a relayed conductor's - picks up where it stopped.
FOLLOW_POLL=1 bash "$RN/runner.sh" follow "$RN" > "$RN/f2.out" 2>&1 &
F2=$!
wait_for "$F2" 15; rc=$?
check "the follower exits when the runner ends the sprint" "0" "$rc"
grep -q '^L1 first$' "$RN/f2.out" && no "a re-armed follower repeats no line" "L1 printed twice" \
  || ok "a re-armed follower repeats no line"
grep -q '^L2 second$' "$RN/f2.out" && grep -q '^SWEEP 0 ' "$RN/f2.out" \
  && ok "and loses no line" || no "and loses no line" "$(cat "$RN/f2.out")"
FOLLOW_POLL=1 bash "$RN/runner.sh" follow "$RN" > "$RN/f3.out" 2>&1 &
F3=$!
wait_for "$F3" 5; rc=$?
check "a follower armed after SWEEP 0 exits at once" "0" "$rc"
check "and restarts no runner the sprint ended on purpose" "1" "$(rn status "$RN" >/dev/null; echo $?)"

# A runner killed mid-run (no SWEEP 0) is started again, with the timings it had.
cat > "$RN/watch.sh" <<'W'
#!/usr/bin/env bash
echo "UP $*"
while true; do sleep 1; done
W
rn start "$RN" 7 9 >/dev/null
OLD="$(tr -d '[:space:]' < "$RN/state/runner.pid")"
sleep 0.5
kill "$OLD"; sleep 0.5
FOLLOW_POLL=1 bash "$RN/runner.sh" follow "$RN" > "$RN/f4.out" 2>&1 &
F4=$!
sleep 3
kill "$F4" 2>/dev/null; wait "$F4" 2>/dev/null
grep -q '^RUNNER-RESTARTED' "$RN/f4.out" && ok "a runner that died mid-run is restarted, and says so once" \
  || no "a runner that died mid-run is restarted, and says so once" "$(cat "$RN/f4.out")"
NEW="$(tr -d '[:space:]' < "$RN/state/runner.pid")"
[ "$NEW" != "$OLD" ] && kill -0 "$NEW" 2>/dev/null && ok "the new runner is alive" \
  || no "the new runner is alive" "old=$OLD new=$NEW"
case "$(ps -o command= -p "$NEW" 2>/dev/null)" in
  *"watch.sh $RN 7 9"*) ok "with the poll and stall it was started with" ;;
  *) no "with the poll and stall it was started with" "$(ps -o command= -p "$NEW" 2>/dev/null)" ;;
esac

# Three restarts inside 30 minutes is a crash loop: say so and stop, do not spin.
kill "$NEW" 2>/dev/null; sleep 0.5
now="$(date +%s)"; printf '%s\n%s\n%s\n' "$now" "$now" "$now" > "$RN/state/.runner-restarts"
FOLLOW_POLL=1 bash "$RN/runner.sh" follow "$RN" > "$RN/f5.out" 2>&1 &
F5=$!
wait_for "$F5" 5; rc=$?
check "a runner that keeps dying ends the follower with exit 1" "1" "$rc"
grep -q '^RUNNER-DOWN' "$RN/f5.out" && ok "and says RUNNER-DOWN" || no "and says RUNNER-DOWN" "$(cat "$RN/f5.out")"
pkill -f "$RN/watch.sh" 2>/dev/null
rm -rf "$RN"

echo
echo "== a runner whose cwd is deleted: unknown is not dead, and one tag keeps one session =="
# The night of 2026-10-04 (machina-stage-c-production). The runner was started from the
# conductor's shell folder, inputs/stage-c-spec/issues. A peer re-copied the spec with `rm -rf` +
# `cp -R` at 07:26, and from then on every `claude` call the runner made failed with "The current
# working directory was deleted". agents_json turned that into `[]`, so a working session was
# called DIED, its stop was a no-op, the resume forked a copy, the id did not resolve, the restart
# added a third session, and DUP saw nothing. It happened on T02, T03 and T04.
DC="$(mktemp -d)"
DBIN="$DC/bin"; mkdir -p "$DBIN" "$DC/wt" "$DC/home/.claude/projects/p"
cp "$HERE/mock-claude.sh" "$DBIN/claude"; chmod +x "$DBIN/claude"
D="$DC/ws"
DSID=c5081c1b-cf5a-4f08-8347-a74c6dd5bf0e
DT="$DC/home/.claude/projects/p/$DSID.jsonl"
dreset() {
  rm -rf "$D" "$DC/mock"; mkdir -p "$D/state" "$DC/mock"
  for f in agents.sh watch.sh revive.sh launch.sh advance.sh close.sh classify-error.sh context-used.sh; do
    cp "$REF/$f" "$D/"
  done
  echo dslug > "$D/SLUG"; echo "$DC/wt" > "$D/WORKTREE"; echo auto > "$D/PERMISSION_MODE"
  echo "do ticket T02" > "$D/prompt-T02.txt"
  echo "$DSID" > "$D/state/T02.session"; mkdir "$D/state/claim-T02"
  : > "$DC/mock/launches"; : > "$DC/mock/stops"
  printf '%s\n' 11111111-0000-4000-8000-000000000001 > "$DC/mock/next-sid"
  echo '{"type":"user","message":{"content":"go"}}' > "$DT"
}
drow() { printf '[{"sessionId":"%s","id":"%s","name":"ns-dslug-T02","state":"%s","status":"%s","pid":%s,"startedAt":1}]' \
           "$DSID" "${DSID:0:8}" "$1" "$2" "$3" > "$DC/mock/agents.json"; }
denv() { MOCK_STATE="$DC/mock" HOME="$DC/home" PATH="$DBIN:$PATH" "$@"; }
dlaunches() { wc -l < "$DC/mock/launches" | tr -d '[:space:]'; }
# One runner process with 1-second polls, as on the night: watch.sh empties its seen-file at
# start, so two `--once` runs never get past the grace poll. Stops once a revive ran, or after $1 s.
drunner() {
  # Not through denv: `func &` forks a subshell, and killing that leaves watch.sh running.
  MOCK_STATE="$DC/mock" HOME="$DC/home" PATH="$DBIN:$PATH" bash "$D/watch.sh" "$D" 1 25 >/dev/null 2>&1 &
  local w=$! i=0
  while [ "$i" -lt "$1" ]; do
    grep -qE '^[0-9TZ:-]+ revive\(' "$D/state/EVENTS.log" 2>/dev/null && break
    sleep 1; i=$((i + 1))
  done
  kill "$w" 2>/dev/null; wait "$w" 2>/dev/null
}
# A live session: a real process, a `working busy` row, and a transcript touched every second.
sleep 600 & DPID=$!
( while kill -0 "$DPID" 2>/dev/null; do touch "$DT" 2>/dev/null; sleep 1; done ) & DTOUCH=$!

dreset; drow working busy "$DPID"
mkdir "$DC/gone"
( cd "$DC/gone" && rmdir "$DC/gone" && drunner 12 )
check "a runner started in a since-deleted folder launches nothing on top of a live session" "0" "$(dlaunches)"
grep -q "DIED T02" "$D/state/EVENTS.log" 2>/dev/null \
  && no "it does not call the live session DIED" "$(grep DIED "$D/state/EVENTS.log")" \
  || ok "it does not call the live session DIED"
check "the session file still names the live session" "$DSID" "$(cat "$D/state/T02.session")"
kill -0 "$DPID" 2>/dev/null && ok "the live session's process was not stopped" \
  || no "the live session's process was not stopped" "it was killed"

dreset; drow working busy "$DPID"; echo 1 > "$DC/mock/agents-fail"
( cd "$DC/wt" && drunner 6 )
check "an agent list that cannot be read revives nothing" "0" "$(dlaunches)"
grep -q "EMIT AGENTS-UNREADABLE" "$D/state/EVENTS.log" \
  && ok "and says AGENTS-UNREADABLE once it has failed three sweeps" \
  || no "and says AGENTS-UNREADABLE once it has failed three sweeps" "$(tail -3 "$D/state/EVENTS.log")"
( . "$D/agents.sh"; denv agents_json >/dev/null 2>&1 ) \
  && no "agents_json returns non-zero when the CLI fails" "it returned 0" \
  || ok "agents_json returns non-zero when the CLI fails"
rm -f "$DC/mock/agents-fail"

# A live process whose row reads `idle` between model calls, transcript still growing. The old
# guard looked at the transcript only when the harness said `busy`, so this was stopped and forked.
dreset; drow working idle "$DPID"; sleep 1
rc="$(cd "$DC/wt" && denv bash "$D/revive.sh" "$D" T02 idle >/dev/null 2>&1; echo $?)"
check "revive.sh refuses a live session whose transcript is still growing, whatever its status" "1" "$rc"
check "and launches nothing" "0" "$(dlaunches)"

# The harness says it in words when a resume finds the session still running.
dreset; drow working idle null; echo 1 > "$DC/mock/fork-note"
python3 -c 'import os,sys,time; t=time.time()-900; os.utime(sys.argv[1],(t,t))' "$DT"
kill "$DTOUCH" 2>/dev/null
rc="$(cd "$DC/wt" && denv bash "$D/revive.sh" "$D" T02 ended-without-signal >/dev/null 2>&1; echo $?)"
check "a resume that forked a live session spends no rung and does not restart" "1" "$rc"
check "exactly one launch (the copy), no restart on top of it" "1" "$(dlaunches)"
grep -q '^stop 11111111$' "$DC/mock/stops" && ok "the copy is stopped by its short id" \
  || no "the copy is stopped by its short id" "$(cat "$DC/mock/stops")"
check "the original stays in the session file" "$DSID" "$(cat "$D/state/T02.session")"
grep -q '^forked-stopped ' "$D/state/T02.revivals" && ok "the ledger says forked-stopped" \
  || no "the ledger says forked-stopped" "$(cat "$D/state/T02.revivals" 2>/dev/null)"
rm -f "$DC/mock/fork-note"

# A resume that started (rc=0) but whose id does not resolve must not fall through to a restart.
dreset; drow working idle null; echo 0 > "$DC/mock/register"
python3 -c 'import os,sys,time; t=time.time()-900; os.utime(sys.argv[1],(t,t))' "$DT"
printf '[]' > "$DC/mock/agents.json"
(cd "$DC/wt" && denv bash "$D/revive.sh" "$D" T02 ended-without-signal >/dev/null 2>&1)
check "a started resume is never followed by a restart" "1" "$(dlaunches)"
check "it is tracked by the short id its banner printed" "11111111" "$(cat "$D/state/T02.session")"

# launch.sh: a new session the list does not show yet is still tracked, by its banner.
dreset; rm -rf "$D/state/claim-T02" "$D/state/T02.session"; echo 0 > "$DC/mock/register"
printf '[]' > "$DC/mock/agents.json"
(cd "$DC/wt" && denv bash "$D/launch.sh" "$D" T02 >/dev/null 2>&1)
check "launch.sh falls back to the banner's short id, not 'unresolved'" "11111111" "$(cat "$D/state/T02.session")"
rm -f "$DC/mock/register"

# DUP is checked on a tag that already wrote DONE: T02 had three live sessions when its DONE landed.
dreset; echo DONE > "$D/state/T02.status"; : > "$D/state/.advanced-T02"; : > "$D/state/.closed-T02"
printf '[{"sessionId":"%s","id":"c5081c1b","name":"ns-dslug-T02","state":"working","status":"busy","pid":%s,"startedAt":1},{"sessionId":"8afc87c2-0000-4000-8000-000000000001","id":"8afc87c2","name":"ns-dslug-T02-r1","state":"working","status":"busy","pid":%s,"startedAt":2}]' \
  "$DSID" "$DPID" "$DPID" > "$DC/mock/agents.json"
(cd "$DC/wt" && denv bash "$D/watch.sh" "$D" 0 25 --once >/dev/null 2>&1)
grep -q "EMIT DUP T02 8afc87c2 c5081c1b" "$D/state/EVENTS.log" \
  && ok "DUP fires on a tag with a status when two sessions are live" \
  || no "DUP fires on a tag with a status when two sessions are live" "$(grep -c DUP "$D/state/EVENTS.log")"

grep -q 'cd "$WS"' "$REF/runner.sh" && ok "runner.sh starts the runner from the workspace, not the caller's cwd" \
  || no "runner.sh starts the runner from the workspace, not the caller's cwd" "no cd"
kill "$DPID" "$DTOUCH" 2>/dev/null; wait "$DPID" "$DTOUCH" 2>/dev/null
pkill -f "$D/watch.sh" 2>/dev/null
rm -rf "$DC"

echo
echo "== the docs arm a follower, never the runner itself =="
SK="$HERE/../SKILL.md"
NMD="$HERE/../../night-marathon"
grep -q 'persistent: true' "$SK" && no "SKILL.md no longer promises a persistent Monitor" "the harness caps every Monitor at 30m" \
  || ok "SKILL.md no longer promises a persistent Monitor"
bad="$(grep -n -E 'Monitor[^.|]*`?(bash )?<WS>/watch\.sh|watch\.sh[^.|]*under (a|the) (persistent )?`?Monitor' \
        "$SK" "$REF"/*.md "$NMD"/references/*.md "$HERE/../../product-research/references/"*.md 2>/dev/null)"
[ -z "$bad" ] && ok "no doc tells a conductor to run watch.sh under its Monitor" \
  || no "no doc tells a conductor to run watch.sh under its Monitor" "$bad"
for f in "$SK" "$REF/research-mode.md" "$NMD/references/build-prompt.md" \
         "$HERE/../../product-research/references/conductor-prompt.md"; do
  label="$(basename "$(cd "$(dirname "$f")" && pwd)")/$(basename "$f")"
  grep -q 'runner.sh follow' "$f" && ok "$label arms the follower" || no "$label arms the follower" "no runner.sh follow"
done
grep -q 'phase-chain.sh init <WS>/phases <NS>/references <SLUG> <CONTEXT_WINDOW>' "$NMD/SKILL.md" \
  && ok "night-marathon passes the context window to the phase chain" \
  || no "night-marathon passes the context window to the phase chain" "init has no window"
grep -q 'CONDUCTOR.waiting-on-user' "$NMD/references/conductor-prompt.md" \
  && ok "the review gate marks its wait on a person" \
  || no "the review gate marks its wait on a person" "no waiting-on-user marker"

echo
echo "== codex-bridge: the plugin ships the MCP server night-marathon consults =="
PLUGIN="$HERE/../../.."
CB="$PLUGIN/mcp/codex-bridge/server.py"
python3 -c 'import json,sys; a=json.load(open(sys.argv[1]))["mcpServers"]["codex-bridge"]["args"]; sys.exit(0 if a==["${CLAUDE_PLUGIN_ROOT}/mcp/codex-bridge/server.py"] else 1)' "$PLUGIN/.mcp.json" 2>/dev/null \
  && ok "the plugin .mcp.json registers codex-bridge from the plugin root" \
  || no "the plugin .mcp.json registers codex-bridge from the plugin root" "missing or wrong args"
CBH="$(mktemp -d)"
tools=$(printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | CODEX_BRIDGE_HOME="$CBH" python3 "$CB" 2>/dev/null \
  | python3 -c 'import sys,json; print(" ".join(t["name"] for l in sys.stdin for t in json.loads(l).get("result",{}).get("tools",[])))')
missing=""
for t in codex_ask codex_check codex_cancel codex_status; do
  case " $tools " in *" $t "*) ;; *) missing="$missing $t" ;; esac
done
[ -z "$missing" ] \
  && ok "the bundled server lists codex_ask, codex_check, codex_cancel and codex_status" \
  || no "the bundled server lists codex_ask, codex_check, codex_cancel and codex_status" "missing:$missing"
cbcall() {
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":$1}" \
    | CODEX_BRIDGE_HOME="$CBH" CODEX_BIN=/nonexistent/codex python3 "$CB" 2>/dev/null | tail -1
}
cbcall '{"name":"codex_status","arguments":{}}' | grep -q 'ready: no.*npm install -g @openai/codex' \
  && ok "without codex, codex_status says not ready and how to install it" \
  || no "without codex, codex_status says not ready and how to install it" "no install hint"
cbcall "{\"name\":\"codex_ask\",\"arguments\":{\"prompt\":\"hi\",\"cwd\":\"$CBH\"}}" | grep 'was not found' | grep -q '"isError": true' \
  && ok "without codex, codex_ask fails at once with a clear error" \
  || no "without codex, codex_ask fails at once with a clear error" "no clear error"
[ ! -d "$CBH/runs" ] || [ -z "$(ls -A "$CBH/runs")" ] \
  && ok "and leaves no empty run behind" \
  || no "and leaves no empty run behind" "$(ls "$CBH/runs")"
rm -rf "$CBH"

echo
echo "== night-watch draws progress from the workspace files, and only reads them =="
NW="$HERE/../../../bin/night-watch"
NWR="$(mktemp -d)"
nw() { COLUMNS=140 NO_COLOR=1 python3 "$NW" --once --root "$NWR" "$@" 2>&1; }

# A sprint mid-relay: T02 handed on to T02c2, which rewrote T02.next, so nothing points at T03 yet.
S="$NWR/relay-sprint"; mkdir -p "$S/state/claim-T01" "$S/state/claim-T02" "$S/state/claim-T02c2"
printf 'T02\n' > "$S/state/T01.next";  printf 'DONE\n' > "$S/state/T01.status"
printf 'T02c2\n' > "$S/state/T02.next"; printf 'RELAYED: T02c2\n' > "$S/state/T02.status"
printf 'REVIEW-FINAL\n' > "$S/state/T03.next"
printf 'FIX-FINAL\n' > "$S/state/REVIEW-FINAL.next"; : > "$S/state/FIX-FINAL.next"
printf 'aaaabbbb-0000-0000-0000-000000000000\n' > "$S/state/T02c2.session"
printf '%s bootstrap workspace ready\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$S/state/EVENTS.log"
out="$(nw relay)"
printf '%s' "$out" | grep -q '1/5' && ok "a relay is one stage: 1 of 5 done" || no "a relay is one stage: 1 of 5 done" "$out"
printf '%s' "$out" | grep -q 'T02c2 running.*session 2.*claude attach aaaabbbb' \
  && ok "the running continuation, its session count and attach id" || no "the running continuation, its session count and attach id" "$out"
printf '%s' "$out" | grep -q 'next: T03 REVIEW-FINAL FIX-FINAL' \
  && ok "the chain continues past the relay to T03" || no "the chain continues past the relay to T03" "$out"
printf '%s' "$out" | grep -q 'runner is not running' \
  && ok "a started sprint with no runner is flagged" || no "a started sprint with no runner is flagged" "$out"

# A review-mode marathon whose plan is done: the next move is the user's.
M="$NWR/gate-marathon"; mkdir -p "$M/phases/state/claim-CONDUCTOR" "$M/state/claim-T01" "$M/state/claim-SYNTH"
: > "$M/phases/PHASE_CHAIN"; printf 'MARATHON_MODE=review\n' > "$M/facts.env"
printf 'BUILD\n' > "$M/phases/state/CONDUCTOR.next"
printf 'ccccdddd-0000-0000-0000-000000000000\n' > "$M/phases/state/CONDUCTOR.session"
: > "$M/phases/state/CONDUCTOR.waiting-on-user"
printf '%s phase chain ready\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$M/phases/state/EVENTS.log"
printf 'SYNTH\n' > "$M/state/T01.next"; printf 'DONE\n' > "$M/state/T01.status"
: > "$M/state/SYNTH.next"; printf 'DONE\n' > "$M/state/SYNTH.status"
out="$(nw gate)"
printf '%s' "$out" | grep -q 'waiting for your picks - `claude attach ccccdddd`' \
  && ok "a marathon at the review gate asks for the picks" || no "a marathon at the review gate asks for the picks" "$out"
printf '%s' "$out" | grep -q 'stage 3 of 4 (Your picks)' \
  && ok "and counts Research, Plan, picks, Build as its stages" || no "and counts Research, Plan, picks, Build as its stages" "$out"

# Abandoned a week ago: off the board by default, on it (dim, not urgent) with --all.
O="$NWR/old-sprint"; mkdir -p "$O/state/claim-T01"
printf 'T02\n' > "$O/state/T01.next"; : > "$O/state/T02.next"
find "$O" -exec touch -t 202601010000 {} +
nw | grep -q old-sprint && no "a week-old unfinished sprint is hidden" "shown" || ok "a week-old unfinished sprint is hidden"
nw --all | grep -q '◌ old-sprint.*stale' && ok "--all shows it as stale" || no "--all shows it as stale" "$(nw --all)"

# The 2026-09 kickoff that wrote `T01 T02.next`: no chain, so no run.
B="$NWR/broken-kickoff"; mkdir -p "$B/state"; : > "$B/state/T01 T02.next"
nw --all | grep -q broken-kickoff && no "tags with spaces are not a chain" "shown" || ok "tags with spaces are not a chain"

before="$(find "$NWR" -newer "$S/state/EVENTS.log" -type f | wc -l | tr -d ' ')"
nw >/dev/null; nw --all >/dev/null
check "it writes nothing into a workspace" "$before" "$(find "$NWR" -newer "$S/state/EVENTS.log" -type f | wc -l | tr -d ' ')"
rm -rf "$NWR"

echo
echo "== the SessionStart hook links night-watch onto PATH, and never over somebody else's file =="
LH="$HERE/../../../hooks/link-night-watch.sh"
FH="$(mktemp -d)"; mkdir -p "$FH/.local/bin" "$FH/plug/amit-mizrachi/bin"
cp "$NW" "$FH/plug/amit-mizrachi/bin/night-watch"
run_hook() { HOME="$FH" PATH="$FH/.local/bin:/usr/bin:/bin" CLAUDE_PLUGIN_ROOT="$FH/plug/amit-mizrachi" bash "$LH"; }
out="$(run_hook)"
check "it prints nothing (SessionStart stdout is context)" "" "$out"
check "it links into the first bin dir on PATH" "$FH/plug/amit-mizrachi/bin/night-watch" "$(readlink "$FH/.local/bin/night-watch")"
ln -sfn "$FH/gone/amit-mizrachi/bin/night-watch" "$FH/.local/bin/night-watch"; run_hook
check "it re-points a link left by an old plugin version" "$FH/plug/amit-mizrachi/bin/night-watch" "$(readlink "$FH/.local/bin/night-watch")"
rm "$FH/.local/bin/night-watch"; printf 'mine\n' > "$FH/.local/bin/night-watch"; run_hook
check "it leaves a real file of the same name alone" "mine" "$(command cat "$FH/.local/bin/night-watch")"
rm -rf "$FH"

# --- CI is handed off, never waited on. ci-watch.sh starts ONE watcher outside the chain.
echo
echo "== ci-watch.sh hands CI to a watcher and returns =="
CW="$(mktemp -d)"
CWB="$CW/bin"; mkdir -p "$CWB" "$CW/ws/state"
cp "$HERE/mock-claude.sh" "$CWB/claude"; chmod +x "$CWB/claude"
cat > "$CWB/gh" <<'GH'
#!/usr/bin/env bash
# mock gh: `pr view [N] --json number|headRefOid -q ...`
case "$*" in
  *number*)     cat "$MOCK_STATE/gh-pr" 2>/dev/null ;;
  *headRefOid*) printf 'abc1234\n' ;;
esac
GH
chmod +x "$CWB/gh"
for f in agents.sh ci-watch.sh ci-watch-prompt.md; do cp "$REF/$f" "$CW/ws/$f"; done
# A real (local) remote, so the watcher's worktree can be made from origin/<branch>.
git init -q --bare "$CW/remote.git"
git init -q -b feat/x "$CW/wt"
git -C "$CW/wt" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$CW/wt" remote add origin "$CW/remote.git"
git -C "$CW/wt" push -q origin feat/x
printf '%s\n' "$CW/wt" > "$CW/ws/WORKTREE"
printf 'feat/x\n' > "$CW/ws/BRANCH"
printf 'cslug\n'  > "$CW/ws/SLUG"
printf 'auto\n'   > "$CW/ws/PERMISSION_MODE"
export MOCK_STATE="$CW/mock"; mkdir -p "$MOCK_STATE"; printf '[]' > "$MOCK_STATE/agents.json"
cw() { PATH="$CWB:$PATH" bash "$CW/ws/ci-watch.sh" "$CW/ws" >/dev/null 2>&1; echo $?; }
launches() { grep -c 'ns-cslug-ci-watch' "$MOCK_STATE/launches" 2>/dev/null || echo 0; }

check "no PR yet: exit 2" "2" "$(cw)"
check "no PR yet: nothing launched" "0" "$(launches)"

printf '41\n' > "$MOCK_STATE/gh-pr"
check "with a PR: exit 0" "0" "$(cw)"
check "one watcher launched" "1" "$(launches)"
case "$(cat "$CW/ws/state/ACCEPTANCE.verdict")" in
  PENDING\ abc1234*) ok "ACCEPTANCE.verdict reads PENDING at the pushed head" ;;
  *) no "ACCEPTANCE.verdict reads PENDING at the pushed head" "got: $(cat "$CW/ws/state/ACCEPTANCE.verdict")" ;;
esac
[ -d "$CW/wt-ci" ] && ok "the watcher gets its own worktree" || no "the watcher gets its own worktree" "no $CW/wt-ci"
case "$(awk '{print $4}' "$MOCK_STATE/launches")" in
  *wt-ci) ok "it runs in that worktree, not the sprint's" ;;
  *) no "it runs in that worktree, not the sprint's" "ran in $(awk '{print $4}' "$MOCK_STATE/launches")" ;;
esac
if ls "$CW/ws/state/"*.session "$CW/ws/state/"*.status "$CW/ws/state/"claim-* >/dev/null 2>&1; then
  no "nothing lands where watch.sh globs (state/*.session, *.status, claim-*)" "$(ls "$CW/ws/state")"
else
  ok "nothing lands where watch.sh globs (state/*.session, *.status, claim-*)"
fi
grep -q '<PR>\|<WS>\|<CI_WORKTREE>\|<BRANCH>' "$MOCK_STATE/last-prompt" \
  && no "the watcher prompt is fully filled" "an unfilled slot remains" \
  || ok "the watcher prompt is fully filled"

# Alive: the harness lists it with a pid and not done -> a second call is a no-op.
python3 - "$MOCK_STATE/agents.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
for r in rows: r["pid"] = 4242
json.dump(rows, open(sys.argv[1], "w"))
PY
check "second call while alive: exit 0" "0" "$(cw)"
check "second call while alive: still one watcher" "1" "$(launches)"

# Finished: a later push (FIX-TEST) gets a fresh watcher, and the old record is kept.
echo DONE > "$CW/ws/state/ci-watch/status"
check "after the watcher finished: exit 0" "0" "$(cw)"
check "after the watcher finished: a fresh watcher" "2" "$(launches)"
ls "$CW/ws/state/ci-watch/status."* >/dev/null 2>&1 && ok "the finished watcher's status is archived" \
  || no "the finished watcher's status is archived" "$(ls "$CW/ws/state/ci-watch")"
rm -rf "$CW"

echo
echo "== no sprint session waits on CI =="
grep -q 'bash <WS>/ci-watch.sh <WS>' "$REF/review-fix-prompt.md" \
  && ok "FIX-FINAL hands CI to the watcher" || no "FIX-FINAL hands CI to the watcher" "no ci-watch.sh call"
grep -q '^    bash <WS>/accept.sh' "$REF/review-fix-prompt.md" \
  && no "FIX-FINAL no longer blocks on accept.sh" "it still runs accept.sh" \
  || ok "FIX-FINAL no longer blocks on accept.sh"
grep -q 'ci-watch.sh' "$REF/review-find-prompt.md" \
  && ok "a FINAL review that routes SKIP hands CI on" || no "a FINAL review that routes SKIP hands CI on" "no ci-watch.sh"
grep -q 'accept\.sh' "$REF/review-find-prompt.md" \
  && no "the finder never runs accept.sh" "it still does" || ok "the finder never runs accept.sh"

echo
echo "== the CI watcher fixes red checks, inherited ones too =="
grep -q 'red on the base branch too - gets ONE' "$REF/ci-watch-prompt.md" \
  && no "a base-branch failure is not a rerun-and-stop" "the old escape hatch is back" \
  || ok "a base-branch failure is not a rerun-and-stop"
grep -q 'That includes a check that is red on the base branch too' "$REF/ci-watch-prompt.md" \
  && ok "a base-branch failure goes to the fix step" || no "a base-branch failure goes to the fix step" "no such rule"
grep -q 'BLOCKED is for exactly two cases' "$REF/ci-watch-prompt.md" \
  && ok "BLOCKED is narrowed to two cases" || no "BLOCKED is narrowed to two cases" "no such rule"
grep -qF 'gh pr view ${BRANCH:+"$BRANCH"}' "$REF/accept.sh" \
  && ok "accept.sh finds the PR by branch, so a detached watcher worktree works" \
  || no "accept.sh finds the PR by branch, so a detached watcher worktree works" "bare gh pr view"

echo
echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
