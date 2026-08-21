"""Request correlation and the one place unhandled errors get logged.

Kept out of `main.py` so `create_app` stays a wiring function you can read in
one screen.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from spoin.core.logging import new_request_id, request_id_var, user_id_var

logger = logging.getLogger("spoin.api.request")

REQUEST_ID_HEADER = "X-Request-ID"

#: Health is polled continuously by the keep-alive cron (ADR-0003) — logging
#: every hit would drown everything else at a ratio of roughly 100:1.
_QUIET_PATHS = frozenset({"/health"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, logs the outcome, and converts an unhandled
    exception into a 500 that says nothing useful to an attacker while logging
    everything useful to us.

    Without this last part an unhandled exception propagated to Starlette's
    default handler, which re-raises it: the traceback landed on stdout with no
    request id and no path attached, and — depending on how the app is served —
    could reach the client.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an id the edge already assigned so one trace stays one trace.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        # Bounded and sanitised: this value reaches a log line and a response
        # header, and it arrives from the client.
        request_id = incoming[:64] if incoming.isascii() and incoming.isprintable() else ""
        request_id = request_id or new_request_id()

        token = request_id_var.set(request_id)
        user_token = user_id_var.set("-")
        started = time.perf_counter()
        quiet = request.url.path in _QUIET_PATHS

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # `exception` and not `error`: the traceback is the entire point.
            logger.exception(
                "%s %s -> 500 unhandled (%.1fms)",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            response = JSONResponse(
                status_code=500,
                # Deliberately opaque. The request id is what makes it
                # actionable — the caller quotes it, we grep for it.
                content={"detail": "Internal server error", "request_id": request_id},
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(token)
            user_id_var.reset(user_token)

        elapsed_ms = (time.perf_counter() - started) * 1000
        if not quiet:
            # 5xx at ERROR so alerting can key off level alone; 4xx stays INFO
            # because a 401 or a 409 is usually the API working correctly.
            level = logging.ERROR if response.status_code >= 500 else logging.INFO
            logger.log(
                level,
                "%s %s -> %d (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
