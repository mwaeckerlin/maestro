# Headless Maestro Docker Image

[mwaeckerlin/maestro] runs [Maestro], the studio for image, video and music generation on the WanGP pipeline, as a server container on an NVIDIA GPU: no Pinokio, no desktop, no shell in the image.

Upstream installs Maestro through the Pinokio desktop launcher only. This image performs the same installation steps at build time and starts Maestro from environment variables, so it runs on a headless GPU server, in Docker Compose or in a Swarm, behind a reverse proxy and below a path of its own.

All features are listed in [FEATURES.md](FEATURES.md), all tests in [TESTS.md](TESTS.md).

The image is a production service image and runs directly. It is built on [mwaeckerlin/ubuntu-very-base] and ships on the headless runtime base [mwaeckerlin/ubuntu-scratch], the Ubuntu counterparts of [mwaeckerlin/very-base] and [mwaeckerlin/scratch]: PyTorch and the CUDA wheels exist for glibc only, so the Alpine bases cannot carry them.

## Licence of Maestro

The MIT licence in [LICENSE](LICENSE) covers only the files of this repository: the Dockerfile, the helpers, the tests and the documentation. The image contains Maestro, which is based on WanGP and is distributed under one licence only, the **WanGP Non-Commercial Evaluation License 1.1** ([summary](https://github.com/Blizaine/Maestro/blob/main/LICENSE), [full text](https://github.com/Blizaine/Maestro/blob/main/app/LICENSE.txt)); there is no alternative open source licence for Maestro itself. The full text ships in the image at `/opt/maestro/src/app/LICENSE.txt`.

- **Permitted:** using the image for your own, non-commercial purposes, headless included, and selling the generated images, videos and audio with a notice that they were produced with WanGP.
- **Not permitted without a commercial licence from the WanGP licensor:** running Maestro as a hosted service for paying customers, selling it or offering it as part of a paid product or API. Section 1.5 c) of the licence also counts services that end users access or invoke, paid or not, as commercial use; a deployment for the operator's own use stays outside it.
- **Components keep their own licences:** the voice conversion `maestro-seedvc` is GPL-3.0, other bundled parts are MIT or Apache-2.0 (upstream `THIRD_PARTY_NOTICES.md`). Model weights have their own terms, which Maestro downloads on first use: Qwen Image 2.1 carries a research and evaluation licence, commercial use needs a separate licence from Qwen; YuE2 music weights are non-commercial.

## Interfaces

- **Studio** — the React interface at `/`: image, video and music generation, the Director, characters, the editor
- **Classic interface** — the WanGP Gradio interface at `/classic/`
- **REST API** — at `/api/v1/…`, documented at `/docs`

Maestro downloads a model the first time it is used and keeps it in the model directory.

## Usage

Requirements on the host: an NVIDIA GPU with driver 580 or newer (CUDA 13) and the [NVIDIA container toolkit].

```bash
$ docker run -d --name maestro --gpus all -p 42003:42003 -v maestro-models:/models -v maestro-output:/output -v maestro-state:/state mwaeckerlin/maestro
```

Browse to `http://localhost:42003`. With Docker Compose, [docker-compose.yml](docker-compose.yml) does the same: `npm start`.

## Administration

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `MAESTRO_CONFIG` | *(empty)* | JSON object merged into Maestro's own `wgp_config.json` at every start, nested objects key by key |

The server listens on port 42003; another port outside is the port mapping of the deployment, such as `-p 8080:42003`.

### Volumes

- `/models` — model weights, LoRAs (`loras/`) and the HuggingFace cache; persist it to avoid downloading models again, it holds nothing personal.
- `/output` — every generated image, video and audio file. Collect them from here.
- `/state` — everything else Maestro writes: settings, projects and the queue it saves after a crash, which contains prompts. As a volume it keeps projects and the saved queue across a restart; the settings of `MAESTRO_CONFIG` are applied again at every start.

`/tmp` needs no mount: it receives the files uploaded through the interface and the Triton cache, and every new container starts with it empty.

The container runs as `somebody` of [mwaeckerlin/ubuntu-scratch], uid 100, gid 1000, member of the group `shared-access` (gid 500), the same user as in [mwaeckerlin/scratch]; the volumes must be writable for it, and a volume shared with another image of the family is shared through `shared-access`.

### Maestro Settings

Maestro tunes itself to the detected hardware on its first start and keeps its settings in `wgp_config.json`. `MAESTRO_CONFIG` overrides any of them. On a machine whose GPU shares its memory with other services, such as the NVIDIA GB10 with 128 GB of unified memory, offloading and tiling keep Maestro from holding everything at once:

```bash
MAESTRO_CONFIG='{"profile":4,"video_profile":4,"image_profile":4,"vae_config":3,"services":{"auto_performance":false}}'
```

- `video_profile`, `image_profile` (and the legacy `profile`) — the mmgp memory profile: `1` HighRAM_HighVRAM … `4` LowRAM_LowVRAM (offloading) … `5` VerylowRAM_LowVRAM
- `vae_config` — `0` automatic, `1` full, `2` medium tiling, `3` aggressive tiling
- `services.auto_performance: false` — Maestro keeps these values instead of re-tuning them after an update

### Behind a Reverse Proxy Below a Path

Route a prefix to the container and strip it; the proxy must send `X-Forwarded-Prefix`, which Traefik's `stripPrefix` does. Example with Traefik labels for the prefix `/spark-4d3f/maestro`:

```text
traefik.http.routers.maestro.rule=PathPrefix(`/spark-4d3f/maestro`)
traefik.http.routers.maestro.middlewares=maestro-strip
traefik.http.middlewares.maestro-strip.stripprefix.prefixes=/spark-4d3f/maestro
traefik.http.services.maestro.loadbalancer.server.port=42003
```

The page must be opened with a trailing slash (`/spark-4d3f/maestro/`); redirect the bare prefix to it. Maestro has no authentication of its own: every path — `/`, `/classic/`, `/api/`, `/docs` — must sit behind the authentication of the proxy.

### Health

The image declares a `HEALTHCHECK`: healthy once the interface at `/` answers, which Maestro mounts as the last step of its start. The first start of a container imports the engine and builds the model registry, so the status stays `starting` for up to 15 minutes.

### Privacy

- **Logs contain prompts.** Maestro prints the prompt of every task to standard output, without a switch to turn it off. Where no prompt may reach a disk, run the container with a logging driver that writes nothing locally (`--log-driver none`, Swarm `logging: driver: none`).
- Telemetry of HuggingFace and Gradio is switched off; the Tailscale route of the Pinokio launcher is not started.

### GPU Access in a Swarm

A Swarm service has no `--gpus`. Set `"default-runtime": "nvidia"` in `/etc/docker/daemon.json` of the GPU node; the image sets `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`, which the NVIDIA runtime reads.

### Architectures

The image is built for `linux/amd64` and `linux/arm64` (NVIDIA GB10). On amd64 it installs upstream's `requirements.txt` unchanged. Four of its pins exist on PyPI for x86_64 Linux only; on arm64 they are replaced, and the PyTorch CUDA 13 index that upstream's `torch.js` names is added:

| Upstream | On arm64 |
| --- | --- |
| `onnxruntime-gpu==1.25.0.dev20260210001` (nightly) | `onnxruntime-gpu`, the latest release, which has aarch64 wheels from 1.29 on |
| `decord==0.6.0` | `decord2`, a maintained fork that ships the same `decord` module |
| `taichi==1.7.4` | `gstaichi`, the Genesis fork, installed under the module name `taichi` for the SCAIL pose renderer |
| `torchcodec==0.10.0` | `0.10.0+cu130` from the PyTorch index, plus `nvidia-npp` for CUDA 13, which it links against |

From upstream's `torch.js`, the arm64 image installs PyTorch and Triton. Three of its wheels exist for x86_64 only and are left out, each named in the build log: `xformers`, which upstream installs as an option and which Maestro's attention code does without by choosing another attention mode, and the optional `lightx2v_kernel` and `nunchaku` kernels. Upstream's optional installers for FlashAttention, SageAttention and the GGUF kernels name Linux wheels for x86_64 only, so the arm64 build skips them; Maestro then uses PyTorch's SDPA attention and dequantises GGUF models without those kernels.

The build keeps the list it installed in the image (`/opt/maestro/src/requirements-installed.txt`), and the runtime contract checks that list. The arm64 image is built natively on the arm64 runner of GitHub Actions, which also runs `npm test` there.

## Development

```bash
$ npm run build
$ npm test
```

`npm run build` builds the image with Docker Compose and starts over up to three times when the build fails, because a name lookup or a download that breaks off ends the whole build while the finished steps stay cached; `npm test` runs every suite. None of them needs a GPU, because the build hosts and the GitHub runners have none.

GitHub Actions builds the image and publishes it on Docker Hub on every push to the default branch and once a week ([.github/workflows/docker.yml](.github/workflows/docker.yml), the reusable workflow of [mwaeckerlin/scratch]), natively for `linux/amd64` and `linux/arm64`.

`npm test` runs, and fails on any single error:

1. **Docs contract** (`tests/docs-contract.sh`) — every feature has a test, no test is skipped.
2. **Image contract** (`tests/image-contract.sh`) — no shell, no busybox, no perl in the image.
3. **Runtime contract** (`tests/runtime/check_runtime.py`, inside the image) — the upstream Python and PyTorch builds, every requirement installed and importable, ffmpeg, gcc, git and ldconfig without a shell, and the launcher.
4. **Start contract** (`tests/run-start.sh`) — the image started with the `docker run` above, without a GPU. Maestro needs an NVIDIA GPU to start: upstream's `app/wgp.py` calls `torch.cuda.get_device_capability()` while it is imported, and without a driver the start ends with «Found no NVIDIA driver», measured on an amd64 host without a GPU. The contract passes when the start gets through the volumes, `MAESTRO_CONFIG` and the import of the engine and stops at exactly that point.
5. **Base path e2e** (`tests/e2e/`) — the interface of the image behind Traefik with a stripped prefix, driven by Chromium. A harness serves the real interface and answers the test requests.

The running Maestro server is not measured: it needs an NVIDIA GPU, and no build host or runner has one. The start contract covers the start up to the question for the GPU, the e2e suite covers the interface.

## Internals

### Build Stages

1. **`build`** — `mwaeckerlin/ubuntu-very-base` with the build tools, [uv], the upstream source (`MAESTRO_SOURCE`, fetched by BuildKit, which compares the remote commit on every build) and the virtual environment with upstream's Python version.
2. **`install`** — the steps of upstream's `install.js`: `requirements.txt`, PyTorch with xformers and Triton from `torch.js`, the optional acceleration and GGUF kernels, `maestro-seedvc`, the React interface built with relative asset URLs and the base path script. `bin/upstream-install.py` reads every version from the launcher files, so no version number is written in this repository. `bin/collect-runtime.py` then collects the shared libraries of every binary, ffmpeg, git and gcc into the directory the final stage copies, and refuses a result that contains a shell.
3. **final** — `mwaeckerlin/ubuntu-scratch` with that directory, the Python runtime and the read-only Maestro source.

### Build Warnings of Upstream

Vite reports two warnings while it builds the React interface: its main bundle exceeds 500 kB, and `ui/src/editor/useEditorStore.ts` is imported both dynamically and statically. Both come from the upstream source, which the image builds unchanged; removing them would mean patching Maestro itself.

### gcc in the Runtime

Triton compiles a small C launcher for every CUDA kernel the first time it runs, with the C compiler and the Python headers. gcc, the assembler, the linker and the C library headers are therefore part of the runtime; none of them is a shell, and gcc starts its stages directly.

### ldconfig Binary

Triton finds `libcuda.so` with `/sbin/ldconfig -p`, and `ctypes.util.find_library` does the same. Where Ubuntu ships `/sbin/ldconfig` as a shell script around `ldconfig.real`, the script cannot run without a shell, so the build copies the binary under that name.

### Base Path Mechanism

Maestro has no setting for a base path: its interface requests `/api/v1/…` and its answers contain root-absolute file addresses. `app/maestro-base-path.js` loads before the bundle, takes the prefix from the address the page was loaded from and rebases every root-absolute URL the page requests. `app/maestro_serve.py` turns `X-Forwarded-Prefix` into the ASGI `root_path`, which the Gradio interface builds its URLs from, and puts the prefix in front of a root-absolute `Location` of a redirect.

[Maestro]: https://github.com/Blizaine/Maestro "Maestro on GitHub"

[mwaeckerlin/maestro]: https://hub.docker.com/r/mwaeckerlin/maestro "get the image from docker hub"

[mwaeckerlin/ubuntu-very-base]: https://github.com/mwaeckerlin/ubuntu-very-base "Ubuntu build-only base image"

[mwaeckerlin/ubuntu-scratch]: https://github.com/mwaeckerlin/ubuntu-scratch "Ubuntu runtime base image"

[mwaeckerlin/very-base]: https://github.com/mwaeckerlin/very-base "build-only base image, never for production"

[mwaeckerlin/scratch]: https://github.com/mwaeckerlin/scratch "minimalistic runtime base image"

[NVIDIA container toolkit]: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html "NVIDIA container toolkit"

[uv]: https://docs.astral.sh/uv/ "uv, the Python package manager"
