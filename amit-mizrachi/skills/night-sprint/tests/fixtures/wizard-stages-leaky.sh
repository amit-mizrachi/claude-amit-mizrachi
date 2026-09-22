
# Contract declared, contract broken. The apply's failure is caught, warned about, and then
# walked straight past - so the stage that @requires it runs over a change that never landed.
# This is the one shape reading never catches: every line of it is correct on its own.

TOTAL_STAGES=3

ENV_FILE="$HOME/.night-sprint-demo.env"

banner "Demo setup"

# ── Stage 1 ───────────────────────────────────────────────────────────────
stage "Paste the API key CI needs"
open_url "https://dashboard.example.com/apikeys"
ask_secret DEMO_API_KEY "Paste the key:"
set_secret DEMO_API_KEY "$DEMO_API_KEY"

# ── Stage 2 ───────────────────────────────────────────────────────────────
# @mutates  terraform apply on infra/demo - adds one variable and rolls the service
# @requires 1
# @onfail   stop
stage "Apply the unit that reads it"
git rev-parse --short HEAD
git status --porcelain
if ! confirm "Save a plan from this checkout?"; then
  warn "no plan taken"
else
  terraform plan -out=demo.tfplan
fi
if confirm "Apply that saved plan, unchanged?"; then
  terraform apply demo.tfplan || warn "the apply did not finish cleanly"
fi

# ── Stage 3 ───────────────────────────────────────────────────────────────
# @observes 2
# @requires 2
stage "Record what the roll did"
ask DEMO_ROLLED_AT "When did the environment finish rolling?"
write_env DEMO_ROLLED_AT "$DEMO_ROLLED_AT"

finish
