#!/usr/bin/env bash
# Start contract: the image started with the `docker run` of the README, on a
# host without a GPU.
#
# Maestro's engine needs an NVIDIA GPU: upstream's wgp.py asks
# torch.cuda.get_device_capability() while it is imported, and without a
# driver that raises "Found no NVIDIA driver". So the start must get through
# everything the image and the launcher do — the volumes, /tmp without a
# mount, MAESTRO_CONFIG, the import of the engine — and
# stop at exactly that question. The running server is not measured: the build
# hosts and the runners have no NVIDIA GPU.
#
# Usage: bash tests/run-start.sh [IMAGE]

set -uo pipefail

IMAGE="${1:-mwaeckerlin/maestro}"
MODELS="maestro-start-models"
OUTPUT_VOLUME="maestro-start-output"
STATE="maestro-start-state"

PASS=0
FAIL=0
declare -a FAILED_NAMES

_pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
_fail() { FAIL=$((FAIL + 1)); FAILED_NAMES+=("$1"); echo "  FAIL  $1: $2"; }

cleanup() {
    docker volume rm -f "${MODELS}" "${OUTPUT_VOLUME}" "${STATE}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Start contract: the documented docker run without a GPU"

if ! docker image inspect "${IMAGE}" > /dev/null 2>&1; then
    _fail "image_exists" "image not built, run 'npm run build' first"
    exit 1
fi

# A deployment may hand /state over as a directory the service owns with mode
# 0700, as an encrypted scratch volume does; the start must work with exactly
# that, so the volume gets it before the start. Docker copies owner and mode of
# the image's /state into a named volume at every mount while the volume is
# empty, so the step leaves a file behind to keep the mode it sets.
docker run --rm --pull=never -v "${STATE}:/state" --entrypoint /opt/maestro/venv/bin/python "${IMAGE}" \
    -c "import os; open('/state/.mode-0700', 'w').close(); os.chmod('/state', 0o700)" > /dev/null 2>&1
MODE="$(docker run --rm --pull=never -v "${STATE}:/state" --entrypoint /opt/maestro/venv/bin/python "${IMAGE}" \
    -c "import os; s = os.stat('/state'); print(s.st_uid, oct(s.st_mode & 0o777))" 2>&1)"
if [[ "${MODE}" == "100 0o700" ]]; then
    _pass "state_owned_by_the_service_with_mode_0700"
else
    _fail "state_owned_by_the_service_with_mode_0700" "owner and mode of /state are «${MODE}»"
fi

LOG="$(timeout 900 docker run --rm --pull=never \
    -e MAESTRO_CONFIG='{"vae_config":3}' \
    -v "${MODELS}:/models" -v "${OUTPUT_VOLUME}:/output" -v "${STATE}:/state" \
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

# A new container on the same volume finds what the first one wrote to /state.
if docker run --rm --pull=never -v "${STATE}:/state" --entrypoint /opt/maestro/venv/bin/python "${IMAGE}" \
        -c "import sys, os; sys.exit(0 if os.path.isfile('/state/app/launch.py') else 1)" > /dev/null 2>&1; then
    _pass "state_survives_a_new_container"
else
    _fail "state_survives_a_new_container" "/state/app/launch.py missing in a new container on the same volume"
fi

echo ""
echo "==> Start contract results: ${PASS} passed, ${FAIL} failed"
if [[ ${FAIL} -gt 0 ]]; then
    echo "==> Failed contracts: ${FAILED_NAMES[*]}"
    echo "==> Last lines of the container log:"
    tail -40 <<< "${LOG}"
    exit 1
fi
