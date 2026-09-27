#!/usr/bin/env python3
"""Measure whether the aarch64 requirements of the image resolve for arm64.

The build installs on aarch64 upstream's requirements.txt with its x86_64-only
pins replaced (upstream-install.py aarch64-requirements), from PyPI plus the
PyTorch index torch.js names, then gstaichi and nvidia-npp. This measurement
resolves the same set for linux/aarch64 on any build host. Where the file does
not resolve, uv names only the first conflict, so every line is then resolved
on its own and each one without an aarch64 distribution is listed. Exit code 0
when everything resolves.

Usage, from the root of the upstream source:

    arm64-resolution.py REQUIREMENTS PYTHON_VERSION PYTORCH_INDEX
"""
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# The glibc of the build stage decides which manylinux wheels install; the
# aarch64 wheels of onnxruntime-gpu need manylinux_2_34. uv names targets up
# to manylinux_2_40, so a newer glibc is measured as 2.40.
UV_HIGHEST_GLIBC_MINOR = 40
GLIBC_MINOR = min(int(platform.libc_ver()[1].split(".")[1]), UV_HIGHEST_GLIBC_MINOR)
PLATFORM = f"aarch64-manylinux_2_{GLIBC_MINOR}"


def resolve(text, python_version, index, *options):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(text)
    result = subprocess.run(
        [
            "uv", "pip", "compile", handle.name, "--quiet", "--no-header",
            "--index-strategy", "unsafe-best-match", "--extra-index-url", index,
            "--python-platform", PLATFORM, "--python-version", python_version, *options,
        ],
        capture_output=True,
        text=True,
    )
    Path(handle.name).unlink()
    reason = (result.stderr.strip().splitlines() or [""])[-1]
    return result.returncode == 0, reason


def main(requirements, python_version, index):
    lines = Path(requirements).read_text(encoding="utf-8").splitlines()
    cuda_major = re.search(r"cu(\d+?)0$", index.rstrip("/")).group(1)
    extras = [("gstaichi\n", ("--prerelease", "allow")), (f"nvidia-npp=={cuda_major}.*\n", ())]
    failures = 0
    joint, reason = resolve("\n".join(lines) + "\n", python_version, index)
    if joint:
        print(f"arm64-resolution: the requirements resolve for {PLATFORM}", flush=True)
    else:
        failures += 1
        print(f"arm64-resolution: the requirements do not resolve for {PLATFORM}: {reason}", flush=True)
        options = [line for line in lines if line.startswith("-")]
        requirements_only = [
            line.split(" #")[0].strip()
            for line in lines
            if line.strip() and not line.startswith(("#", "-"))
        ]
        for requirement in requirements_only:
            ok, why = resolve("\n".join(options + [requirement]) + "\n", python_version, index)
            if not ok:
                print(f"arm64-resolution: MISSING {requirement}: {why}", flush=True)
    for text, options in extras:
        ok, why = resolve(text, python_version, index, *options)
        print(f"arm64-resolution: {text.strip()} {'resolves' if ok else 'does not resolve: ' + why}", flush=True)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
