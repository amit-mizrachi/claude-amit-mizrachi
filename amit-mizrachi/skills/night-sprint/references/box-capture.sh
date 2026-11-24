#!/usr/bin/env bash
# Record a test walk on the app: screenshots + one video + gallery.html, ready to publish as an Artifact.
#
#   bash <WS>/box-capture.sh <base-url> <out-dir> <steps.json> [title]
#
# <base-url> is a cloud box link (https://<id>-dev.shapes.services) or a local stack (http://localhost:...).
# For a box link it loads the Cloudflare Access service token the box browser uses
# (AWS SM shapes-machina/internal/box-browser-access, eu-west-1) into this process only - never printed,
# never written to disk. The app password is the seeded preview password from shapes-platform's
# .github/workflows/preview-deploy.yml (a committed test value), read from PLATFORM_TREE when set, else
# from GitHub. Playwright is installed once into a cache dir. Steps format: see box-capture.mjs.
set -euo pipefail
BASE="${1:?base url}"; OUT="${2:?out dir}"; STEPS="${3:?steps.json}"; TITLE="${4:-Sprint test walk}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PW_VERSION="1.62.0"
NIGHT_SPRINT_CACHE="${NIGHT_SPRINT_CACHE:-$HOME/.cache/night-sprint}"
BOX_ACCESS_SECRET_ID="${BOX_ACCESS_SECRET_ID:-shapes-machina/internal/box-browser-access}"
BOX_AWS_PROFILE="${BOX_AWS_PROFILE:-${AWS_PROFILE:-amit}}"
PLATFORM_TREE="${PLATFORM_TREE:-}"
CACHE="$NIGHT_SPRINT_CACHE/box-capture-$PW_VERSION"

if [ ! -d "$CACHE/node_modules/playwright" ]; then
  mkdir -p "$CACHE"
  npm install --prefix "$CACHE" --silent --no-audit --no-fund "playwright@$PW_VERSION" >/dev/null
fi
# Downloads the headless browser only when this Playwright version's build is missing.
"$CACHE/node_modules/.bin/playwright" install chromium-headless-shell >/dev/null 2>&1 || \
  "$CACHE/node_modules/.bin/playwright" install chromium >/dev/null

case "$BASE" in
  https://*-dev.shapes.services*)
    if [ -z "${BOX_ACCESS_CLIENT_ID:-}" ]; then
      TOKEN="$(AWS_PROFILE="$BOX_AWS_PROFILE" aws secretsmanager get-secret-value --region eu-west-1 \
        --secret-id "$BOX_ACCESS_SECRET_ID" --query SecretString --output text)"
      BOX_ACCESS_CLIENT_ID="$(jq -r .clientId <<<"$TOKEN")"
      BOX_ACCESS_CLIENT_SECRET="$(jq -r .clientSecret <<<"$TOKEN")"
      unset TOKEN
      export BOX_ACCESS_CLIENT_ID BOX_ACCESS_CLIENT_SECRET
    fi ;;
esac

if [ -z "${BOX_LOGIN_PASSWORD:-}" ]; then
  WF=".github/workflows/preview-deploy.yml"
  if [ -n "$PLATFORM_TREE" ] && [ -f "$PLATFORM_TREE/$WF" ]; then
    SRC="$(cat "$PLATFORM_TREE/$WF")"
  else
    SRC="$(gh api "repos/dreamteamapp/shapes-platform/contents/$WF" --jq .content | base64 -d)"
  fi
  BOX_LOGIN_PASSWORD="$(sed -nE 's/^ *PREVIEW_LOGIN_PASSWORD: *"?([^"]*)"? *$/\1/p' <<<"$SRC" | head -1)"
  export BOX_LOGIN_PASSWORD
fi

mkdir -p "$OUT"
cp "$HERE/box-capture.mjs" "$CACHE/box-capture.mjs"
cd "$CACHE"
BOX_CAPTURE_TITLE="$TITLE" node "$CACHE/box-capture.mjs" "$BASE" "$(cd "$OUT" && pwd)" "$(cd "$(dirname "$STEPS")" && pwd)/$(basename "$STEPS")"
