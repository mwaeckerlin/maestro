"""Start Maestro headless, configured from the environment.

Upstream starts Maestro from Pinokio, which passes the port in SERVER_PORT and
keeps every setting in app/wgp_config.json. This launcher is the entrypoint of
the image and does what Pinokio does:

- /state receives everything Maestro writes besides models and outputs:
  settings, the queue it saves, projects, uploads of the interface. Maestro
  writes all of it into its own app directory, so the launcher runs a copy of
  that directory from /state; the image itself stays read-only, and a tmpfs
  there keeps all of it off the disk.
- /models receives the model weights, the LoRAs and the HuggingFace cache;
  /output receives every generated file. The launcher links the directories
  Maestro writes them to.
- MAESTRO_CONFIG, a JSON object, is merged into wgp_config.json at every start,
  so a deployment sets any of Maestro's own settings without the interface.
- A reverse proxy that strips a path prefix announces it in the header
  X-Forwarded-Prefix; ForwardedPrefix gives it to the application as ASGI
  root_path, which is what the classic Gradio interface builds its URLs from.

Tailscale, which the Pinokio launcher refreshes at every start, is not started:
the image is reached through the network it is deployed in.
"""
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

# The read-only upstream source of the image: app/, ui/dist and the files
# app/launch.py reads from its parent directory.
SOURCE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILENAME = "wgp_config.json"
# The volumes of the image; a deployment mounts whatever it wants there.
MODEL_DIR = Path("/models")
OUTPUT_DIR = Path("/output")
STATE_DIR = Path("/state")
# wgp parses the command line at import; launch.py hands it exactly this.
WGP_ARGV = ["wgp.py", "--multiple-images"]
# Inside the container the server listens on every interface; where it is
# reached from outside is the port mapping of the deployment.
HOST = "0.0.0.0"
PORT = 42003


class ConfigurationError(Exception):
    """A setting in the environment that the launcher cannot apply."""


class ForwardedPrefix:
    """ASGI middleware: X-Forwarded-Prefix becomes the root_path of the request.

    Per the ASGI specification the path of a request contains its root_path, so
    the prefix goes in front of both; the routes of the application strip it
    again. A redirect to a root-absolute Location gets the prefix as well, the
    way a reverse proxy rewrites it, because Maestro redirects /classic to
    /classic/. Only the header of the proxy in front of the service sets the
    prefix, and a value that is not a path is ignored.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        prefix = ""
        if scope["type"] in ("http", "websocket"):
            prefix = forwarded_prefix(scope.get("headers", []))
            if prefix and not scope["path"].startswith(prefix + "/") and scope["path"] != prefix:
                scope = dict(scope)
                scope["root_path"] = prefix + scope.get("root_path", "")
                scope["path"] = prefix + scope["path"]
                if scope.get("raw_path") is not None:
                    scope["raw_path"] = prefix.encode("utf-8") + scope["raw_path"]
        if not prefix:
            await self.app(scope, receive, send)
            return

        encoded = prefix.encode("utf-8")

        async def send_with_prefix(message):
            if message["type"] == "http.response.start":
                headers = []
                for name, value in message.get("headers", []):
                    if (
                        name.lower() == b"location"
                        and value.startswith(b"/")
                        and not value.startswith(b"//")
                        and not value.startswith(encoded + b"/")
                    ):
                        value = encoded + value
                    headers.append((name, value))
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, send_with_prefix)


def forwarded_prefix(headers):
    for name, value in headers:
        if name.lower() == b"x-forwarded-prefix":
            prefix = value.decode("latin-1").split(",")[0].strip().rstrip("/")
            if prefix.startswith("/") and not prefix.startswith("//") and all(
                character.isalnum() or character in "/-._~" for character in prefix
            ):
                return prefix
    return ""


def replace_file(source, target):
    """Copy a file over an older copy, also where that copy is read-only.

    A file the image ships read-only (git's pack files, mode 0444) is copied
    with its mode, so the next start cannot write into it; removing it first
    only needs the directory to be writable, which the state directory is.
    """
    if os.path.lexists(target):
        os.unlink(target)
    return shutil.copy2(source, target)


def prepare_state(source=SOURCE_DIR, state=STATE_DIR):
    """Copy the app directory into the state directory and return the copy.

    The code of the image replaces the code in the copy at every start, so an
    updated image runs its own version; what Maestro wrote there beside the
    code stays. Everything else of the source is linked, read-only.
    """
    state.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source / "app", state / "app", symlinks=True, dirs_exist_ok=True,
                        copy_function=replace_file)
    except (OSError, shutil.Error) as error:
        raise ConfigurationError(f"cannot write {state}: {error}") from error
    for entry in source.iterdir():
        if entry.name == "app":
            continue
        link = state / entry.name
        if link.is_symlink() and Path(os.readlink(link)) == entry:
            continue
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.exists():
            shutil.rmtree(link)
        link.symlink_to(entry)
    return state / "app"


def link_directories(app_dir, models=MODEL_DIR, output=OUTPUT_DIR):
    """Point the directories Maestro writes into at the volumes."""
    for name, target in (("ckpts", models), ("loras", models / "loras"), ("outputs", output)):
        target.mkdir(parents=True, exist_ok=True)
        link = app_dir / name
        if link.is_symlink() and Path(os.readlink(link)) == target:
            continue
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():
            raise ConfigurationError(f"{link} is a directory; it must link to {target}")
        link.symlink_to(target)


def configuration_override():
    value = os.environ.get("MAESTRO_CONFIG", "").strip()
    if not value:
        return {}
    try:
        override = json.loads(value)
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"MAESTRO_CONFIG is no valid JSON: {error}") from error
    if not isinstance(override, dict):
        raise ConfigurationError("MAESTRO_CONFIG must be a JSON object, such as {\"video_profile\": 4}")
    return override


def merge(configuration, override):
    """Merge override into configuration; nested objects merge key by key.

    Maestro keeps nested settings such as "services", which also holds the
    active workspace, so an override of one nested key keeps its siblings.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(configuration.get(key), dict):
            merge(configuration[key], value)
        else:
            configuration[key] = value
    return configuration


def write_configuration(app_dir, override):
    """Merge MAESTRO_CONFIG into Maestro's own configuration file.

    Maestro writes that file on its first start, tuned to the hardware it
    detects. Where it does not exist yet, one import of the engine in a
    separate process creates it exactly that way, and the override is merged
    on top before the server imports the engine with it.
    """
    if not override:
        return
    config_file = app_dir / CONFIG_FILENAME
    if not config_file.is_file():
        print("[maestro-serve] creating Maestro's hardware-tuned configuration", flush=True)
        subprocess.run(
            [sys.executable, "-c", f"import sys; sys.argv = {WGP_ARGV!r}; import wgp"],
            cwd=app_dir,
            check=True,
        )
    configuration = merge(json.loads(config_file.read_text(encoding="utf-8")), override)
    config_file.write_text(json.dumps(configuration, indent=4), encoding="utf-8")
    print(f"[maestro-serve] applied MAESTRO_CONFIG: {', '.join(sorted(override))}", flush=True)


def main():
    import uvicorn

    # Maestro reads the address it serves on from these, as under Pinokio
    os.environ["SERVER_NAME"], os.environ["SERVER_PORT"] = HOST, str(PORT)
    app_dir = prepare_state()
    link_directories(app_dir)
    write_configuration(app_dir, configuration_override())

    os.chdir(app_dir)
    # Maestro imports its modules from the copy, never from the read-only source.
    sys.path[:] = [path for path in sys.path if Path(path or ".").resolve() != SOURCE_DIR / "app"]
    sys.path.insert(0, str(app_dir))
    launch = runpy.run_path(str(app_dir / "launch.py"), run_name="maestro_launch")
    launch["install_quiet_access_filter"]()
    print(f"[maestro-serve] Maestro listens on {HOST}:{PORT}", flush=True)
    uvicorn.run(ForwardedPrefix(launch["api"]), host=HOST, port=PORT)


def health():
    """Exit code 0 when the interface answers: the HEALTHCHECK of the image.

    Maestro mounts the interface at / as the very last step of its start, after
    the engine, the API and the classic interface, so a 200 there means the
    whole server is up.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=10) as response:
            return 0 if response.status == 200 else 1
    except OSError as error:
        print(f"[maestro-serve] not healthy: {error}", flush=True)
        return 1


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--health"]:
            sys.exit(health())
        main()
    except ConfigurationError as error:
        raise SystemExit(f"[maestro-serve] configuration error: {error}")
