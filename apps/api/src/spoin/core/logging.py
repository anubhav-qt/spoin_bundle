"""Logging setup and request correlation.

The API layer had no logging at all: every logger in the codebase lived under
`generation/` or `worker/`, and the FastAPI app never called `basicConfig`, so a
500 in production surfaced as an uncaught traceback on stdout with nothing tying
it to a request, a user, or the background job it may have enqueued.

Deliberately small. One formatter, one context variable, one middleware — no
structured-logging dependency, no log shipper, no correlation framework. The
thing that was missing is the ability to answer "what else happened during that
request", and a request id threaded through the existing stdlib logging is
enough to answer it.

The id is taken from an inbound `X-Request-ID` when a proxy already set one, so
a trace started at the edge stays one trace, and echoed back on the response so
a user reporting a failure can quote it.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

#: Set per request by `RequestContextMiddleware`, read by the filter below.
#: A ContextVar rather than a thread-local: FastAPI serves many requests on one
#: thread, and asyncio's context propagation is what keeps these from bleeding
#: into each other across `await` points.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")


class ContextFilter(logging.Filter):
    """Injects the current request/user id into every record.

    A filter rather than a custom Logger or an adapter, so `logging.getLogger`
    keeps working unchanged everywhere — including the generation and worker
    loggers that predate this module and know nothing about it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        return True


_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s user=%(user_id)s] %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Idempotent — safe to call from the API, the worker and the scripts.

    Uses `force=True` so an entrypoint that already called `basicConfig` (the
    worker, `generate_topics.py`) ends up with this handler rather than two
    handlers duplicating every line.
    """

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(ContextFilter())

    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)

    # These two are noisy and say nothing our own request log does not.
    # uvicorn.error keeps its level — that is where startup/shutdown lives.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def new_request_id() -> str:
    """Short enough to quote in a support conversation, long enough not to
    collide within a retention window."""

    return uuid.uuid4().hex[:12]
