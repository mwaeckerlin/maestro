# Open Tasks

One line per task, newest on top: date, status, who asked. An entry is removed when the task is implemented, entered in [FEATURES.md](FEATURES.md), tested green and entered in [TESTS.md](TESTS.md).

## Maintainer

- 2026-09-26 blocked, decision of Marc, F11 arm64 image for the NVIDIA GB10: `npm run test:arm64` measured five of upstream's 82 requirements without an aarch64 distribution, also with the PyTorch CUDA 13 index: `onnxruntime-gpu==1.25.0.dev20260210001` (and with it `rembg[gpu]`, which Maestro imports at start), `decord==0.6.0`, `taichi==1.7.4`, and `smplfitter`, which resolves only without build isolation. arm64 needs replacements upstream does not test (CPU `onnxruntime`, `eva-decord`, `taichi` built from source) or goes without the functions that use them.
- 2026-09-26 open, Marc: GPU suite `npm run test:gpu` has not run, there is no NVIDIA GPU on the build host
