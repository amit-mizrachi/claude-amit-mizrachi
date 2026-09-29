#!/usr/bin/env bash
# night-sprint shared helper - ask the harness about background sessions, reliably.
#
# Sourced, not run:  . "$WS/agents.sh"
# Provides:          agents_json [WORKTREE]   -> a JSON array on stdout, never empty output
#
# WHY THIS EXISTS. Three scripts need the same list, and they used to each call
# `claude agents --json --all --cwd "$WT"` their own way. That filter has been observed to
# return `[]` for a worktree whose sessions are demonstrably running under exactly that cwd.
# Every caller then drew the same wrong conclusion: no rows for this tag, so the session is
# gone. The watcher reported healthy sessions as DIED, and the reviver could not resolve the
# id of a session it had just started. One sprint patched it locally and the fix never
# reached the skill, which is the other half of the bug.
#
# So: ask with the filter, and if that comes back empty ask again without it. An unfiltered
# list is never wrong, only broader - and every caller here already matches on the session
# name or id, which is what actually narrows the answer. The filter is an optimisation; it
# is not allowed to be the source of truth.

# shellcheck shell=bash

agents_json() {
  # PATCHED (machina-feedback sprint, 2026-09-23): the WORKTREE argument is accepted and IGNORED.
  # `claude agents --cwd <wt>` has returned `[]` on this harness, and has also returned ONE
  # UNRELATED row - a non-empty answer the old fallback trusted, which made the runner call the
  # sprint's own live sessions dead. Every caller already matches rows by name or session id, so
  # the unfiltered list is both sufficient and correct.
  local out=""
  out="$(claude agents --json --all 2>/dev/null || true)"
  out="$(printf '%s' "$out" | tr -d '\000')"
  case "$(printf '%s' "$out" | tr -d '[:space:]')" in
    "") printf '[]' ;;
    *)  printf '%s' "$out" ;;
  esac
}
