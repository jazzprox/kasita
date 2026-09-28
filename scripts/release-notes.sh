#!/usr/bin/env bash
# Release notes for an Android build: every app/server change since the previous
# android-* release (or up to <to> for backfilling). Prints Markdown.
# Usage: scripts/release-notes.sh [<from-tag>] [<to-ref>]
set -euo pipefail
cd "$(dirname "$0")/.."
to="${2:-HEAD}"
if [ -n "${1:-}" ]; then
  from="$1"
else
  # newest android-* release on a DIFFERENT commit than <to> (a commit can carry
  # two tags while old android-9 style tags are being renamed to android-0009)
  target=$(git rev-parse "$to^{commit}")
  from=""
  for t in $(git tag --list 'android-*' --merged "$to" --sort=-v:refname); do
    if [ "$(git rev-parse "$t^{commit}")" != "$target" ]; then from="$t"; break; fi
  done
fi
range="${from:+$from..}$to"
subjects=$(git log --no-merges --reverse --format='- **%s**' "$range" -- app server)
echo "## What's new"
echo
if [ -z "$subjects" ]; then
  echo "No changes to the app or server in this build (build and tooling only)."
else
  echo "$subjects"
  echo
  echo "<details><summary>Details</summary>"
  echo
  # grep exits 1 when it prints nothing; that must not fail the release
  git log --no-merges --reverse --format='### %s%n%n%b' "$range" -- app server | { grep -v '^Co-Authored-By:' || true; }
  echo "</details>"
fi
echo
echo "Changes since ${from:-the first build}. Built from $(git rev-parse --short "$to")."
