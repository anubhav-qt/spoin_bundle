# One image, three entrypoints: api, worker, seed. ADR-0003 §2 — moving from a
# cron batch worker to a persistent pool must be a process-type change, not a
# rebuild of anything.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first so source edits do not reinstall the world.
COPY pyproject.toml README.md ./
RUN mkdir -p src/slocho && touch src/slocho/__init__.py \
    && pip install --no-cache-dir -e ".[dev]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY tests ./tests

EXPOSE 8000

CMD ["uvicorn", "slocho.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
