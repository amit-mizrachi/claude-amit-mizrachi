
# The same procedure with the defects a real night sprint shipped, one per line of the audit.
# Every one of these passes `bash -n`, passes shellcheck, and reads fine.

TOTAL_STAGES=3

# Never fires - the library assigned ENV_FILE before this line ran, so notes land in `.env`
# inside the repo instead of the out-of-repo rollout file this claims.
ENV_FILE="${ENV_FILE:-$HOME/.night-sprint-demo.env}"

banner "Demo setup"

# ── Stage 1 ───────────────────────────────────────────────────────────────
stage "What is configured now"
say "The unit currently sets one variable."
note "Nothing to do on this screen."

# ── Stage 2 ───────────────────────────────────────────────────────────────
stage "Apply the unit"
ask DEPLOY_CHECKOUT "Which checkout holds the merged change? (Enter for this one):"
[ -z "$DEPLOY_CHECKOUT" ] && DEPLOY_CHECKOUT="."
if confirm "Run 'terraform plan'?"; then terraform plan; fi
if confirm "Run 'terraform apply'?"; then terraform apply; fi
ask DEMO_SAW "Did the service come back? (yes/no plus what you saw):"
write_env DEMO_SAW "$DEMO_SAW"

# ── Stage 3 ───────────────────────────────────────────────────────────────
stage "Roll it back"
if confirm "Roll the change back?"; then terraform apply -destroy; fi

finish
