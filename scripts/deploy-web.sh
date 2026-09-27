#!/usr/bin/env bash
# Deploy the web app built by GitHub Actions (.github/workflows/web.yml):
# fetch the web-dist branch, put it in server/web, rebuild the container.
# The server never runs `flutter build web` itself (dart2js needs >1.5 GB RAM).
set -euo pipefail
cd "$(dirname "$0")/.."
git fetch -q origin web-dist
built=$(git show origin/web-dist:BUILD_COMMIT)
echo "web-dist was built from ${built:0:7} (main is $(git rev-parse --short origin/main))"
tmp=$(mktemp -d)
git archive origin/web-dist | tar -x -C "$tmp"
find server/web -mindepth 1 ! -name .gitkeep -delete
cp -r "$tmp"/. server/web/ && rm -rf "$tmp" server/web/BUILD_COMMIT
docker compose up -d --build kasita
