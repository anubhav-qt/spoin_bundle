# The `frog` image: corpus ingestion, and the only image in this project with a GPU.
#
# Separate from apps/api/Dockerfile rather than an extra layer on it, because the two
# have opposite requirements. The api image deploys and must stay small; this one
# carries torch and a CUDA runtime (~3GB) and never deploys anywhere — ADR-0092 put
# generation and bulk embedding on the owner's machine, and only the app backend goes
# online. Folding torch into the api image would put 3GB into every service that builds
# from it (api, worker, seed, test) to serve one command.
#
# ADR-0087: build context is the REPOSITORY ROOT, like every other service here.

# Same base as apps/api/Dockerfile, deliberately, and NOT an `nvidia/cuda` image.
#
# The CUDA base was the obvious first choice and it does not work: `nvidia/cuda`'s
# Ubuntu 24.04 tags ship Python 3.12, and this project is 3.13 — `apt-get install
# python3.13` fails outright, and reaching for the deadsnakes PPA to bolt a second
# interpreter onto a 3GB base image is a lot of machinery for nothing.
#
# It buys nothing either, because PyTorch's cu128 wheels **bundle the CUDA runtime and
# cuDNN as ordinary pip packages** (`nvidia-cuda-runtime-cu12`, `nvidia-cudnn-cu12`,
# and friends). What a container genuinely cannot bring is the *driver*, and that is
# injected from the host by nvidia-container-toolkit regardless of base image. So a
# plain Python image plus the cu128 index is both smaller and one less thing to keep in
# step with apps/api.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Weights are ~1.2GB and the container is `--rm`'d after every run. Without the
    # cache volume mounted here, every ingestion re-downloads Qwen3-Embedding-0.6B.
    HF_HOME=/cache/huggingface

WORKDIR /app/frog

# torch first, from the cu128 index, and in its own layer. Two reasons it is not folded
# into the install below: it is the slowest layer by an order of magnitude and should
# not be invalidated by a pyproject edit, and pinning the index here means the
# dependency resolution below cannot quietly satisfy `torch` with a CPU-only wheel from
# PyPI — which fails at the first `.to("cuda")` rather than at build time.
#
# cu128 specifically: the RTX 5070 is Blackwell (compute capability 12.0), and earlier
# CUDA builds emit no kernel image for it. That failure surfaces at the first CUDA call
# as "no kernel image is available for execution on the device", which reads like a
# driver problem and is not one.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 torch

COPY apps/frog/pyproject.toml /app/frog/pyproject.toml
RUN mkdir -p /app/frog/src/frog && touch /app/frog/src/frog/__init__.py \
    && pip install --no-cache-dir -e "/app/frog[dev,embeddings-gpu]"

COPY apps/frog/src /app/frog/src
COPY apps/frog/alembic.ini /app/frog/alembic.ini
COPY apps/frog/alembic /app/frog/alembic
COPY apps/frog/tests /app/frog/tests

# The corpus lives under docs/, mounted at run time rather than copied — it is authored
# continuously by another track, and an image rebuild per delivery would be absurd.
WORKDIR /repo

ENTRYPOINT ["python", "-m", "frog.ingest"]
