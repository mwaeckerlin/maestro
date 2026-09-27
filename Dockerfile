# Ubuntu and not the Alpine very-base: PyTorch and the CUDA wheels exist for
# glibc only, so the build stage is mwaeckerlin/ubuntu-very-base and the final
# stage mwaeckerlin/ubuntu-scratch, the Ubuntu counterparts of very-base and
# scratch.

#### build: the upstream source and its Python environment ####
FROM mwaeckerlin/ubuntu-very-base AS build
RUN $PKG_INSTALL ca-certificates curl git python3 build-essential nodejs npm ffmpeg libgl1 libglib2.0-0 libportaudio2
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
ENV UV_PYTHON_INSTALL_DIR="/opt/maestro/python" \
    UV_CACHE_DIR="/root/.cache/uv" \
    npm_config_cache="/root/.npm" \
    UV_LINK_MODE="copy" \
    UV_COMPILE_BYTECODE="1" \
    VIRTUAL_ENV="/opt/maestro/venv" \
    # A slow or interrupted package feed must make the build slow, never make it
    # fail: upstream pulls onnxruntime-gpu from a nightly feed that timed out
    # after 30s, and on a flaky link the large CUDA wheels broke off and failed
    # after the default three retries.
    UV_HTTP_TIMEOUT="600" \
    UV_HTTP_RETRIES="10" \
    UV_CONCURRENT_DOWNLOADS="2"
COPY bin /opt/maestro/bin
# The upstream source, main branch by default; BuildKit compares the remote
# commit on every build, so a new upstream commit rebuilds from here.
ARG MAESTRO_SOURCE="https://github.com/Blizaine/Maestro.git#main"
ADD ${MAESTRO_SOURCE} /opt/maestro/src
WORKDIR /opt/maestro/src
# The Python version of upstream's CUDA 13 runtime, read from its launcher.
RUN uv venv --managed-python --python "$(python3 /opt/maestro/bin/upstream-install.py python-version)" "${VIRTUAL_ENV}"

#### install: the steps of upstream's install.js, without Pinokio ####
# The cache ids are those of the earlier ubuntu-base build, so the packages
# already downloaded there are used again.
FROM build AS install
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py requirements
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py onnxruntime-gpu
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    uv pip install hf-xet pip
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py torch
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py aarch64-extras
# Both helpers of upstream install optional kernels and report a missing wheel
# instead of failing, the way they do under Pinokio; where every Linux wheel a
# helper names is for another architecture, it is skipped.
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py optional-kernels scripts/install_optional_cuda_acceleration.py
RUN --mount=type=cache,id=/home/somebody/.cache/uv,target=/root/.cache/uv \
    python3 /opt/maestro/bin/upstream-install.py optional-kernels scripts/install_gguf_kernels.py
RUN python3 /opt/maestro/bin/upstream-install.py seedvc
# Maestro runs the component, it never updates it through git
RUN rm -rf app/postprocessing/seedvc/.git
WORKDIR /opt/maestro/src/ui
RUN --mount=type=cache,id=/home/somebody/.npm,target=/root/.npm npm ci
# Relative asset URLs, so the interface also works below a path prefix.
RUN npm run build -- --base=./
COPY app/maestro-base-path.js dist/maestro-base-path.js
RUN sed -i 's#<head>#<head><script src="./maestro-base-path.js"></script>#' dist/index.html
RUN grep -q 'src="./maestro-base-path.js"' dist/index.html
RUN rm -rf node_modules
WORKDIR /opt/maestro/src
COPY app/maestro_serve.py app/maestro_serve.py
RUN "${VIRTUAL_ENV}/bin/python" -m compileall -q app

# The runtime closure for the final stage: the shared libraries of every
# binary in /opt/maestro, ffmpeg for the media pipeline, git for plugin
# installation, and gcc with the C library headers, because Triton compiles
# its CUDA launchers with the C compiler when a model runs for the first time.
RUN python3 /opt/maestro/bin/collect-runtime.py /runtime \
      --scan /opt/maestro \
      --files /usr/bin/ffmpeg /usr/bin/ffprobe \
              /usr/bin/git /usr/lib/git-core /usr/share/git-core \
              /usr/bin/gcc /usr/bin/cc \
              /etc/ssl/certs /usr/share/ca-certificates \
              /etc/ld.so.conf /etc/ld.so.conf.d /sbin \
      --packages 'gcc-[0-9]*' 'cpp-[0-9]*' 'libgcc-[0-9]*-dev' 'binutils*' \
                 libc6-dev linux-libc-dev libcrypt-dev libportaudio2
# Triton and ctypes run `/sbin/ldconfig -p` to find libcuda. Where Ubuntu ships
# /sbin/ldconfig as a shell script around ldconfig.real, the binary takes its
# name, because the final image has no shell to run the script.
RUN if [ -e /usr/sbin/ldconfig.real ]; then LDCONFIG=/usr/sbin/ldconfig.real; else LDCONFIG=/usr/sbin/ldconfig; fi \
    && install -D -m 755 "${LDCONFIG}" /runtime/usr/sbin/ldconfig \
    && "${LDCONFIG}" -r /runtime
RUN install -d -m 1777 /runtime/tmp
RUN install -d /volumes/models /volumes/output /volumes/state

#### the final image: no shell, no package manager ####
FROM mwaeckerlin/ubuntu-scratch
ENV CONTAINERNAME="maestro" \
    PATH="/opt/maestro/venv/bin:/usr/local/bin:/usr/bin" \
    VIRTUAL_ENV="/opt/maestro/venv" \
    MAESTRO_HOST="0.0.0.0" \
    MAESTRO_PORT="42003" \
    MAESTRO_MODEL_DIR="/models" \
    MAESTRO_OUTPUT_DIR="/output" \
    MAESTRO_STATE_DIR="/state" \
    MAESTRO_CONFIG="" \
    HF_HOME="/models/huggingface" \
    TRITON_CACHE_DIR="/tmp/triton" \
    GIT_PYTHON_GIT_EXECUTABLE="/usr/bin/git" \
    PYTHONUNBUFFERED="1" \
    PYTHONUTF8="1" \
    HF_HUB_DISABLE_TELEMETRY="1" \
    GRADIO_ANALYTICS_ENABLED="False" \
    DO_NOT_TRACK="1" \
    NVIDIA_VISIBLE_DEVICES="all" \
    NVIDIA_DRIVER_CAPABILITIES="compute,utility,video"
EXPOSE 42003
VOLUME ["/models", "/output"]
# The engine import takes minutes on a first start; the interface at / answers
# only once everything is up.
HEALTHCHECK --interval=30s --timeout=15s --start-period=900s --retries=3 \
    CMD ["/opt/maestro/venv/bin/python", "/opt/maestro/src/app/maestro_serve.py", "--health"]
WORKDIR /state
ENTRYPOINT ["/opt/maestro/venv/bin/python", "/opt/maestro/src/app/maestro_serve.py"]
COPY --from=install /runtime/ /
COPY --from=install --chown=0:0 /opt/maestro/python /opt/maestro/python
COPY --from=install --chown=0:0 /opt/maestro/venv /opt/maestro/venv
COPY --from=install --chown=0:0 /opt/maestro/src /opt/maestro/src
COPY --from=install --chown=${RUN_USER}:${RUN_GROUP} /volumes/ /
