#!/usr/bin/env bash
# wizard-dryrun.sh - drive a wizard's stage machine without touching anything real.
#
#   wizard-dryrun.sh <wizard.sh> <template.sh> [--repo <checkout>] [--verdict <file>]
#
# WHY IT EXISTS. A wizard is a state machine: stages run in an order, each one can fail, and
# what a later stage is allowed to do depends on what an earlier one did. The rule used to be
# "bash -n, shellcheck, and trace it on paper". Reading found the typos and missed every
# ordering defect. One 713-line wizard shipped with an apply that ignored its helper's return
# value, a probe that ran before the restart it was measuring, a failed canary that fell
# through into the stages after it, and a default checkout that was wrong only in combination
# with a warning four stages earlier. None of those is visible in a diff. All of them are
# visible the moment the path is driven.
#
# WHAT IT DOES. The wizard library above the STAGES marker is byte-identical in every wizard,
# which is what makes this cheap: the harness throws that half away and substitutes its own,
# with the same names and the same semantics but no blocking reads, no browser, and a trace
# line per event. The authored half runs unmodified. Every external command resolves to a shim
# that records its argv and returns what the scenario says. Then it drives the wizard once per
# branch - defaults taken, values given, each confirm declined in turn, each mutating command
# failed in turn - and checks the traces against the stage contract the author declared.
#
# NOTHING REAL CAN BE REACHED. PATH holds the shim directory and nothing else, so an unshimmed
# binary is "command not found" rather than a live apply; HOME and the working directory are
# both inside a temporary sandbox. The harness adds a shim and retries when a run dies that
# way, so the fail-closed default costs nothing.
#
# Exits 0 when every check passes, 1 when any fails, 2 when the wizard could not be driven.

set -uo pipefail

WIZ="${1:?usage: wizard-dryrun.sh <wizard.sh> <template.sh> [--verdict <file>]}"
TPL="${2:?usage: wizard-dryrun.sh <wizard.sh> <template.sh> [--verdict <file>]}"
shift 2
VERDICT_FILE=""
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --verdict) VERDICT_FILE="${2:-}"; shift 2 ;;
    --repo)    REPO="${2:-}"; shift 2 ;;
    *) echo "wizard-dryrun: unknown argument $1" >&2; exit 2 ;;
  esac
done

for f in "$WIZ" "$TPL"; do
  [ -f "$f" ] || { echo "wizard-dryrun: no such file: $f" >&2; exit 2; }
done

verdict() {
  [ -n "$VERDICT_FILE" ] && printf '%s\n' "$1" > "$VERDICT_FILE"
  return 0
}

SBX="$(mktemp -d)"
# DR_KEEP=1 leaves the sandbox and every trace behind, which is how you read what a scenario
# actually did rather than arguing with the finding.
if [ -n "${DR_KEEP:-}" ]; then
  echo "wizard-dryrun: sandbox $SBX"
else
  trap 'rm -rf "${SBX:?}"' EXIT
fi
mkdir -p "$SBX/bin" "$SBX/home" "$SBX/work" "$SBX/traces"

# --- 1. split each file at the STAGES marker -------------------------------------------------
marker_of() { grep -n '^# STAGES:' "$1" | head -1 | cut -d: -f1; }
M_WIZ="$(marker_of "$WIZ")"
M_TPL="$(marker_of "$TPL")"
if [ -z "$M_WIZ" ]; then
  echo "wizard-dryrun: $WIZ has no '# STAGES:' marker - it was not built from the template" >&2
  verdict "FAIL"; exit 2
fi
[ -n "$M_TPL" ] || { echo "wizard-dryrun: $TPL has no '# STAGES:' marker" >&2; exit 2; }

head -n "$((M_WIZ - 1))" "$WIZ" > "$SBX/lib-authored.txt"
head -n "$((M_TPL - 1))" "$TPL" > "$SBX/lib-template.txt"
tail -n +"$M_WIZ" "$WIZ" > "$SBX/stages.sh"

# The "never hand-edit the library" rule, enforced instead of asked for. A wizard whose library
# has drifted is one this harness models wrongly, so the check has to come before the driving.
if ! diff -q "$SBX/lib-template.txt" "$SBX/lib-authored.txt" >/dev/null 2>&1; then
  echo "FAIL  the wizard library above the STAGES marker was hand-edited:"
  diff "$SBX/lib-template.txt" "$SBX/lib-authored.txt" | head -40
  verdict "FAIL"; exit 1
fi

# --- 2. the instrumented library ------------------------------------------------------------
# Same names, same signatures, same semantics as template.sh - including the `ENV_FILE` default,
# which one wizard's out-of-repo rollout file was silently losing to. Only the blocking reads,
# the browser and the terminal control are replaced.
cat > "$SBX/lib.sh" <<'INSTRUMENTED'
#!/usr/bin/env bash
set -euo pipefail

BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""

TOTAL_STAGES=0
_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()
WRITTEN_SECRET=()
SKIPPED=()

_DR_CONFIRM=0

_dr() { printf '%s\n' "$*" >> "$DR_TRACE"; }

_clear() { return 0; }

banner() { _dr "BANNER|$1"; }

stage() {
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  _dr "STAGE|$_STAGE_INDEX|$1"
}

say()  { _dr "TEXT|$1"; }
step() { _dr "TEXT|$1"; }
note() { _dr "TEXT|$1"; }
warn() { _dr "TEXT|$1"; }

open_url() { _dr "URL|$1"; }

pause() { _dr "PAUSE|${1:-}"; }

# confirm answers per scenario: DR_CONFIRM_NO is the 1-based index to decline, 0 for none.
confirm() {
  _DR_CONFIRM=$((_DR_CONFIRM + 1))
  local answer="yes"
  [ "$_DR_CONFIRM" = "${DR_CONFIRM_NO:-0}" ] && answer="no"
  _dr "CONFIRM|$_DR_CONFIRM|$1|$answer"
  [ "$answer" = "yes" ]
}

_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

# DR_ASK_MODE=default feeds an empty answer, exactly as a human pressing Enter does, so the
# stage's own fallback runs and a wrong default becomes visible. DR_ASK_MODE=value feeds a
# sentinel, which is what makes "no secret is ever an argument" checkable in the trace.
_dr_answer() {
  local key="$1" kind="$2" current="$3"
  if [ "${DR_ASK_MODE:-value}" = "default" ]; then
    printf '%s' "$current"
  elif [ "$kind" = "secret" ]; then
    printf '__DRSECRET_%s__' "$key"
  else
    printf '__DRVALUE_%s__' "$key"
  fi
}

ask() {
  local key="$1" current input
  current=$(_existing "$key" || true)
  input="$(_dr_answer "$key" plain "$current")"
  _dr "ASK|$key"
  printf -v "$key" '%s' "$input"
}

ask_secret() {
  local key="$1" current input
  current=$(_existing "$key" || true)
  input="$(_dr_answer "$key" secret "$current")"
  _dr "SECRET|$key"
  printf -v "$key" '%s' "$input"
}

write_env() {
  local key="$1" value="$2" tmp abs
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  abs="$ENV_FILE"
  case "$abs" in /*) ;; *) abs="$PWD/$abs" ;; esac
  _dr "ENV|$key|$abs"
}

set_secret() { WRITTEN_SECRET+=("$1"); _dr "GHSECRET|$1|$2"; }
set_var()    { _dr "GHVAR|$1|$2"; }

finish() { _dr "FINISH|"; }
INSTRUMENTED

# --- 3. the shims ---------------------------------------------------------------------------
# One executable, hard-linked under every name. It records the call, honours DR_FAIL_AT, and
# creates any file an argument names as an output so a saved plan is observable downstream.
cat > "$SBX/shim" <<'SHIM'
#!/usr/bin/env bash
n=$(( $(cat "$DR_EXEC_COUNT" 2>/dev/null || echo 0) + 1 ))
printf '%s' "$n" > "$DR_EXEC_COUNT"
rc=0
[ "$n" = "${DR_FAIL_AT:-0}" ] && rc=1
printf 'EXEC|%s|%s|rc=%s\n' "$n" "$(basename "$0")$(printf ' %s' "$@")" "$rc" >> "$DR_TRACE"
if [ "$rc" = 0 ]; then
  for a in "$@"; do
    case "$a" in
      -out=*|--out=*|-o=*|--output=*) : > "${a#*=}" 2>/dev/null || true ;;
    esac
  done
fi
exit "$rc"
SHIM
chmod +x "$SBX/shim"

SAFE="bash sh cat grep sed mktemp mv rm touch date tr wc dirname basename mkdir head tail \
      cut sort uniq awk ls test true false sleep env diff"
for c in $SAFE; do
  p="$(command -v "$c" 2>/dev/null)" && ln -sf "$p" "$SBX/bin/$c"
done
add_shim() { [ -e "$SBX/bin/$1" ] || cp "$SBX/shim" "$SBX/bin/$1"; }
# The tools a wizard reaches for most; the retry loop below adds anything else it needs.
for c in terraform tofu terragrunt pulumi aws gcloud az kubectl helm gh git psql mysql \
         wrangler flyctl doctl heroku vercel netlify supabase stripe curl wget npm pnpm \
         yarn bun docker make python3 node open xdg-open wslview explorer.exe tput; do
  add_shim "$c"
done

# --- 4. drive it ------------------------------------------------------------------------------
# The sandbox is a skeleton of the real checkout - every tracked path as an empty file - and the
# wizard sits at its real relative path inside it. Without that, a stage guarded by
# `[[ -d "$unit_dir" ]]` short-circuits, the mutating half never runs, and the harness reports a
# clean sheet for a path it never drove.
RUN_REL="$(basename "$WIZ")"
if [ -n "$REPO" ] && [ -d "$REPO" ]; then
  abs_wiz="$(cd "$(dirname "$WIZ")" && pwd)/$(basename "$WIZ")"
  abs_repo="$(cd "$REPO" && pwd)"
  case "$abs_wiz" in "$abs_repo"/*) RUN_REL="${abs_wiz#"$abs_repo"/}" ;; esac
fi

build_work() {
  rm -rf "${SBX:?}/work" "${SBX:?}/home"; mkdir -p "$SBX/work" "$SBX/home"
  if [ -n "$REPO" ] && [ -d "$REPO" ]; then
    ( cd "$REPO" && git ls-files 2>/dev/null ) | while IFS= read -r p; do
        mkdir -p "$SBX/work/$(dirname "$p")" 2>/dev/null && : > "$SBX/work/$p" 2>/dev/null
      done
  fi
  mkdir -p "$(dirname "$SBX/work/$RUN_REL")"
  cat "$SBX/lib.sh" "$SBX/stages.sh" > "$SBX/work/$RUN_REL"
}

# dr_run NAME CONFIRM_NO ASK_MODE FAIL_AT
dr_run() {
  local name="$1" confirm_no="$2" ask_mode="$3" fail_at="$4"
  local trace="$SBX/traces/$name" tries=0 missing
  while [ "$tries" -lt 25 ]; do
    tries=$((tries + 1))
    build_work
    : > "$trace"; : > "$SBX/count"
    ( cd "$SBX/work" && env -i \
        PATH="$SBX/bin" HOME="$SBX/home" TERM=dumb LANG=C \
        DR_TRACE="$trace" DR_EXEC_COUNT="$SBX/count" \
        DR_CONFIRM_NO="$confirm_no" DR_ASK_MODE="$ask_mode" DR_FAIL_AT="$fail_at" \
        bash "$SBX/work/$RUN_REL" ) >"$SBX/out" 2>"$SBX/err"
    printf 'EXIT|%s\n' "$?" >> "$trace"
    missing="$(sed -n 's/.*: \([A-Za-z0-9_.-][A-Za-z0-9_.-]*\): command not found.*/\1/p' \
               "$SBX/err" | head -1)"
    if [ -n "$missing" ]; then add_shim "$missing"; continue; fi
    return 0
  done
  echo "wizard-dryrun: scenario $name would not settle; last stderr:" >&2
  head -20 "$SBX/err" >&2
  return 1
}

# Two happy runs, because the branch a real operator takes depends on what they type. `values`
# answers every question; `defaults` presses Enter through all of them, which is the run that
# exercises each stage's own fallback - and a wrong fallback is invisible in the other one.
dr_run values 0 value 0 || { verdict "FAIL"; exit 2; }
dr_run defaults 0 default 0 || { verdict "FAIL"; exit 2; }

most() {
  local a b
  a="$(grep -c "$1" "$SBX/traces/values" 2>/dev/null)"   || a=0
  b="$(grep -c "$1" "$SBX/traces/defaults" 2>/dev/null)" || b=0
  [ "$a" -ge "$b" ] && echo "$a" || echo "$b"
}
N_CONFIRM="$(most '^CONFIRM|')"
N_EXEC="$(most '^EXEC|')"

# The failure scenarios take whichever answering mode got furthest, so a decline or a failure is
# injected into a run that actually reaches the commands.
REACH_MODE=value
de="$(grep -c '^EXEC|' "$SBX/traces/defaults" 2>/dev/null)" || de=0
ve="$(grep -c '^EXEC|' "$SBX/traces/values"   2>/dev/null)" || ve=0
[ "$de" -gt "$ve" ] && REACH_MODE=default

i=1
while [ "$i" -le "$N_CONFIRM" ]; do
  dr_run "decline-$i" "$i" "$REACH_MODE" 0 || { verdict "FAIL"; exit 2; }
  i=$((i + 1))
done

i=1
while [ "$i" -le "$N_EXEC" ]; do
  dr_run "fail-$i" 0 "$REACH_MODE" "$i" || { verdict "FAIL"; exit 2; }
  i=$((i + 1))
done

# --- 5. check the traces against the declared contract ----------------------------------------
python3 - "$SBX/stages.sh" "$SBX/traces" <<'PY'
import os, re, sys

stages_src, trace_dir = sys.argv[1], sys.argv[2]
src = open(stages_src).read()
lines = src.splitlines()

findings = []
def bad(where, msg):
    findings.append((where, msg))

# ---- the stage contract, as declared above each stage() call --------------------------------
# @mutates  <what changes, and where>
# @requires <stage numbers that must have succeeded, or "none">
# @onfail   stop | skip-to <n>
# @input    <KEYS asked before the mutation because the mutation needs them>
# @observes <stage number this one records the result of>
TAG = re.compile(r'^\s*#\s*@(mutates|requires|onfail|input|observes)\b\s*(.*)$')
STAGE_CALL = re.compile(r'^\s*stage\s+(["\'])(.*?)\1')

stages, pending, idx = {}, {}, 0
for line in lines:
    m = TAG.match(line)
    if m:
        pending[m.group(1)] = m.group(2).strip()
        continue
    m = STAGE_CALL.match(line)
    if m:
        idx += 1
        stages[idx] = {"name": m.group(2), "tags": pending}
        pending = {}
        continue
    if line.strip() and not line.lstrip().startswith("#"):
        pending = {}          # a tag block only binds to the stage() directly below it

declared_total = None
for m in re.finditer(r'^\s*TOTAL_STAGES=(\d+)', src, re.M):
    declared_total = int(m.group(1))

def nums(text):
    return [int(n) for n in re.findall(r'\d+', text or "")]

# ---- traces ---------------------------------------------------------------------------------
def read_trace(name):
    path = os.path.join(trace_dir, name)
    out = []
    for raw in open(path):
        parts = raw.rstrip("\n").split("|")
        out.append((parts[0], parts[1:]))
    return out

traces = {n: read_trace(n) for n in sorted(os.listdir(trace_dir))}
values = traces["values"]

ACTION = {"EXEC", "ENV", "GHSECRET", "GHVAR", "ASK", "SECRET", "CONFIRM"}
EFFECT = {"EXEC", "ENV", "GHSECRET", "GHVAR"}

APPLY = {"apply", "deploy", "destroy", "up", "upgrade", "install", "migrate", "push",
         "set", "put", "create", "delete", "remove", "run", "exec", "import", "rollout",
         "promote", "publish", "restart", "scale", "sync", "provision", "login", "revoke"}
PREVIEW = {"plan", "diff", "dry-run", "preview", "what-if"}
PLANNABLE = {"terraform", "tofu", "terragrunt", "pulumi", "kubectl", "helm"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

def argv(ev):
    # EXEC|<n>|<cmd arg arg>|rc=<n>
    return ev[1].split()

def is_mutating(ev):
    a = argv(ev)
    if any(f in ("--dry-run", "--dryrun", "--check") for f in a):
        return False
    if a and a[0] == "curl":
        return any(t in WRITE_METHODS for t in a)
    return any(t in APPLY for t in a[1:])

def is_preview(ev):
    return any(t in PREVIEW for t in argv(ev)[1:])

def by_stage(trace):
    """[(stage_index, stage_name, [events])] - events before stage 1 land under index 0."""
    groups, cur = [(0, "<before the first stage>", [])], None
    for kind, ev in trace:
        if kind == "STAGE":
            cur = (int(ev[0]), ev[1], [])
            groups.append(cur)
        else:
            groups[-1][2].append((kind, ev))
    return groups

# Both happy runs get checked. They take different branches, so a stage that only mutates when
# the operator presses Enter is still driven.
happy = [by_stage(traces["values"]), by_stage(traces["defaults"])]
vstages = max(happy, key=lambda g: sum(1 for _, _, evs in g for k, _ in evs if k == "EXEC"))
reference = traces["defaults"] if vstages is happy[1] else values

mutating_stages = set()
for groups in happy:
    for n, name, evs in groups[1:]:
        if any(k == "EXEC" and is_mutating(ev) for k, ev in evs):
            mutating_stages.add(n)

def all_stages():
    """Every stage of every happy run. Findings dedupe, so checking both costs nothing."""
    for groups in happy:
        for g in groups[1:]:
            yield g

# ---- 1. the stage count is the one the banner promises --------------------------------------
run_count = sum(1 for k, _ in reference if k == "STAGE")
if declared_total is None:
    bad("script", "no TOTAL_STAGES assignment in the stages section")
elif declared_total != run_count:
    bad("script", "TOTAL_STAGES is %d but the wizard ran %d stages - the banner and the "
                  "progress counter lie to the operator" % (declared_total, run_count))
if run_count != len(stages):
    bad("script", "%d stage() calls in the source but %d ran - a stage sits inside a branch "
                  "that a live run can skip, so the numbering shifts under the operator"
                  % (len(stages), run_count))

# A clean sheet over a path nothing drove is the one result worse than a finding. If the source
# reaches for a tool and no run ever called one, a guard short-circuited every mutating stage.
# Quoted text goes first, so a `warn "the next terragrunt apply removes it"` is prose and not a
# call. What is left is scanned in command position only.
code = re.sub(r'"[^"\n]*"', '""', src)
code = re.sub(r"'[^'\n]*'", "''", code)
code = re.sub(r'(?m)^\s*#.*$', '', code)
TOOLS = re.compile(r'(?:^|[;&|(){}]|\bthen\b|\belse\b|\bdo\b)\s*'
                   r'(terraform|tofu|terragrunt|pulumi|aws|gcloud|az|kubectl|helm|gh|psql|'
                   r'wrangler|flyctl|doctl|curl|docker|npm|make)\b', re.M)
called = TOOLS.search(code)
if called and not any(k == "EXEC" for k, _ in reference):
    bad("script", "the source calls %s but no scenario reached a single command - a guard "
                  "short-circuited every mutating stage, so this run proves nothing. Re-run "
                  "with --repo <worktree>" % called.group(1))

# ---- 2. every stage is an action -------------------------------------------------------------
acted = {n for n, _, evs in all_stages() if any(k in ACTION for k, _ in evs)}
for n, name, evs in vstages[1:]:
    if n not in acted:
        bad("stage %d" % n, "'%s' only reads or prints. A stage is something the operator "
                            "does; delete it and put the reading in HANDOFF.md" % name)

# ---- 3. the contract is declared wherever there is a mutation -------------------------------
for n, name, evs in all_stages():
    muts = [ev for k, ev in evs if k == "EXEC" and is_mutating(ev)]
    if not muts:
        continue
    tags = stages.get(n, {}).get("tags", {})
    for t in ("mutates", "requires", "onfail"):
        if t not in tags:
            bad("stage %d" % n, "runs `%s` but declares no @%s. A mutating stage states what "
                                "it changes, what must have succeeded first, and what happens "
                                "when it fails" % (muts[0][1], t))
    if tags.get("onfail", "").split()[:1] not in ([], ["stop"]) \
       and not tags.get("onfail", "").startswith("skip-to"):
        bad("stage %d" % n, "@onfail must be `stop` or `skip-to <n>`, not '%s'" % tags["onfail"])

if len(mutating_stages) > 3:
    bad("script", "%d stages mutate something. Past three, the wizard has become a runbook: "
                  "keep the ones that turn the feature on and file the rest in FOLLOWUPS.md"
                  % len(mutating_stages))

# ---- 4. @requires points at a real, earlier stage --------------------------------------------
for n in sorted(stages):
    req = stages[n]["tags"].get("requires")
    if req is None or req.lower().startswith("none"):
        continue
    for r in nums(req):
        if r not in stages:
            bad("stage %d" % n, "@requires stage %d, which does not exist" % r)
        elif r >= n:
            bad("stage %d" % n, "@requires stage %d, which runs later" % r)

# ---- 5. a mutation is confirmed first ---------------------------------------------------------
for n, name, evs in all_stages():
    seen_yes = False
    for k, ev in evs:
        if k == "CONFIRM" and ev[2] == "yes":
            seen_yes = True
        if k == "EXEC" and is_mutating(ev) and not seen_yes:
            bad("stage %d" % n, "runs `%s` with no confirm before it. The operator has to be "
                                "the one who decides, and they need the command printed first"
                                % ev[1])
            break

# ---- 6. the reviewed diff is the applied diff --------------------------------------------------
for n, name, evs in all_stages():
    execs = [ev for k, ev in evs if k == "EXEC"]
    saved = []
    for ev in execs:
        a = argv(ev)
        if is_preview(ev):
            outs = [t.split("=", 1)[1] for t in a
                    if t.startswith(("-out=", "--out=", "-o=", "--output="))]
            saved.append((a[0], outs))
    for ev in execs:
        a = argv(ev)
        if not is_mutating(ev) or a[0] not in PLANNABLE:
            continue
        previews = [s for s in saved if s[0] == a[0]]
        if not previews:
            bad("stage %d" % n, "`%s` applies with nothing reviewed in this stage" % ev[1])
            continue
        artifacts = [p for _, outs in previews for p in outs]
        if not artifacts:
            bad("stage %d" % n, "the %s plan is printed and thrown away, then a bare `%s` "
                                "runs. Drift or anybody else's change between the two makes "
                                "the applied diff a different diff from the reviewed one - "
                                "save the plan and apply that file"
                                % (a[0], ev[1]))
        elif not any(p in a for p in artifacts):
            bad("stage %d" % n, "`%s` does not consume the saved plan (%s)"
                                % (ev[1], ", ".join(artifacts)))

# ---- 7. no secret is ever an argument ----------------------------------------------------------
for name, trace in traces.items():
    for k, ev in trace:
        if k == "EXEC" and "__DRSECRET_" in "|".join(ev):
            key = re.search(r'__DRSECRET_(\w+)__', "|".join(ev)).group(1)
            bad("script", "%s is passed to `%s` as an argument, where `ps` can read it. Send "
                          "it through stdin instead" % (key, ev[1].split()[0]))
            break
    else:
        continue
    break

# ---- 8. write_env writes where the stages section says -----------------------------------------
m = re.search(r'^\s*ENV_FILE=(.+)$', src, re.M)
if m:
    intended = m.group(1).strip().strip('"').strip("'")
    d = re.search(r'\$\{ENV_FILE:-(.+)\}$', intended)
    intended_path = (d.group(1) if d else intended).rstrip('}"\'')
    want = os.path.basename(intended_path)
    got = {os.path.basename(ev[1]) for k, ev in values if k == "ENV"}
    if got and want not in got:
        bad("script", "the stages section sets ENV_FILE to %s, but write_env wrote to %s. The "
                      "library assigns ENV_FILE before the stages run, so a `${ENV_FILE:-...}` "
                      "default below the marker never fires - assign it unconditionally"
                      % (intended_path, ", ".join(sorted(got))))

# ---- 9. a mutating stage does one thing, and ends at the change ----------------------------------
# The rule that removes the whole ordering class. A stage that opens a gate and then asks what
# the gate did has an order inside it that nothing can check, and one wizard got it backwards:
# it told the operator to drive its probes above the restart that opened the gate, so the probes
# measured the closed process and the stage printed open-gate evidence. Split it, and the order
# becomes two stages with a @requires between them, which the failure scenarios below do check.
for n, name, evs in all_stages():
    muts = [i for i, (k, ev) in enumerate(evs) if k == "EXEC" and is_mutating(ev)]
    if not muts:
        continue
    tags = stages.get(n, {}).get("tags", {})
    declared = set(re.split(r'[,\s]+', tags.get("input", "")))
    last_mut = max(muts)
    for i, (k, ev) in enumerate(evs):
        if k in ("ASK", "SECRET") and i < last_mut and ev[0] not in declared:
            bad("stage %d" % n, "asks for %s before the change it makes. If the change needs "
                                "it, say so with @input %s; if it records what the change did, "
                                "it is reading the old state" % (ev[0], ev[0]))
    trailing = [k for k, _ in evs[last_mut + 1:] if k in ("ASK", "SECRET", "URL", "CONFIRM")]
    if trailing:
        bad("stage %d" % n, "keeps going after the change it makes (%s). A mutating stage ends "
                            "at the change; whatever records the result is the next stage, with "
                            "@requires %d on it" % (", ".join(sorted(set(trailing))), n))
    if "observes" in tags:
        bad("stage %d" % n, "both changes something and declares @observes. Those are two "
                            "stages")

for n in sorted(stages):
    obs = stages[n]["tags"].get("observes")
    if obs is None:
        continue
    ns = nums(obs)
    if not ns or ns[0] not in stages or ns[0] >= n:
        bad("stage %d" % n, "@observes must name an earlier stage, not '%s'" % obs)
    elif ns[0] not in mutating_stages:
        bad("stage %d" % n, "@observes stage %d, which changes nothing" % ns[0])
    elif ns[0] not in nums(stages[n]["tags"].get("requires", "")):
        bad("stage %d" % n, "@observes stage %d but does not @require it, so a failed stage %d "
                            "is still followed by a question about its result"
                            % (ns[0], ns[0], ns[0]))

# ---- 9b. the wizard knows which checkout it is in ------------------------------------------------
# One wizard asked, and defaulted to the sprint's own feature branch - the one checkout that did
# not carry the property its apply depended on. The script is committed in the repo; it is
# already in a checkout, and that is the only one it should ever apply from.
for m in re.finditer(r'^\s*ask(?:_secret)?\s+(\w*(?:CHECKOUT|WORKTREE|REPO_ROOT|REPO_PATH|REPO_DIR)\w*)',
                     src, re.M):
    bad("script", "asks the operator for %s. The wizard is committed in the repo and knows "
                  "where it is - a checkout somebody types is a checkout nobody verified, and "
                  "a default for it is a guess about which branch is merged" % m.group(1))

# ---- 9c. an infra apply states the revision it applies from ---------------------------------------
first_infra = None
git_read = False
for k, ev in reference:
    if k != "EXEC":
        continue
    a = argv(ev)
    if a[0] == "git" and any(t in ("rev-parse", "status", "log", "describe") for t in a):
        git_read = True
    if first_infra is None and a[0] in PLANNABLE and is_mutating(ev):
        first_infra = ev[1]
if first_infra and not git_read:
    bad("script", "`%s` runs without the wizard ever reading the checkout's revision. Print "
                  "`git rev-parse --short HEAD`, the branch and `git status --porcelain` and "
                  "gate on them, so the operator applies from a revision they can name"
                  % first_infra)

# ---- 10. a failed or declined mutation stops what depends on it ------------------------------------
def stage_of_event(trace, pred):
    cur = 0
    for k, ev in trace:
        if k == "STAGE":
            cur = int(ev[0])
        elif pred(k, ev):
            return cur
    return None

def acted_after(trace, from_stage):
    """stage numbers > from_stage that had an effect, in this run."""
    cur, out = 0, set()
    for k, ev in trace:
        if k == "STAGE":
            cur = int(ev[0])
        elif k in EFFECT and cur > from_stage:
            out.add(cur)
    return out

def dependents_that_ran(trace, failed):
    ran = set()
    cur = 0
    for k, ev in trace:
        if k == "STAGE":
            cur = int(ev[0])
        elif k in EFFECT and cur in stages:
            req = stages[cur]["tags"].get("requires", "")
            if failed in nums(req):
                ran.add(cur)
    return ran

for name, trace in traces.items():
    if name.startswith("fail-"):
        s = stage_of_event(trace, lambda k, ev: k == "EXEC" and ev[2] == "rc=1")
    elif name.startswith("decline-"):
        s = stage_of_event(trace, lambda k, ev: k == "CONFIRM" and ev[2] == "no")
        if s not in mutating_stages:
            continue
    else:
        continue
    if s is None or s == 0:
        continue
    what = "failed" if name.startswith("fail-") else "was declined"
    ran = dependents_that_ran(trace, s)
    if ran:
        bad("stage %d" % s, "%s: the mutation %s, and stage%s %s ran anyway even though "
                            "they @require it"
                            % (name, what, "s" if len(ran) > 1 else "",
                               ", ".join(str(r) for r in sorted(ran))))
    onfail = stages.get(s, {}).get("tags", {}).get("onfail", "")
    if onfail == "stop":
        later = acted_after(trace, s)
        if later:
            bad("stage %d" % s, "%s: declares @onfail stop, but stage%s %s still acted"
                                % (name, "s" if len(later) > 1 else "",
                                   ", ".join(str(x) for x in sorted(later))))
    elif onfail.startswith("skip-to"):
        target = nums(onfail)
        if target:
            skipped = {x for x in acted_after(trace, s) if x < target[0]}
            if skipped:
                bad("stage %d" % s, "%s: declares @onfail skip-to %d, but stage%s %s acted on "
                                    "the way there"
                                    % (name, target[0], "s" if len(skipped) > 1 else "",
                                       ", ".join(str(x) for x in sorted(skipped))))

# ---- report ---------------------------------------------------------------------------------------
print("wizard-dryrun: %d stages, %d scenarios driven (%s)"
      % (run_count, len(traces), ", ".join(sorted(traces))))
if not findings:
    print("PASS  every scenario held the contract")
    raise SystemExit(0)
seen = set()
for where, msg in findings:
    key = (where, msg)
    if key in seen:
        continue
    seen.add(key)
    print("FAIL  %-10s %s" % (where, msg))
print("wizard-dryrun: %d finding(s)" % len(seen))
raise SystemExit(1)
PY
rc=$?
if [ "$rc" -eq 0 ]; then verdict "PASS"; else verdict "FAIL"; fi
exit "$rc"
