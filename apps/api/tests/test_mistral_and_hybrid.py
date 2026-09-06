"""The Mistral transport, and the ladder-based routing that decides who gets a call.

No network: `MistralClient` is driven through a stubbed `httpx.AsyncClient`, which is
the right seam here -- what is under test is our retry, our logging and our schema
conversion, not Mistral's behaviour. Mistral's behaviour is what the committed probe
and task 10's JSONL are for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from spoin.core.config import Settings
from spoin.generation.hybrid import _has_image
from spoin.generation.mistral import MistralCallError, MistralClient, strict_json_schema


class _WireItem(BaseModel):
    index: int = 0
    text: str = ""
    note: str | None = None


class _WireBatch(BaseModel):
    items: list[_WireItem] = Field(default_factory=list)


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        mistral_api_keys="k1,k2",
        mistral_log_dir=str(tmp_path / "mistral"),
        mistral_backoff_base_seconds=0.0,
        **overrides,
    )


class _StubTransport:
    """Stands in for `httpx.AsyncClient`, replaying a scripted sequence of responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: dict[str, str], json: Any) -> httpx.Response:
        self.requests.append({"url": url, "headers": headers, "json": json})
        response = self._responses[min(len(self.requests) - 1, len(self._responses) - 1)]
        if isinstance(response, Exception):  # pragma: no cover - typed for clarity
            raise response
        return response

    async def aclose(self) -> None:
        return None


def _ok(payload: dict[str, Any], **headers: str) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return httpx.Response(200, json=body, headers={"x-request-id": "req-1", **headers})


def _err(status: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"message": "nope"}, headers=headers)


def _client(tmp_path: Path, responses: list[httpx.Response], **overrides: Any) -> MistralClient:
    client = MistralClient(_settings(tmp_path, **overrides))
    client._client = _StubTransport(responses)  # type: ignore[assignment]
    return client


# ------------------------------------------------------------------- schema --


def test_strict_schema_forbids_extra_properties_and_requires_every_key() -> None:
    schema = strict_json_schema(_WireBatch)
    item = schema["$defs"]["_WireItem"]
    assert item["additionalProperties"] is False
    # Every property, not just the ones Pydantic marked required -- strict mode has
    # no notion of an optional key.
    assert sorted(item["required"]) == ["index", "note", "text"]
    assert schema["additionalProperties"] is False


def test_strict_schema_strips_defaults() -> None:
    """`default` is what actually breaks the request: every `_Wire*` field has one."""

    dumped = json.dumps(strict_json_schema(_WireBatch))
    assert '"default"' not in dumped


def test_strict_schema_keeps_the_nullable_branch() -> None:
    """`X | None` still expresses "may be absent" -- the key is present, value nullable."""

    note = strict_json_schema(_WireBatch)["$defs"]["_WireItem"]["properties"]["note"]
    assert {"type": "null"} in note["anyOf"]


# ---------------------------------------------------------------- transport --


@pytest.mark.asyncio
async def test_a_successful_call_parses_and_logs_the_full_body(tmp_path: Path) -> None:
    client = _client(tmp_path, [_ok({"items": [{"index": 0, "text": "hi", "note": None}]})])

    result = await client.invoke(_WireBatch, [("system", "s"), ("human", "u")])
    assert [item.text for item in result.items] == ["hi"]

    records = _records(client)
    assert len(records) == 1
    assert records[0]["outcome"] == "ok"
    assert records[0]["status"] == 200
    # The whole response body on SUCCESS too -- the complete record is what diagnoses
    # malformed structured output later (owner's call).
    assert records[0]["body"]["choices"][0]["message"]["content"]
    assert records[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}
    assert records[0]["headers"]["x-request-id"] == "req-1"
    assert records[0]["in_flight_at_send"] == 1


@pytest.mark.asyncio
async def test_prompt_roles_map_to_openai_shape(tmp_path: Path) -> None:
    client = _client(tmp_path, [_ok({"items": []})])
    await client.invoke(_WireBatch, [("system", "s"), ("human", "u")])

    sent = client._client.requests[0]["json"]  # type: ignore[attr-defined]
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_a_429_is_retried_and_then_succeeds(tmp_path: Path) -> None:
    client = _client(
        tmp_path,
        [_err(429, **{"retry-after": "0"}), _ok({"items": [{"index": 0, "text": "ok"}]})],
    )
    result = await client.invoke(_WireBatch, [("human", "u")])
    assert result.items[0].text == "ok"

    outcomes = [r["outcome"] for r in _records(client)]
    assert outcomes == ["http_429", "ok"]


@pytest.mark.asyncio
async def test_a_400_is_not_retried(tmp_path: Path) -> None:
    """Retrying a request we got wrong is spend without a hypothesis."""

    client = _client(tmp_path, [_err(400)])
    with pytest.raises(MistralCallError):
        await client.invoke(_WireBatch, [("human", "u")])
    assert len(client._client.requests) == 1  # type: ignore[attr-defined]
    assert _records(client)[0]["retryable"] is False


@pytest.mark.asyncio
async def test_exhausting_every_attempt_raises_a_call_failure(tmp_path: Path) -> None:
    """`MistralCallError`, NOT a QuotaExhaustedError -- a Mistral outage must stay
    visible as a Mistral outage rather than reading as a spent Gemini grid."""

    from spoin.generation.quota import QuotaExhaustedError

    client = _client(tmp_path, [_err(503)], mistral_max_attempts=3)
    with pytest.raises(MistralCallError) as caught:
        await client.invoke(_WireBatch, [("human", "u")])
    assert not isinstance(caught.value, QuotaExhaustedError)
    assert len(client._client.requests) == 3  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_200_with_unparseable_content_is_bad_schema_not_a_throttle(
    tmp_path: Path,
) -> None:
    """A different fact from a 429, and logged as one: it says the model did not hold
    our schema, which no amount of pacing fixes."""

    broken = httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    client = _client(tmp_path, [broken], mistral_max_attempts=2)
    with pytest.raises(MistralCallError):
        await client.invoke(_WireBatch, [("human", "u")])

    records = _records(client)
    assert [r["outcome"] for r in records] == ["bad_schema", "bad_schema"]
    assert all(r["status"] == 200 for r in records)


@pytest.mark.asyncio
async def test_keys_round_robin(tmp_path: Path) -> None:
    client = _client(tmp_path, [_err(500)], mistral_max_attempts=3)
    with pytest.raises(MistralCallError):
        await client.invoke(_WireBatch, [("human", "u")])
    assert [r["key_index"] for r in _records(client)] == [0, 1, 0]


@pytest.mark.asyncio
async def test_multimodal_content_is_refused_rather_than_flattened(tmp_path: Path) -> None:
    """`ministral-8b` is text-only. A repair that silently lost its rendered image
    would produce a plausible fix for something the model never saw."""

    client = _client(tmp_path, [_ok({"items": []})])
    with pytest.raises(MistralCallError, match="text-only"):
        await client.invoke(_WireBatch, [("human", [{"type": "image_url"}])])


def _records(client: MistralClient) -> list[dict[str, Any]]:
    lines = client._log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ------------------------------------------------------------------ routing --


def test_has_image_detects_a_multimodal_prompt() -> None:
    text_only: list[tuple[str, Any]] = [("system", "s"), ("human", "u")]
    assert _has_image(text_only) is False

    with_image: list[tuple[str, Any]] = [
        ("system", "s"),
        ("human", [{"type": "text", "text": "t"}, {"type": "image_url", "image_url": "data:..."}]),
    ]
    assert _has_image(with_image) is True

    # A content list that is only text parts is still safe to send.
    text_parts: list[tuple[str, Any]] = [("human", [{"type": "text", "text": "t"}])]
    assert _has_image(text_parts) is False
