"""Request correlation middleware.

Built against a throwaway app rather than the real one: this is about the
middleware's own contract (assign an id, echo it, log the outcome, convert an
unhandled exception into an opaque 500) and nothing about Spoin's routes, so it
needs no database and runs everywhere.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI

from spoin.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from spoin.core.logging import request_id_var


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)

    @application.get("/ok")
    async def ok() -> dict[str, str]:
        # Proves the id is readable from anywhere in the request, which is what
        # makes it useful to the loggers further down the stack.
        return {"seen": request_id_var.get()}

    @application.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("this should not reach the client")

    return application


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_assigns_and_echoes_a_request_id(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/ok")

    assert response.status_code == 200
    assigned = response.headers[REQUEST_ID_HEADER]
    assert assigned
    # The handler saw the same id the caller got back.
    assert response.json()["seen"] == assigned


async def test_honours_an_id_the_edge_already_assigned(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/ok", headers={REQUEST_ID_HEADER: "edge-abc-123"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-abc-123"
    assert response.json()["seen"] == "edge-abc-123"


async def test_a_hostile_inbound_id_is_replaced(app: FastAPI) -> None:
    """The header reaches a log line and a response header, and it comes from
    the client — so a non-printable value is discarded rather than propagated."""

    async with await _client(app) as client:
        response = await client.get("/ok", headers={REQUEST_ID_HEADER: "bad\tvalue"})

    assert response.headers[REQUEST_ID_HEADER] != "bad\tvalue"


async def test_an_overlong_inbound_id_is_truncated(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/ok", headers={REQUEST_ID_HEADER: "x" * 500})

    assert len(response.headers[REQUEST_ID_HEADER]) == 64


async def test_unhandled_exception_becomes_an_opaque_500(app: FastAPI) -> None:
    async with await _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    # The message never reaches the caller; the id that finds it in the log does.
    assert "this should not reach the client" not in response.text
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_unhandled_exception_is_logged_with_a_traceback(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="spoin.api.request"):
        async with await _client(app) as client:
            await client.get("/boom")

    record = next(r for r in caplog.records if r.name == "spoin.api.request")
    assert record.exc_info is not None, "the traceback is the point"


async def test_context_does_not_leak_between_requests(app: FastAPI) -> None:
    async with await _client(app) as client:
        first = (await client.get("/ok")).json()["seen"]
        second = (await client.get("/ok")).json()["seen"]

    assert first != second
    # And nothing is left set on the ambient context afterwards.
    assert request_id_var.get() == "-"
