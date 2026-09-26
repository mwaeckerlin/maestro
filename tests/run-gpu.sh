#!/usr/bin/env bash
# GPU suite: the real Maestro server of the image on an NVIDIA GPU behind the
# prefix route of the Swarm deployment. Needs a host with an NVIDIA GPU, the
# NVIDIA container toolkit and the image built by `npm run build`. The first
# run downloads no model: the suite reads the model list, it generates nothing.
# Usage: bash tests/run-gpu.sh [pytest-args...]
set -euo pipefail

COMPOSE="tests/gpu/docker-compose.yml"
cd "$(dirname "$0")/.."

cleanup() {
    docker compose -f "$COMPOSE" down -v --rmi local --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

docker compose -f "$COMPOSE" build --quiet
docker compose -f "$COMPOSE" up -d --remove-orphans maestro proxy

EXIT=0
docker compose -f "$COMPOSE" run --rm test-runner "$@" || EXIT=$?

if [[ $EXIT -ne 0 ]]; then
    docker compose -f "$COMPOSE" logs maestro proxy 2>&1 | tail -200
fi

exit $EXIT
