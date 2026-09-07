"""The FastAPI application.

This service is the single source of truth for all clients — the web app today,
React Native later. Both talk to it over HTTP with no privileged access. If the web
client can do something the mobile client can't, that is a bug.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from spoin.api.middleware import RequestContextMiddleware
from spoin.api.routers import (
    admin_ascii,
    admin_repairs,
    ask,
    auth,
    dev,
    engagement,
    feed,
    notes,
    profile,
    quiz,
    reports,
    topics,
)
from spoin.api.routers.feed import cards_router
from spoin.core.config import get_settings
from spoin.core.db import get_engine
from spoin.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Spoin API",
        version="0.1.0",
        summary="Swipeable AI-generated knowledge cards",
        description=(
            "The feed read path never touches an LLM. Generation is an offline "
            "batch process filling a shared corpus; this service selects, filters "
            "and ranks over that corpus."
        ),
        lifespan=lifespan,
    )

    # Order matters and is the reverse of registration: the LAST middleware
    # added is the outermost. CORS has to end up outside the request-context
    # one, or the 500 response that middleware synthesises would go back to a
    # browser without CORS headers and surface as an opaque network error
    # instead of the 500 it actually is.
    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(feed.router)
    app.include_router(cards_router)
    app.include_router(topics.router)
    app.include_router(quiz.router)
    app.include_router(engagement.router)
    app.include_router(notes.router)
    app.include_router(profile.router)
    app.include_router(reports.router)
    app.include_router(ask.router)

    # `/dev/*` mutates a user's whole state on one call, and `/admin/repairs/*`
    # (ADR-0076) can retire a card and spend LLM calls -- neither has a role
    # check (there is no admin role yet), so both are gated to non-production on
    # the `env` switch that already gates the JWT-secret validator below, rather
    # than inventing a second flag. Task 0035 replaces this with a real gate.
    # (The B4 `/admin/quota` read surface that used to mount here was archived
    # to docs/archive/b4-quota-panel/ -- SQL is used instead.)
    if settings.env != "production":
        app.include_router(dev.router)
        app.include_router(admin_repairs.router)
        app.include_router(admin_ascii.router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, Any]:
        """Liveness plus a real database round-trip.

        Also the target for the cron ping that keeps the free-tier instance from
        sleeping after ~15 minutes idle (ADR-0003).
        """

        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ok", "env": settings.env}

    return app


app = create_app()
