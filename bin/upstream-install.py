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
    upstream-install.py aarch64-extras   taichi and NPP on aarch64
    upstream-install.py aarch64-requirements FILE  write the aarch64 requirements
    upstream-install.py torch            install PyTorch and the accelerators
    upstream-install.py torch-lines MACHINE  print the torch.js commands for MACHINE
    upstream-install.py seedvc           clone the voice-conversion component
    upstream-install.py optional-kernels scripts/NAME.py  run an optional kernel installer
"""
import os
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


# The file the image records as installed, read by its runtime contract.
INSTALLED_REQUIREMENTS = "requirements-installed.txt"

# Upstream requirements PyPI publishes for x86_64 Linux only, and what takes
# their place on aarch64, each measured on PyPI on 2026-09-27. A replacement
# that is None is installed by install_aarch64_extras instead.
AARCH64_REPLACEMENTS = {
    # decord2 is a maintained fork that ships the same `decord` module
    "decord": "decord2",
    # the nightly build upstream pins has no aarch64 wheel; the releases from
    # 1.29 on have one
    "onnxruntime-gpu": "onnxruntime-gpu",
    # gstaichi, the Genesis fork, has aarch64 wheels as pre-releases only
    "taichi": None,
}


def on_aarch64():
    return MACHINE_TAGS.get(platform.machine()) == "aarch64"


def aarch64_requirements(text):
    """requirements.txt with the x86_64-only pins replaced for aarch64."""
    lines = []
    seen = set()
    for line in text.splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*(==|@|;|$)", line)
        name = match.group(1).lower() if match else None
        if name in AARCH64_REPLACEMENTS:
            replacement = AARCH64_REPLACEMENTS[name]
            if replacement and replacement not in seen:
                lines.append(replacement)
                seen.add(replacement)
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def install_requirements():
    """uv pip install -r requirements.txt, as install.js does.

    On x86_64 the file and its sources are upstream's own. On aarch64 the
    x86_64-only pins are replaced (AARCH64_REPLACEMENTS) and the PyTorch index
    torch.js names is added, because upstream pins torchcodec, which PyPI
    publishes for x86_64 Linux only; that index carries it for aarch64. On
    x86_64 the index would swap in torchcodec's CUDA build, which needs NPP.
    The file that was installed is kept, so the runtime contract checks it.
    """
    text = read("app/requirements.txt")
    if on_aarch64():
        text = aarch64_requirements(text)
    Path(INSTALLED_REQUIREMENTS).write_text(text, encoding="utf-8")
    command = ["uv", "pip", "install", "-r", INSTALLED_REQUIREMENTS, "--index-strategy", "unsafe-best-match"]
    if on_aarch64():
        command += ["--extra-index-url", pytorch_index()]
    print(f"upstream-install: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


def write_aarch64_requirements(target):
    """Write the aarch64 variant of requirements.txt, for the resolution check."""
    Path(target).write_text(aarch64_requirements(read("app/requirements.txt")), encoding="utf-8")


def install_aarch64_extras():
    """On aarch64: taichi through gstaichi, and NPP for torchcodec's CUDA build.

    gstaichi ships the module `gstaichi`; a module `taichi` that is gstaichi
    lets Maestro's SCAIL pose renderer import it by its usual name. The CUDA
    build of torchcodec the PyTorch index carries for aarch64 links against
    libnppicc, which nvidia-npp of the same CUDA major puts beside the other
    CUDA libraries in nvidia/cu13/lib.
    """
    if not on_aarch64():
        print("upstream-install: x86_64 installs taichi and torchcodec from requirements.txt", flush=True)
        return
    cuda_major = re.search(r"cu(\d+?)0$", pytorch_index().rstrip("/")).group(1)
    commands = [
        ["uv", "pip", "install", "--prerelease", "allow", "gstaichi"],
        ["uv", "pip", "install", f"nvidia-npp=={cuda_major}.*"],
    ]
    for command in commands:
        print(f"upstream-install: {' '.join(command)}", flush=True)
        subprocess.run(command, check=True)
    site = subprocess.run(
        [str(Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python"), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    Path(site, "taichi.py").write_text(
        '"""taichi on aarch64 is gstaichi, the fork with aarch64 wheels."""\n'
        "import sys\n\nimport gstaichi\n\nsys.modules[__name__] = gstaichi\n",
        encoding="utf-8",
    )
    print(f"upstream-install: {site}/taichi.py points to gstaichi", flush=True)


def onnxruntime_gpu_requirement():
    """The onnxruntime-gpu requirement for the runtime's Python and machine."""
    if on_aarch64():
        return AARCH64_REPLACEMENTS["onnxruntime-gpu"], None
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


# Lines of torch.js that install nothing on aarch64, each with the reason,
# measured on the PyTorch index on 2026-09-27. xformers is optional upstream
# (install.js switches it on through a template flag), and every import of it
# in Maestro falls back when it is missing (shared/attention.py and the
# preprocessors); its release pinned by torch.js has wheels for x86_64 and
# Windows only.
AARCH64_SKIPS = {"xformers": "optional upstream, and its pinned release has no aarch64 wheel"}


def torch_installs(machine):
    """Each torch.js command with the reason it is skipped on this machine."""
    for command in torch_commands():
        packages = [word.split("==")[0].lower() for word in shlex.split(command)[3:] if not word.startswith("-")]
        if foreign_wheel(command, machine):
            yield command, f"no {machine} wheel upstream"
        elif machine == "aarch64" and any(name in AARCH64_SKIPS for name in packages):
            yield command, next(AARCH64_SKIPS[name] for name in packages if name in AARCH64_SKIPS)
        else:
            yield command, None


def machine_tag(name=None):
    machine = MACHINE_TAGS.get(name or platform.machine())
    if machine is None:
        fail(f"unsupported architecture {name or platform.machine()}")
    return machine


def install_torch():
    for command, skipped in torch_installs(machine_tag()):
        if skipped:
            print(f"upstream-install: skipped, {skipped}: {command}", flush=True)
            continue
        print(f"upstream-install: {command}", flush=True)
        subprocess.run(shlex.split(command), check=True)


def optional_kernels(script):
    """Run one of upstream's optional kernel installers, from app/.

    Both installers name fixed Linux wheels. install_optional_cuda_acceleration
    hands them to uv with --no-deps, and uv installs an x86_64 wheel from a URL
    on aarch64 without a word: its Python files land, its compiled module does
    not load, and diffusers then fails at import because it finds flash_attn.
    Where every Linux wheel a script names is for another machine, the script
    is skipped.
    """
    machine = machine_tag()
    source = read(f"app/{script}")
    tags = re.findall(r"linux_([a-z0-9_]+)\.whl", source)
    if tags and all(tag != machine for tag in tags):
        print(f"upstream-install: skipped, {script} names Linux wheels for {', '.join(sorted(set(tags)))} only", flush=True)
        return
    command = [str(Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python"), f"scripts/{Path(script).name}"]
    print(f"upstream-install: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, cwd="app")


def print_torch_lines(machine):
    """The torch.js commands the build runs on MACHINE, one per line."""
    for command, skipped in torch_installs(machine_tag(machine)):
        if not skipped:
            print(command)


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
        "aarch64-extras": install_aarch64_extras,
        "onnxruntime-gpu": install_onnxruntime_gpu,
        "torch": install_torch,
        "seedvc": seedvc_clone,
    }
    if len(argv) == 3 and argv[1] == "aarch64-requirements":
        write_aarch64_requirements(argv[2])
        return
    if len(argv) == 3 and argv[1] == "torch-lines":
        print_torch_lines(argv[2])
        return
    if len(argv) == 3 and argv[1] == "optional-kernels":
        optional_kernels(argv[2])
        return
    if len(argv) != 2 or argv[1] not in actions:
        fail(f"usage: {argv[0]} {'|'.join(actions)}|aarch64-requirements FILE|torch-lines MACHINE|optional-kernels SCRIPT")
    actions[argv[1]]()


if __name__ == "__main__":
    main(sys.argv)
