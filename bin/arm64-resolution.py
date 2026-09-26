#!/usr/bin/env python3
"""Measure whether upstream's requirements resolve for arm64.

The image installs upstream's requirements.txt from PyPI plus the PyTorch
index torch.js names, which carries CUDA builds for aarch64 that PyPI lacks
(torchcodec, for instance). This measurement resolves the whole file for
linux/aarch64 from the same sources; where that fails, uv names only the first
conflict, so every line is then resolved on its own and each one without an
aarch64 distribution is listed. Exit code 0 when the whole file resolves.

Usage, from the root of the upstream source:

    arm64-resolution.py PYTHON_VERSION PYTORCH_INDEX
"""
import subprocess
import sys
import tempfile
from pathlib import Path

PLATFORM = "aarch64-manylinux_2_28"


def resolve(text, python_version, index):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(text)
    result = subprocess.run(
        [
            "uv", "pip", "compile", handle.name, "--quiet", "--no-header",
            "--index-strategy", "unsafe-best-match", "--extra-index-url", index,
            "--python-platform", PLATFORM, "--python-version", python_version,
        ],
        capture_output=True,
        text=True,
    )
    Path(handle.name).unlink()
    reason = (result.stderr.strip().splitlines() or [""])[-1]
    return result.returncode == 0, reason


def main(python_version, index):
    lines = Path("app/requirements.txt").read_text(encoding="utf-8").splitlines()
    joint, reason = resolve("\n".join(lines) + "\n", python_version, index)
    if joint:
        print(f"arm64-resolution: requirements.txt resolves for {PLATFORM}", flush=True)
        return 0
    print(f"arm64-resolution: requirements.txt does not resolve for {PLATFORM}: {reason}", flush=True)
    options = [line for line in lines if line.startswith("-")]
    requirements = [
        line.split(" #")[0].strip()
        for line in lines
        if line.strip() and not line.startswith(("#", "-"))
    ]
    missing = 0
    for requirement in requirements:
        ok, why = resolve("\n".join(options + [requirement]) + "\n", python_version, index)
        if not ok:
            missing += 1
            print(f"arm64-resolution: MISSING {requirement}: {why}", flush=True)
    print(f"arm64-resolution: {missing} of {len(requirements)} requirements without an aarch64 distribution", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
