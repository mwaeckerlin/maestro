# Tests

Register of all tests, grouped by kind and sorted by the [FEATURES.md](FEATURES.md) number each test covers. `npm test` runs every suite that needs no GPU; `npm run test:gpu` runs the suite against the real Maestro server and needs a host with an NVIDIA GPU; `npm run test:arm64` runs the arm64 resolution contract. The guard `tests/docs-contract.sh` fails when a feature has no test entry here or when any test carries a skip/xfail marker — tests are never skipped.

The Maestro server imports its engine at start, and the engine asks CUDA for the GPU; without one it stops. The e2e suite therefore serves the real interface of the image through a harness (`tests/e2e/harness/harness.py`) that answers the requests of the base path tests; the GPU suite runs the real server.

## Image contract

- **F2** `tests/image-contract.sh` › no sh, no bash, no busybox, no perl — the shipped image is headless.

## Runtime contract

Runs inside the image, without a GPU.

- **F1** `tests/runtime/check_runtime.py` › python_version_is_upstream_runtime — the Python version is the one upstream's launcher names for the CUDA 13 runtime.
- **F1** `tests/runtime/check_runtime.py` › every_requirement_installed — every distribution of upstream's `requirements.txt` that applies to the platform is installed.
- **F1** `tests/runtime/check_runtime.py` › every_requirement_importable — every module of those distributions imports, after Maestro's own TorchAudio adapter; `sounddevice` is exempt, it needs an audio server.
- **F3** `tests/runtime/check_runtime.py` › onnxruntime_is_the_gpu_build — only `onnxruntime-gpu` owns the `onnxruntime` package, it offers CUDA, and `rembg`, which Maestro imports at start, loads.
- **F1** `tests/runtime/check_runtime.py` › voice_conversion_component_present — `maestro-seedvc` is in place.
- **F1** `tests/runtime/check_runtime.py` › interface_built_with_base_path_script — the React interface is built with relative asset URLs and loads the base path script before its bundle.
- **F2** `tests/runtime/check_runtime.py` › runs_unprivileged — the service runs as `somebody` of `mwaeckerlin/ubuntu-scratch` and is a member of `shared-access` (gid 500), the group through which the output directory is shared, never as root.
- **F2** `tests/runtime/check_runtime.py` › source_is_read_only_for_the_service_user — the code of the image cannot be changed by the service.
- **F3** `tests/runtime/check_runtime.py` › torch_builds_are_upstream_cuda13 — torch, torchvision and torchaudio are the versions upstream pins, built for CUDA 13.
- **F3** `tests/runtime/check_runtime.py` › triton_and_xformers_importable — Triton and xformers import; on aarch64 xformers is absent and Maestro's attention module loads without it.
- **F4** `tests/runtime/check_runtime.py` › launcher_reads_bind_address — defaults `0.0.0.0:42003`, overrides reach Maestro as `SERVER_NAME`/`SERVER_PORT`, a port that is no number between 1 and 65535 stops the start.
- **F5** `tests/runtime/check_runtime.py` › launcher_links_model_and_output_directories — `ckpts` and `loras` point into `MAESTRO_MODEL_DIR`, and a second start keeps the links.
- **F5** `tests/runtime/check_runtime.py` › launcher_rejects_relative_or_empty_directory — a relative directory stops the start with the name of the variable.
- **F6** `tests/runtime/check_runtime.py` › launcher_links_model_and_output_directories — `outputs` points into `MAESTRO_OUTPUT_DIR`, and a file written there arrives in the volume.
- **F7** `tests/runtime/check_runtime.py` › launcher_runs_maestro_from_the_state_directory — the app runs from a copy in `MAESTRO_STATE_DIR`, the interface and icon are reachable from it, what Maestro wrote stays and stale code is replaced, also where the old copy is read-only.
- **F7** `tests/runtime/check_runtime.py` › launcher_rejects_relative_or_empty_directory — an empty `MAESTRO_STATE_DIR` stops the start with the name of the variable.
- **F8** `tests/runtime/check_runtime.py` › launcher_merges_maestro_config — `MAESTRO_CONFIG` overrides the named keys, merges nested objects key by key and keeps every other setting.
- **F8** `tests/runtime/check_runtime.py` › launcher_rejects_invalid_maestro_config — invalid JSON and a JSON array stop the start with the name of the variable.
- **F10** `tests/runtime/check_runtime.py` › ffmpeg_and_ffprobe_run — both programs run without a shell.
- **F10** `tests/runtime/check_runtime.py` › ffmpeg_encodes_video — ffmpeg encodes an H.264 video.
- **F10** `tests/runtime/check_runtime.py` › git_runs — git runs and GitPython finds it.
- **F10** `tests/runtime/check_runtime.py` › gcc_builds_a_python_extension_like_triton — gcc compiles and links a shared object against the Python headers, as Triton does.
- **F10** `tests/runtime/check_runtime.py` › ldconfig_lists_libraries — `/sbin/ldconfig -p` runs and lists the C library.
- **F10** `tests/runtime/check_runtime.py` › ctypes_finds_system_libraries — `ctypes.util.find_library` finds libc and PortAudio.
- **F10** `tests/runtime/check_runtime.py` › sounddevice_failure_is_caught_like_maestro — without an audio server Maestro's own call to play a notification sound reports failure and goes on.
- **F12** `tests/runtime/check_runtime.py` › telemetry_switched_off — HuggingFace Hub and Gradio report their telemetry as disabled.
- **F12** `tests/runtime/check_runtime.py` › no_tailscale_client — the image carries no Tailscale client, so the launcher's Tailscale route cannot start.
- **F13** `tests/runtime/check_runtime.py` › health_fails_while_nothing_listens — the health check reports unhealthy while no server answers.

- **F11** `tests/runtime/check_runtime.py` › installed_requirements_follow_upstream — on x86_64 the installed list is upstream's `requirements.txt` unchanged, on aarch64 none of the x86_64-only pins reached it and `decord2` did.
- **F11** `tests/runtime/check_runtime.py` › taichi_importable — `taichi` imports, on aarch64 as `gstaichi`, with `init` and `kernel`.
- **F11** `tests/runtime/check_runtime.py` › no_shared_library_of_another_architecture — no ELF shared library in the environment or the source is built for another architecture than the image.

## arm64 resolution contract

- **F11** `tests/run-arm64.sh` › build target `arm64-resolution` — the arm64 variant of upstream's `requirements.txt`, `gstaichi`, `nvidia-npp` and every `torch.js` line the build runs on aarch64 resolve for aarch64 with the glibc of the build stage and the upstream Python version; where they do not, every line without an aarch64 distribution is listed.

## Base path e2e

Playwright with Chromium, Traefik with the route of the Swarm deployment, no GPU.

- **F4** `tests/e2e/docker-compose.yml` › harness with `MAESTRO_PORT=42100` — the stack reaches the server on the configured port, not the default.
- **F13** `tests/e2e/docker-compose.yml` › proxy `depends_on: condition: service_healthy` — the proxy starts only after the image's own `HEALTHCHECK` reported the server healthy; `tests/run-e2e.sh` fails otherwise.
- **F9** `tests/e2e/test_base_path.py` › test_bare_prefix_redirects_to_slash — the bare prefix redirects to its slash form.
- **F9** `tests/e2e/test_base_path.py` › test_interface_mounts_below_prefix — React mounts and every request of the page stays below the prefix.
- **F9** `tests/e2e/test_base_path.py` › test_bundle_and_assets_load_below_prefix — bundle and stylesheets answer 200 below the prefix.
- **F9** `tests/e2e/test_base_path.py` › test_fetch_of_root_absolute_api_reaches_maestro — `fetch('/api/v1/…')` reaches the server with the prefix as `root_path`.
- **F9** `tests/e2e/test_base_path.py` › test_fetch_with_request_object_and_url_object — the same for a `Request` and a `URL` argument.
- **F9** `tests/e2e/test_base_path.py` › test_server_file_url_loads_as_image — a root-absolute file address from a server answer loads as image, set by property and by attribute.
- **F9** `tests/e2e/test_base_path.py` › test_link_and_window_open_keep_prefix — link targets and `window.open` keep the prefix.
- **F9** `tests/e2e/test_base_path.py` › test_icon_of_index_html_is_rebased — the icon link written in `index.html` is rebased and loads.
- **F9** `tests/e2e/test_base_path.py` › test_service_worker_registers_below_prefix — the service worker registers with the prefix as scope.
- **F9** `tests/e2e/test_base_path.py` › test_foreign_and_prefixed_urls_stay_unchanged — foreign, protocol-relative, relative, data and already prefixed URLs stay as they are.
- **F9** `tests/e2e/test_base_path.py` › test_forwarded_prefix_reaches_the_server — the server sees path and `root_path` with the prefix.
- **F9** `tests/e2e/test_base_path.py` › test_classic_redirect_keeps_prefix — the redirect `/classic` → `/classic/` keeps the prefix, and the classic page sees it as `root_path`.
- **F9** `tests/e2e/test_base_path.py` › test_interface_at_root_without_prefix — served at the root, the script changes no URL.
- **F9** `tests/e2e/test_base_path.py` › test_invalid_forwarded_prefix_is_ignored — a prefix header with spaces, a scheme, a double slash or markup is ignored.

## GPU suite

The real Maestro server, on a host with an NVIDIA GPU only.

- **F3** `tests/gpu/test_maestro.py` › test_gpu_detected — Maestro detects CUDA inside the container.
- **F1** `tests/gpu/test_maestro.py` › test_models_listed — the engine loaded and lists its models.
- **F8** `tests/gpu/test_maestro.py` › test_maestro_config_applied — the running server reports the profiles and VAE setting of `MAESTRO_CONFIG`.
- **F9** `tests/gpu/test_maestro.py` › test_interface_below_prefix — the real interface mounts below the prefix, stays there and has no failing request.
- **F9** `tests/gpu/test_maestro.py` › test_classic_interface_below_prefix — the classic Gradio interface loads below the prefix and stays there.
- **F9** `tests/gpu/test_maestro.py` › test_api_docs_below_prefix — the API documentation answers below the prefix.

## Limitations

A real arm64 build and start are not measured by a suite: the resolution contract proves that every dependency exists for aarch64, and the GPU suite runs wherever an NVIDIA GPU is. That no request leaves the container is not measured; the runtime contract measures that HuggingFace and Gradio read their telemetry switches as off and that no Tailscale client exists.
