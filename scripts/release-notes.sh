#!/usr/bin/env bash
# Release notes for an Android build: every app/server change since the previous
# android-* release (or up to <to> for backfilling). Prints Markdown.
# Usage: scripts/release-notes.sh [<from-tag>] [<to-ref>]
set -euo pipefail
cd "$(dirname "$0")/.."
to="${2:-HEAD}"
from="${1:-$(git tag --list 'android-*' --merged "$to" --sort=-v:refname | grep -v "^$(git tag --points-at "$to" | grep android- || echo NONE)$" | head -1 || true)}"
range="${from:+$from..}$to"
echo "## What's new"
echo
git log --no-merges --reverse --format='- **%s**' "$range" -- app server
echo
echo "<details><summary>Details</summary>"
echo
git log --no-merges --reverse --format='### %s%n%n%b' "$range" -- app server | grep -v '^Co-Authored-By:'
echo "</details>"
echo
echo "Changes since ${from:-the first build}. Built from $(git rev-parse --short "$to")."
