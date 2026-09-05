# One image, three entrypoints: api, worker, seed. ADR-0003 §2 — moving from a
# cron batch worker to a persistent pool must be a process-type change, not a
# rebuild of anything.
#
# ADR-0097: one embedder now serves everything (`Qwen/Qwen3-Embedding-0.6B`), and it
# needs torch — ~800MB on CPU, ~3GB on CUDA. `EMBEDDER_BACKEND` below is how that cost
# lands where it is wanted and nowhere else.
#
# ADR-0087: the build context is the REPOSITORY ROOT, not apps/api. `spoin` takes
# a path dependency on the sibling package `apps/frog`, and a context rooted at
# apps/api cannot reach `../frog` at all. This is the packaging friction task 0038
# budgeted for; it is paid here so the dependency direction stays a fact of the
# filesystem rather than a convention.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Which torch, if any. Not a convenience: api, worker, seed, test and universe-seed all
# build from this one file, and they do not want the same thing.
#
#   gpu  -- the worker. cu128 for the RTX 5070's Blackwell compute capability 12.0;
#           apps/frog/Dockerfile's header explains why an earlier CUDA build fails at
#           the first kernel launch rather than at build time.
#   cpu  -- the api and the test suite. `Qwen3Embedder` passes `device=None`, so
#           sentence-transformers picks CPU when no CUDA is present and the code path
#           is identical to the GPU one. Only the wheel differs.
#   none -- seed and universe-seed, which run alembic and never embed anything.
#
# The index is pinned per value rather than left to resolution, for the reason
# apps/frog/Dockerfile gives: an unpinned `torch` can be satisfied by a CPU-only wheel
# from PyPI, and that failure surfaces at the first `.to("cuda")` instead of here.
ARG EMBEDDER_BACKEND=none

# Its own layer, ahead of every COPY: it is the slowest layer by an order of magnitude
# and must not be invalidated by a dependency edit.
RUN set -eu; \
    case "$EMBEDDER_BACKEND" in \
      gpu)  pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 torch ;; \
      cpu)  pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch ;; \
      none) : ;; \
      *)    echo "EMBEDDER_BACKEND must be gpu, cpu or none (got '$EMBEDDER_BACKEND')" >&2; exit 1 ;; \
    esac

# Weights are ~1.2GB and a `--rm` container throws them away. Every service that embeds
# mounts the same cache volume the `frog` service uses -- same model, downloaded once.
ENV HF_HOME=/cache/huggingface

# Dependency layer first so source edits do not reinstall the world. frog is
# installed BEFORE spoin because spoin imports it (`spoin.embeddings` builds
# frog's Embedder classes) -- installing in dependency order keeps a broken
# boundary visible at build time rather than at import time.
COPY apps/frog/pyproject.toml /app/frog/pyproject.toml
RUN set -eu; \
    mkdir -p /app/frog/src/frog && touch /app/frog/src/frog/__init__.py; \
    extras="dev,embeddings"; \
    [ "$EMBEDDER_BACKEND" = none ] || extras="$extras,embeddings-gpu"; \
    pip install --no-cache-dir -e "/app/frog[$extras]"

COPY apps/api/pyproject.toml apps/api/README.md ./
RUN mkdir -p src/spoin && touch src/spoin/__init__.py \
    && pip install --no-cache-dir -e ".[dev,generation,embeddings]"

COPY apps/frog/src /app/frog/src
COPY apps/frog/alembic.ini /app/frog/alembic.ini
COPY apps/frog/alembic /app/frog/alembic
COPY apps/frog/tests /app/frog/tests

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/src ./src
COPY apps/api/tests ./tests

EXPOSE 8000

CMD ["uvicorn", "spoin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
