# Changelog

- 2026-09-28 **1.0.5**
    - The server always listens on port 42003 and uses the volumes `/models`, `/output` and `/state`; the variables that moved them are gone, because a port mapping and a mount do the same
    - The documented `docker run` starts again: its tmpfs mounts for `/state` and `/tmp` now carry the owner and mode the service needs, where before the start stopped with «Permission denied»

- 2026-09-27 **1.0.4**
    - The image is published on Docker Hub for `linux/amd64` and `linux/arm64`; the build-time check that the arm64 packages exist is gone, because the arm64 runner now builds and tests the image itself

- 2026-09-27 **1.0.3**
    - On arm64, upstream's optional FlashAttention, SageAttention and GGUF kernels are left out, because they exist for x86_64 only and a half-installed FlashAttention stopped the model libraries from loading

- 2026-09-27 **1.0.2**
    - The arm64 build no longer stops at xformers, which upstream installs as an option and publishes for x86_64 only; Maestro uses another attention mode there

- 2026-09-27 **1.0.1**
    - Also built for arm64, such as the NVIDIA GB10: the upstream packages that exist for x86_64 only are replaced there by releases and forks that ship arm64 builds
        - the amd64 image installs exactly what upstream specifies, as before

- 2026-09-26 **1.0.0**
    - Maestro, the studio for image, video and music on NVIDIA GPUs, as a headless container: no Pinokio, no desktop, no shell in the image
    - Built on the Ubuntu base images of the family, because PyTorch and the CUDA libraries exist for glibc only
    - Model weights, generated files and everything else Maestro writes each get their own directory, so a deployment keeps personal data such as prompts in memory only
    - Maestro's own settings, such as memory offloading and VAE tiling, are set from the environment
    - Works behind a reverse proxy below a path such as `/<hostname>/maestro`
    - Reports its health to Docker and Swarm once the server is up
    - Runs as the family's unprivileged user, a member of the group through which volumes are shared with other images
    - The licence states that the image may be used for one's own, non-commercial purposes only, or under a separate licence from the WanGP licensor
