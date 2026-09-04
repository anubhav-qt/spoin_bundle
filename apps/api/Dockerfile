# One image, three entrypoints: api, worker, seed. ADR-0003 §2 — moving from a
# cron batch worker to a persistent pool must be a process-type change, not a
# rebuild of anything.
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

# Dependency layer first so source edits do not reinstall the world. frog is
# installed BEFORE spoin because spoin imports it (`spoin.embeddings` builds
# frog's Embedder classes) -- installing in dependency order keeps a broken
# boundary visible at build time rather than at import time.
COPY apps/frog/pyproject.toml /app/frog/pyproject.toml
RUN mkdir -p /app/frog/src/frog && touch /app/frog/src/frog/__init__.py \
    && pip install --no-cache-dir -e "/app/frog[dev,embeddings]"

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
