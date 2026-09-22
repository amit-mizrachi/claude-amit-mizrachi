#!/usr/bin/env bash
# Stand-in for the wizard library, used only by tests/run.sh.
#
# wizard-dryrun.sh replaces everything above the STAGES marker with its own instrumented copy
# and only checks that the wizard's half is byte-identical to the template it was given. So the
# tests need a marker and nothing else, and vendoring the real `wizard` skill's template.sh -
# which lives outside this repo - would buy nothing and go stale.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# STAGES: author this section. One stage() per step the human takes.
# ──────────────────────────────────────────────────────────────────────────
