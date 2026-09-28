#!/usr/bin/env bash
# Start contract: the image started with the `docker run` of the README, on a
# host without a GPU.
#
# Maestro's engine needs an NVIDIA GPU: upstream's wgp.py asks
# torch.cuda.get_device_capability() while it is imported, and without a
# driver that raises "Found no NVIDIA driver". So the start must get through
# everything the image and the launcher do — the volumes, the tmpfs mounts
# owned by the service user, MAESTRO_CONFIG, the import of the engine — and
# stop at exactly that question. The running server is not measured: the build
# hosts and the runners have no NVIDIA GPU.
#
# Usage: bash tests/run-start.sh [IMAGE]

set -uo pipefail

IMAGE="${1:-mwaeckerlin/maestro}"
MODELS="maestro-start-models"
OUTPUT_VOLUME="maestro-start-output"

PASS=0
FAIL=0
declare -a FAILED_NAMES

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); echo "  FAIL  $1: $2"; }

cleanup() {
    docker volume rm -f "${MODELS}" "${OUTPUT_VOLUME}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Start contract: the documented docker run without a GPU"

if ! docker image inspect "${IMAGE}" > /dev/null 2>&1; then
    _fail "image_exists" "image not built, run 'npm run build' first"
    exit 1
fi

LOG="$(timeout 900 docker run --rm --pull=never \
    -e MAESTRO_CONFIG='{"vae_config":3}' \
    -v "${MODELS}:/models" -v "${OUTPUT_VOLUME}:/output" \
    --tmpfs /state:uid=100,gid=1000,mode=0700 --tmpfs /tmp:mode=1777 \
    "${IMAGE}" 2>&1)"
STATUS=$?

if [[ ${STATUS} -eq 124 ]]; then
    _fail "start_ends" "still running after 900s"
else
    _pass "start_ends"
fi

_contains() {
    local name="$1" text="$2"
    if grep -qF -- "${text}" <<< "${LOG}"; then _pass "${name}"; else _fail "${name}" "no «${text}» in the log"; fi
}

_absent() {
    local name="$1" text="$2"
    if grep -qiF -- "${text}" <<< "${LOG}"; then _fail "${name}" "«${text}» in the log"; else _pass "${name}"; fi
}

_absent "state_and_volumes_writable" "permission denied"
_absent "launcher_accepts_the_documented_setup" "configuration error"
_contains "maestro_config_reaches_the_engine" "creating Maestro's hardware-tuned configuration"
_contains "engine_imported" "[Runtime] Python"
_contains "stops_only_at_the_missing_gpu" "Found no NVIDIA driver"

echo ""
echo "==> Start contract results: ${PASS} passed, ${FAIL} failed"
if [[ ${FAIL} -gt 0 ]]; then
    echo "==> Failed contracts: ${FAILED_NAMES[*]}"
    echo "==> Last lines of the container log:"
    tail -40 <<< "${LOG}"
    exit 1
fi
