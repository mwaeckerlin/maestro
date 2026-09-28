"""Runtime contract: the headless image carries everything Maestro runs with.

Runs inside the image with its own interpreter and without a GPU. It measures
what can be measured without CUDA hardware: the Python and PyTorch builds of
upstream's CUDA 13 runtime, every dependency the build installed from upstream's requirements.txt
installed and importable, the programs Maestro and Triton call, the built
interface with the base path script, and the launcher's configuration from the
environment.

Usage: python check_runtime.py (exit code 0 when every check passes)
"""
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

SOURCE = Path("/opt/maestro/src")
APP = SOURCE / "app"
RESULTS = {"passed": 0, "failed": []}


def check(name):
    def decorator(function):
        try:
            function()
            RESULTS["passed"] += 1
            print(f"  PASS  {name}", flush=True)
        except Exception as error:  # every failure is reported, none stops the run
            RESULTS["failed"].append(name)
            print(f"  FAIL  {name}: {error}", flush=True)
            traceback.print_exc(limit=2)
        return function
    return decorator


def run(*command, **options):
    result = subprocess.run(command, capture_output=True, text=True, **options)
    if result.returncode != 0:
        raise AssertionError(f"{' '.join(command)} exited {result.returncode}: {result.stderr[-500:]}")
    return result.stdout


def upstream_torch_versions():
    source = (SOURCE / "torch.js").read_text(encoding="utf-8")
    branch = re.search(r"solCapable && linux\)\s*\{(.*?)optionalMessage", source, re.S).group(1)
    return dict(re.findall(r"\b(torch|torchvision|torchaudio)==([0-9.]+)", branch))


def requirement_names():
    """Distribution names the build installed on this platform.

    requirements-installed.txt is upstream's requirements.txt on x86_64 and
    its aarch64 variant with the x86_64-only pins replaced on aarch64.
    """
    from packaging.requirements import Requirement

    names = []
    for line in (SOURCE / "requirements-installed.txt").read_text(encoding="utf-8").splitlines():
        line = line.split(" #")[0].strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        requirement = Requirement(line)
        if requirement.marker is None or requirement.marker.evaluate():
            names.append(requirement.name)
    return names


print("==> Runtime contract: Maestro image")


@check("python_version_is_upstream_runtime")
def _():
    profile = (SOURCE / "launcher_profile.js").read_text(encoding="utf-8")
    expected = re.search(r'env:\s*"env-sol",\s*python:\s*"([0-9.]+)"', profile).group(1)
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert actual == expected, f"Python {actual}, upstream runtime {expected}"


@check("torch_builds_are_upstream_cuda13")
def _():
    import torch
    import torchaudio
    import torchvision

    expected = upstream_torch_versions()
    for module in (torch, torchvision, torchaudio):
        version = module.__version__.split("+")[0]
        assert version == expected[module.__name__], f"{module.__name__} {version}, upstream {expected[module.__name__]}"
    assert torch.version.cuda and torch.version.cuda.startswith("13."), f"torch CUDA {torch.version.cuda}"


@check("every_requirement_installed")
def _():
    missing = []
    for name in requirement_names():
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    assert not missing, f"not installed: {', '.join(missing)}"


# Modules Maestro never imports at start, each with the place that shows how
# it uses them, measured on 2026-09-26.
IMPORT_EXCEPTIONS = {
    # opens the audio server at import; Maestro calls it only to play a
    # notification sound on the host and catches every error
    # (shared/utils/notification_sound.py, play_audio_with_sounddevice)
    "sounddevice": "needs an audio server; tested by sounddevice_failure_is_caught_like_maestro",
}


@check("every_requirement_importable")
def _():
    # Maestro puts back the torchaudio functions TorchAudio 2.9 removed before
    # pyannote and speechbrain use them (services/audio_analysis.py)
    sys.path.insert(0, str(APP))
    from shared.torchaudio_compat import ensure_pyannote_audio_compat

    ensure_pyannote_audio_compat()
    distributions = importlib.metadata.packages_distributions()
    wanted = {name.lower().replace("_", "-") for name in requirement_names()}
    modules = sorted(
        module for module, owners in distributions.items()
        if module.isidentifier() and not module.startswith("_")
        and module not in IMPORT_EXCEPTIONS
        and any(owner.lower().replace("_", "-") in wanted for owner in owners)
    )
    failed, declared_only = [], []
    for module in modules:
        if importlib.util.find_spec(module) is None:
            # a name in a package's top_level.txt that the package does not ship
            declared_only.append(module)
            continue
        try:
            importlib.import_module(module)
        except Exception as error:
            failed.append(f"{module} ({type(error).__name__}: {error})")
    if declared_only:
        print(f"        declared by a package but not shipped: {', '.join(declared_only)}", flush=True)
    assert not failed, "cannot import: " + "; ".join(failed)


@check("onnxruntime_is_the_gpu_build")
def _():
    import onnxruntime

    installed = {d.metadata["Name"].lower() for d in importlib.metadata.distributions()}
    assert "onnxruntime-gpu" in installed, "onnxruntime-gpu is not installed"
    assert "onnxruntime" not in installed, "the CPU build onnxruntime shares its directory with onnxruntime-gpu"
    assert "CUDAExecutionProvider" in onnxruntime.get_available_providers(), onnxruntime.get_available_providers()
    import rembg  # noqa: F401  shared/utils/utils.py imports it when Maestro starts


@check("sounddevice_failure_is_caught_like_maestro")
def _():
    sys.path.insert(0, str(APP))
    import numpy
    from shared.utils.notification_sound import play_audio_with_sounddevice

    # no audio server in the container: Maestro's call reports False and goes on
    assert play_audio_with_sounddevice(numpy.zeros(10, dtype=numpy.float32)) is False


@check("triton_and_xformers_importable")
def _():
    importlib.import_module("triton")
    if platform.machine() == "aarch64":
        # no aarch64 wheel of the xformers release torch.js pins; Maestro's
        # attention module then runs without it
        assert importlib.util.find_spec("xformers") is None, "xformers is installed on aarch64"
        sys.path.insert(0, str(APP))
        attention = importlib.import_module("shared.attention")
        assert attention.memory_efficient_attention is None
    else:
        importlib.import_module("xformers")


# ELF e_machine values of the architectures the image is built for
ELF_MACHINES = {62: "x86_64", 183: "aarch64"}


@check("no_shared_library_of_another_architecture")
def _():
    # a wheel installed for the wrong machine leaves Python files that import
    # and a compiled module that does not, as flash_attn did on aarch64
    foreign = []
    for root in (Path("/opt/maestro/venv"), SOURCE):
        for directory, _, files in os.walk(root):
            for name in files:
                if not (name.endswith(".so") or ".so." in name):
                    continue
                path = Path(directory, name)
                if path.is_symlink():
                    continue
                with path.open("rb") as handle:
                    header = handle.read(20)
                if header[:4] != b"\x7fELF":
                    continue
                machine = ELF_MACHINES.get(int.from_bytes(header[18:20], "little"), "other")
                if machine != platform.machine():
                    foreign.append(f"{path} ({machine})")
    assert not foreign, f"{len(foreign)} for another architecture: " + "; ".join(foreign[:10])


@check("installed_requirements_follow_upstream")
def _():
    import platform

    upstream = (APP / "requirements.txt").read_text(encoding="utf-8")
    installed = (SOURCE / "requirements-installed.txt").read_text(encoding="utf-8")
    if platform.machine() == "x86_64":
        assert installed == upstream, "x86_64 installs upstream's requirements.txt unchanged"
    else:
        for pin in ("decord==", "taichi==", "onnxruntime-gpu=="):
            assert pin not in installed, f"the x86_64-only pin {pin} reached the aarch64 requirements"
        assert "decord2" in installed.splitlines()


@check("taichi_importable")
def _():
    # the SCAIL pose renderer imports taichi (models/wan/scail); on aarch64 it
    # is gstaichi under the same name
    taichi = importlib.import_module("taichi")
    assert hasattr(taichi, "init") and hasattr(taichi, "kernel"), taichi


@check("ffmpeg_and_ffprobe_run")
def _():
    assert "ffmpeg version" in run("ffmpeg", "-hide_banner", "-version")
    assert "ffprobe version" in run("ffprobe", "-hide_banner", "-version")


@check("ffmpeg_encodes_video")
def _():
    with tempfile.TemporaryDirectory() as directory:
        target = os.path.join(directory, "probe.mp4")
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=5", "-t", "1", "-pix_fmt", "yuv420p", target)
        assert os.path.getsize(target) > 0


@check("git_runs")
def _():
    assert "git version" in run("git", "--version")
    import git  # GitPython, used by the plugin manager

    assert git.Git().version_info


@check("gcc_builds_a_python_extension_like_triton")
def _():
    import sysconfig

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "probe.c")
        library = os.path.join(directory, "probe.so")
        Path(source).write_text("#include <Python.h>\nint probe(void) { return Py_IsInitialized(); }\n")
        run("gcc", source, "-O3", "-shared", "-fPIC", "-o", library,
            f"-I{sysconfig.get_paths()['include']}")
        assert os.path.getsize(library) > 0


@check("ldconfig_lists_libraries")
def _():
    assert "libc.so.6" in run("/sbin/ldconfig", "-p")


@check("ctypes_finds_system_libraries")
def _():
    import ctypes.util

    for name in ("c", "portaudio"):
        assert ctypes.util.find_library(name), f"find_library({name!r}) found nothing"


@check("interface_built_with_base_path_script")
def _():
    dist = SOURCE / "ui" / "dist"
    index = (dist / "index.html").read_text(encoding="utf-8")
    assert index.index('src="./maestro-base-path.js"') < index.index('type="module"'), "base path script must load before the bundle"
    assert (dist / "maestro-base-path.js").is_file()
    assert not re.search(r'(src|href)="/assets/', index), "bundle assets are root-absolute"


@check("voice_conversion_component_present")
def _():
    assert (APP / "postprocessing" / "seedvc" / "__init__.py").is_file()


sys.path.insert(0, str(APP))


@check("source_is_read_only_for_the_service_user")
def _():
    assert not os.access(APP, os.W_OK), f"{APP} is writable by the service user"
    assert not os.access(SOURCE / "ui" / "dist" / "index.html", os.W_OK)


@check("launcher_runs_maestro_from_the_state_directory")
def _():
    import maestro_serve

    assert maestro_serve.STATE_DIR == Path("/state")
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory)
        app_dir = maestro_serve.prepare_state(state=state)
        assert app_dir == state / "app"
        assert (app_dir / "launch.py").is_file() and not (app_dir / "launch.py").is_symlink()
        assert (state / "ui" / "dist" / "index.html").is_file()
        assert (state / "maestro_simplified_icon_alpha.png").is_file()
        # Maestro writes its settings into its app directory: the copy takes them
        (app_dir / "settings").mkdir(exist_ok=True)
        (app_dir / "settings" / "kept.json").write_text("{}")
        # a new image replaces the code and keeps what Maestro wrote, also over
        # a copy that is read-only (git pack files are 0444)
        (app_dir / "launch.py").write_text("stale")
        (app_dir / "launch.py").chmod(0o444)
        maestro_serve.prepare_state(state=state)
        assert (app_dir / "launch.py").read_text() != "stale"
        assert (app_dir / "settings" / "kept.json").is_file()


@check("launcher_links_model_and_output_directories")
def _():
    import maestro_serve

    assert (maestro_serve.MODEL_DIR, maestro_serve.OUTPUT_DIR) == (Path("/models"), Path("/output"))
    with tempfile.TemporaryDirectory() as directory:
        app_dir = Path(directory) / "app"
        app_dir.mkdir()
        models, output = Path(directory) / "models", Path(directory) / "output"
        maestro_serve.link_directories(app_dir, models=models, output=output)
        assert os.path.realpath(app_dir / "ckpts") == str(models)
        assert os.path.realpath(app_dir / "loras") == str(models / "loras")
        assert os.path.realpath(app_dir / "outputs") == str(output)
        (app_dir / "outputs" / "written.png").write_bytes(b"x")
        assert (output / "written.png").is_file()
        # a second start finds the links in place
        maestro_serve.link_directories(app_dir, models=models, output=output)


@check("launcher_merges_maestro_config")
def _():
    import maestro_serve

    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "wgp_config.json"
        config.write_text(json.dumps({
            "video_profile": 1, "vae_config": 0, "save_path": "outputs",
            "services": {"auto_performance": True, "active_workspace": "default"},
        }))
        os.environ["MAESTRO_CONFIG"] = '{"video_profile": 4, "vae_config": 3, "services": {"auto_performance": false}}'
        maestro_serve.write_configuration(Path(directory), maestro_serve.configuration_override())
        merged = json.loads(config.read_text())
        assert merged == {
            "video_profile": 4, "vae_config": 3, "save_path": "outputs",
            "services": {"auto_performance": False, "active_workspace": "default"},
        }, merged
    os.environ["MAESTRO_CONFIG"] = ""


@check("launcher_rejects_invalid_maestro_config")
def _():
    import maestro_serve

    for value in ("{broken", "[1, 2]"):
        os.environ["MAESTRO_CONFIG"] = value
        try:
            maestro_serve.configuration_override()
        except maestro_serve.ConfigurationError as error:
            assert "MAESTRO_CONFIG" in str(error)
        else:
            raise AssertionError(f"MAESTRO_CONFIG={value!r} was accepted")
    os.environ["MAESTRO_CONFIG"] = ""


@check("launcher_listens_on_the_exposed_port")
def _():
    import maestro_serve

    dockerfile_port = 42003  # EXPOSE of the image
    assert (maestro_serve.HOST, maestro_serve.PORT) == ("0.0.0.0", dockerfile_port)


@check("health_fails_while_nothing_listens")
def _():
    result = subprocess.run(
        [sys.executable, str(APP / "maestro_serve.py"), "--health"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "not healthy" in result.stdout


@check("telemetry_switched_off")
def _():
    import huggingface_hub.constants
    from gradio import analytics

    assert huggingface_hub.constants.HF_HUB_DISABLE_TELEMETRY is True
    assert analytics.analytics_enabled() is False


@check("no_tailscale_client")
def _():
    assert shutil.which("tailscale") is None


@check("runs_unprivileged")
def _():
    import grp
    import pwd

    assert os.getuid() != 0, "the image runs as root"
    # the user of mwaeckerlin/scratch, shared with the other images of the family
    user = pwd.getpwuid(os.getuid()).pw_name
    group = grp.getgrgid(os.getgid()).gr_name
    print(f"        runs as {user} uid={os.getuid()} gid={os.getgid()} ({group})", flush=True)
    assert user == "somebody", user
    # the Swarm deployment shares /output with the rsync collector through the
    # group shared-access (gid 500) the base images create for that, mode 2770;
    # without the membership maestro could not write its outputs there
    shared = grp.getgrnam("shared-access")
    assert shared.gr_gid == 500, f"shared-access has gid {shared.gr_gid}"
    assert 500 in os.getgroups(), f"somebody is not in shared-access: groups {os.getgroups()}"


print("")
print(f"==> Runtime contract results: {RESULTS['passed']} passed, {len(RESULTS['failed'])} failed")
if RESULTS["failed"]:
    print(f"==> Failed contracts: {' '.join(RESULTS['failed'])}")
    sys.exit(1)
