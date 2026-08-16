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

from slocho.api.routers import engagement, feed, topics
from slocho.core.config import get_settings
from slocho.core.db import get_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Slocho API",
        version="0.1.0",
        summary="Swipeable AI-generated knowledge cards",
        description=(
            "The feed read path never touches an LLM. Generation is an offline "
            "batch process filling a shared corpus; this service selects, filters "
            "and ranks over that corpus."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(feed.router)
    app.include_router(topics.router)
    app.include_router(engagement.router)

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
