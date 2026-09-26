#!/usr/bin/env bash
# Base path e2e suite: the built interface of the image behind Traefik with the
# prefix route of the Swarm deployment, driven by Chromium. Needs the image
# built by `npm run build`; no GPU.
# Usage: bash tests/run-e2e.sh [pytest-args...]
set -euo pipefail

COMPOSE="tests/e2e/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down -v --rmi all --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Building test stack..."
docker compose -f "$COMPOSE" build --quiet

echo "==> Starting services..."
docker compose -f "$COMPOSE" up -d --remove-orphans harness proxy

echo "==> Running tests..."
EXIT=0
docker compose -f "$COMPOSE" run --rm test-runner "$@" || EXIT=$?

if [[ $EXIT -ne 0 ]]; then
    echo "==> Collecting logs on failure..."
    docker compose -f "$COMPOSE" logs harness proxy 2>&1 | tail -120
fi

exit $EXIT
