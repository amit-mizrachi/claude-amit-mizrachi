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
# launcher, a reviver, a runner and a handback that all fail before doing anything.
for need in agents.sh launch.sh advance.sh watch.sh revive.sh classify-error.sh \
            context-used.sh handback.sh accept.sh render.sh continuation-prompt.md; do
  [ -f "$BWS/$need" ] && ok "copied $need" || no "copied $need" "absent from $BWS"
done
check "PERMISSION_MODE defaults to auto" "auto" "$(cat "$BWS/PERMISSION_MODE")"
check "CONTEXT_WINDOW derived from facts.env" "1000000" "$(cat "$BWS/CONTEXT_WINDOW")"
check "VERIFY derived whole, spaces and all" "pnpm nx affected -t typecheck test lint" "$(cat "$BWS/VERIFY")"
check "FORMAT_CHECK derived for handback" "pnpm format:check" "$(cat "$BWS/FORMAT_CHECK" 2>/dev/null)"

# Tests run once, at the end, in FIX-FINAL. Nothing before it may be told to run the suite.
for f in implementer-prompt.md continuation-prompt.md review-fix-prompt.md review-find-prompt.md; do
  grep -q 'TESTS RUN ONCE, AT THE END, IN FIX-FINAL\|Tests run once in this sprint, at the end, in FIX-FINAL' "$REF/$f" \
    && ok "$f carries the tests-once rule" || no "$f carries the tests-once rule" "rule missing"
done
# The repo's own "run the tests before you commit" must not win over the sprint's rule.
for f in implementer-prompt.md continuation-prompt.md review-fix-prompt.md handback.sh; do
  grep -q 'skip that until FIX-FINAL' "$REF/$f" \
    && ok "$f overrides a repo rule to test before commit" || no "$f overrides a repo rule to test before commit" "override missing"
done
if grep -q 'verify green' "$REF/revive.sh"; then
  no "revive does not tell a resumed session to run the suite" "revive.sh still says verify green"
else
  ok "revive does not tell a resumed session to run the suite"
fi
if grep -q '\$VERIFY' "$REF/handback.sh"; then
  no "handback (checkpoint fixes only) does not run the test suite" "handback.sh still uses \$VERIFY"
else
  ok "handback (checkpoint fixes only) does not run the test suite"
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
grep -q 'gh pr view --json number' "$REF/review-find-prompt.md" \
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

# --- F3: handback must not drop a rendered prompt's acceptance obligations.
HWS="$MWS/hb"; mkdir -p "$HWS/state"
for f in agents.sh handback.sh context-used.sh; do cp "$REF/$f" "$HWS/"; done
printf '%s\n' "$MWS/wt" > "$HWS/WORKTREE"
printf 'mslug\n' > "$HWS/SLUG"
printf 'auto\n' > "$HWS/PERMISSION_MODE"
printf 'F1 something\n' > "$HWS/findings.md"
printf 'work the list, then: bash <WS>/accept.sh <WS>\n' > "$HWS/prompt-FIX-FINAL.txt"
out="$(PATH="$MBIN:$PATH" bash "$HWS/handback.sh" "$HWS" FIX-FINAL T07 "$HWS/findings.md" 2>&1)"; rc=$?
check "F3 handback refuses a tag whose prompt has an acceptance gate" "1" "$rc"
case "$out" in
  *"acceptance gate"*) ok "F3 it says why, so the caller launches the rendered fixer" ;;
  *) no "F3 it says why, so the caller launches the rendered fixer" "got: $out" ;;
esac
[ ! -d "$HWS/state/claim-FIX-FINAL" ] && ok "F3 it leaves no claim behind for the fallback" \
  || no "F3 it leaves no claim behind for the fallback" "claim-FIX-FINAL exists, so launch.sh would no-op"
grep -q 'a FINAL review always launches its rendered fixer' "$REF/review-find-prompt.md" \
  && ok "F3 the finder is told not to hand back on a FINAL review" \
  || no "F3 the finder is told not to hand back on a FINAL review" "no such rule"

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
rm -rf "$QWS"

echo
echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
