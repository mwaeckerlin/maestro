#!/usr/bin/env bash
# Runtime contract: every dependency, program and launcher function works in
# the headless image. Needs the image built by `npm run build`; no GPU.
# Usage: bash tests/run-runtime.sh
set -euo pipefail

COMPOSE="tests/runtime/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down --rmi all --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

docker compose -f "$COMPOSE" build --quiet
docker compose -f "$COMPOSE" run --rm runtime
