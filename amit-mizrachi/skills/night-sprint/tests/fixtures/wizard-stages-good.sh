
# The shape a WIZARD session is aiming at: three stages, one of them mutating, the change and
# the record of the change in different stages with a @requires between them.

TOTAL_STAGES=3

# Assigned unconditionally. `${ENV_FILE:-...}` here would never fire: the library set ENV_FILE
# before this line ran.
ENV_FILE="$HOME/.night-sprint-demo.env"

banner "Demo setup"

# ── Stage 1 ───────────────────────────────────────────────────────────────
stage "Paste the API key CI needs"
open_url "https://dashboard.example.com/apikeys"
step "Developers > API keys > Reveal > copy."
ask_secret DEMO_API_KEY "Paste the key:"
set_secret DEMO_API_KEY "$DEMO_API_KEY"

# ── Stage 2 ───────────────────────────────────────────────────────────────
# @mutates  terraform apply on infra/demo - adds one variable and rolls the service
# @requires 1
# @onfail   stop
stage "Apply the unit that reads it"
say "THE COMMANDS, printed before anything runs:"
note "    git rev-parse --short HEAD && git status --porcelain"
note "    terraform plan -out=demo.tfplan"
note "    terraform apply demo.tfplan"
say "Applying from:"
git rev-parse --short HEAD
git status --porcelain
warn "A dirty or unmerged checkout applies a different diff from the one that was reviewed."
if ! confirm "Save a plan from this checkout?"; then
  SKIPPED+=("the demo unit: no plan was taken")
  exit 0
fi
terraform plan -out=demo.tfplan
say "Read the plan above. Only then answer the next question."
if ! confirm "Apply that saved plan, unchanged?"; then
  SKIPPED+=("the demo unit: the saved plan was not applied")
  exit 0
fi
terraform apply demo.tfplan

# ── Stage 3 ───────────────────────────────────────────────────────────────
# @observes 2
# @requires 2
stage "Record what the roll did"
ask DEMO_ROLLED_AT "When did the environment finish rolling?"
write_env DEMO_ROLLED_AT "$DEMO_ROLLED_AT"

finish
