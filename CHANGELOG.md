# Changelog

- 2026-09-26 **1.0.0**
    - Maestro, the studio for image, video and music on NVIDIA GPUs, as a headless container: no Pinokio, no desktop, no shell in the image
    - Built on the Ubuntu base images of the family, because PyTorch and the CUDA libraries exist for glibc only
    - Model weights, generated files and everything else Maestro writes each get their own directory, so a deployment keeps personal data such as prompts in memory only
    - Maestro's own settings, such as memory offloading and VAE tiling, are set from the environment
    - Works behind a reverse proxy below a path such as `/<hostname>/maestro`
    - Reports its health to Docker and Swarm once the server is up
    - Runs as the family's unprivileged user, a member of the group through which volumes are shared with other images
    - The licence states that the image may be used for one's own, non-commercial purposes only, or under a separate licence from the WanGP licensor
