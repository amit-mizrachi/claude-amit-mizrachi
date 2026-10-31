#!/usr/bin/env bash
# night-sprint shared helper - which repo a tag works in, and that repo's facts.
#
# Sourced, not run:  . "$WS/repos.sh"
# Provides:          repo_of WS TAG          -> the repo key the tag works in, or nothing
#                    repo_fact WS KEY FACT   -> <WS>/repos/<KEY>/<FACT>, or <WS>/<FACT> with no KEY
#
# A MULTI-REPO SPRINT (facts.env: MULTI_REPO=1, REPOS=<key> <key> ...) builds one feature across
# several repos and ends with one branch and one PR per repo. Each repo has its own worktree,
# branch and checks, in <WS>/repos/<key>/ (derived by bootstrap.sh from <WS>/repos/<key>.env).
# A tag names its repo in state/<TAG>.repo, written at kickoff.
#
# A continuation (T03c2, T03c2c3) is the same ticket, so it works in the same repo: with no
# .repo of its own it inherits its ticket's, found by stripping one `c<n>` at a time. Nobody has
# to remember to copy the file on a relay.
#
# A single-repo sprint has no .repo files, so repo_of prints nothing and repo_fact reads the
# sprint's own one-value file, exactly as every script did before this helper existed.

# shellcheck shell=bash

repo_of() {
  local ws="$1" tag="$2" prev=""
  while [ -n "$tag" ] && [ "$tag" != "$prev" ]; do
    if [ -s "$ws/state/$tag.repo" ]; then
      tr -d '[:space:]' < "$ws/state/$tag.repo"
      return 0
    fi
    prev="$tag"
    tag="$(printf '%s' "$tag" | sed -E 's/c[0-9]+$//')"
  done
  return 0
}

repo_fact() {
  local ws="$1" key="$2" fact="$3"
  if [ -n "$key" ]; then
    tr -d '[:space:]' < "$ws/repos/$key/$fact"
  else
    tr -d '[:space:]' < "$ws/$fact"
  fi
}
