#!/usr/bin/env python3
"""Run the installation steps of the upstream Pinokio launcher without Pinokio.

Maestro installs through Pinokio: `install.js` and `torch.js` name the Python
version, the PyTorch build, the acceleration wheels and the voice-conversion
component. This helper reads those values out of the launcher files of the
checked-out source, so the image follows every upstream release without a
version number written into this project.

Upstream picks its runtime by GPU. The image targets the "H3 Sol Engine / CUDA
13" runtime, the one upstream uses on Linux for every GPU from RTX 40 on,
including the Blackwell generation of the NVIDIA GB10.

Usage, from the root of the upstream source:

    upstream-install.py python-version   print the Python version of that runtime
    upstream-install.py pytorch-index    print the package index torch comes from
    upstream-install.py requirements     install requirements.txt
    upstream-install.py onnxruntime-gpu  keep only the GPU build of onnxruntime
    upstream-install.py torch            install PyTorch and the accelerators
    upstream-install.py seedvc           clone the voice-conversion component
"""
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path

# The wheel platform tag of the machine the image is built for. A wheel for
# another architecture cannot install here; upstream publishes some of its
# optional kernels for x86_64 only.
MACHINE_TAGS = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}


def fail(message):
    raise SystemExit(f"upstream-install: {message}")


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read {path}: {error}")


def python_version():
    """The Python of the Sol runtime profile in launcher_profile.js."""
    source = read("launcher_profile.js")
    match = re.search(r'env:\s*"env-sol",\s*python:\s*"([0-9.]+)"', source)
    if not match:
        fail("launcher_profile.js names no Python version for the env-sol runtime")
    return match.group(1)


def torch_commands():
    """The install commands of the Linux branch of the Sol runtime in torch.js.

    That branch holds a list of shell lines; one of them is a Pinokio template
    that installs xformers when install.js asks for it, which it does.
    """
    source = read("torch.js")
    branch = re.search(
        r"\}\s*else if \(solCapable && linux\)\s*\{\s*message\s*=\s*\[(.*?)\]",
        source,
        re.S,
    )
    if not branch:
        fail("torch.js has no Linux branch for the Sol runtime")
    commands = []
    for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', branch.group(1)):
        template = re.fullmatch(r"\{\{args && args\.xformers \? '(.*)' : ''\}\}", literal)
        command = template.group(1) if template else literal
        if not command.startswith("uv pip install"):
            fail(f"unexpected line in the Linux branch of torch.js: {literal}")
        commands.append(command)
    if not any(re.search(r"\btorch==", command) for command in commands):
        fail("the Linux branch of torch.js installs no torch")
    return commands


def pytorch_index():
    """The package index the Linux Sol runtime installs torch from (torch.js)."""
    for command in torch_commands():
        if re.search(r"\btorch==", command):
            match = re.search(r"--index-url\s+(\S+)", command)
            if match:
                return match.group(1)
    fail("the torch line of torch.js names no --index-url")


def foreign_wheel(command, machine):
    """True when the command installs a wheel built for another architecture."""
    tags = re.findall(r"linux_([a-z0-9_]+)\.whl", command)
    return any(tag != machine for tag in tags)


def install_requirements():
    """uv pip install -r app/requirements.txt, as install.js does.

    On aarch64 the PyTorch index torch.js names is added: upstream pins
    torchcodec, which PyPI publishes for x86_64 Linux only, and that index
    carries it for aarch64. On x86_64 the sources stay upstream's own, because
    the index would swap in torchcodec's CUDA build, which needs NVIDIA NPP.
    """
    command = ["uv", "pip", "install", "-r", "app/requirements.txt", "--index-strategy", "unsafe-best-match"]
    if MACHINE_TAGS.get(platform.machine()) == "aarch64":
        command += ["--extra-index-url", pytorch_index()]
    print(f"upstream-install: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def onnxruntime_gpu_requirement():
    """The onnxruntime-gpu line of requirements.txt for the runtime's Python."""
    wanted = tuple(int(part) for part in python_version().split("."))
    lines = read("app/requirements.txt").splitlines()
    index = next((line.split(None, 1)[1] for line in lines if line.startswith("--extra-index-url")), None)
    for line in lines:
        match = re.match(r'\s*(onnxruntime-gpu==\S+?)\s*;\s*python_version\s*(<|>=)\s*"([0-9.]+)"', line)
        if not match:
            continue
        bound = tuple(int(part) for part in match.group(3).split("."))
        if (wanted < bound) == (match.group(2) == "<"):
            return match.group(1), index
    fail(f"requirements.txt names no onnxruntime-gpu for Python {python_version()}")


def install_onnxruntime_gpu():
    """Leave onnxruntime-gpu as the only owner of the onnxruntime package.

    faster-whisper requires the CPU build `onnxruntime`, rembg[gpu] and
    requirements.txt require `onnxruntime-gpu`; both install into the same
    `onnxruntime/` directory, and the files of two versions mixed there fail at
    import (`OrtDeviceVendorId` missing from its own module), which stops
    Maestro at start, since shared/utils/utils.py imports rembg. The CPU build
    goes, and the GPU build is installed again over the directory.
    """
    requirement, index = onnxruntime_gpu_requirement()
    commands = [["uv", "pip", "uninstall", "onnxruntime", "onnxruntime-gpu"]]
    install = ["uv", "pip", "install", "--no-deps", requirement]
    if index:
        install += ["--extra-index-url", index]
    commands.append(install)
    for command in commands:
        print(f"upstream-install: {' '.join(command)}", flush=True)
        subprocess.run(command, check=True)


def install_torch():
    machine = MACHINE_TAGS.get(platform.machine())
    if machine is None:
        fail(f"unsupported architecture {platform.machine()}")
    for command in torch_commands():
        if foreign_wheel(command, machine):
            print(f"upstream-install: skipped, no {machine} wheel upstream: {command}", flush=True)
            continue
        print(f"upstream-install: {command}", flush=True)
        subprocess.run(shlex.split(command), check=True)


def seedvc_clone():
    """The pinned clone of the voice-conversion component from install.js."""
    source = read("install.js")
    match = re.search(r'"(git clone [^"]*maestro-seedvc[^"]*)"', source)
    if not match:
        fail("install.js clones no maestro-seedvc")
    command = shlex.split(match.group(1))
    print(f"upstream-install: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def main(argv):
    actions = {
        "python-version": lambda: print(python_version()),
        "pytorch-index": lambda: print(pytorch_index()),
        "requirements": install_requirements,
        "onnxruntime-gpu": install_onnxruntime_gpu,
        "torch": install_torch,
        "seedvc": seedvc_clone,
    }
    if len(argv) != 2 or argv[1] not in actions:
        fail(f"usage: {argv[0]} {'|'.join(actions)}")
    actions[argv[1]]()


if __name__ == "__main__":
    main(sys.argv)
