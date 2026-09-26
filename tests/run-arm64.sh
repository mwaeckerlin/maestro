#!/usr/bin/env bash
# arm64 resolution contract: every dependency of upstream's requirements.txt
# resolves to a distribution for linux/aarch64 (the NVIDIA GB10), measured with
# uv's cross-platform resolver on any build host.
# Usage: bash tests/run-arm64.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker build --target arm64-resolution --progress plain .
