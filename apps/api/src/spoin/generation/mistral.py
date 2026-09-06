"""Mistral's chat-completions transport, over raw `httpx`.

ADR-0090 and docs/architecture/generation-pipeline-v2.md §2-3. The generator ladder's
prose calls run here; the thinking ladder's verdicts stay on Gemini. This module is the
transport only -- it builds no prompts and knows no domain types beyond "parse the
response into this Pydantic model", which is what lets `HybridContentGenerator` reuse
every prompt `GeminiContentGenerator` already builds.

**What is deliberately NOT here.** No key pool, no box leasing, no quota ledger, no
load balancer, no send-gap pacing, no rung ladder. Those exist to survive Gemini's
IP-keyed concurrency wall, and the mistral-saga measured Mistral not to have one --
no wall through N=5, zero 429s in 641 calls. Porting them would be carrying four weeks
of scar tissue onto a provider without the wound (ADR-0090). Mistral gets a semaphore,
a send path and retry.

**We do not know Mistral's failure shape, so we log everything and classify nothing**
(owner's call). Every attempt writes a JSONL line carrying the status, *all* response
headers (rate-limit headers are how we learn its limits without documentation), the
latency, the in-flight count at send, prompt size, reported usage, the request id and
**the full response body on success as well as failure**. The taxonomy gets derived
from real runs, not guessed at now -- that discipline is the one thing the gemini-saga
cost bought.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from spoin.core.config import Settings

logger = logging.getLogger(__name__)

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

#: OpenAI-shaped chat endpoint. The probe (`spoin/probes/mistral_probe.py`) exercised
#: exactly this path 646 times at 12k tokens before anything was built on it.
_CHAT_PATH = "/chat/completions"

#: ADR-0085's estimator, reused so this number and the load balancer's are the same
#: kind of number.
_CHARS_PER_TOKEN = 4


class MistralCallError(RuntimeError):
    """A Mistral call that never returned a usable verdict.

    A **call failure**, never a rejection (CLAUDE.md): the caller's existing
    `except Exception` turns this into a `BatchResult` failure, which is counted
    separately from content that was judged and found bad. Deliberately NOT a
    `QuotaExhaustedError` subclass -- those mean Gemini's grid is spent, and a
    Mistral outage must stay visible as a Mistral outage rather than borrowing a
    vocabulary that would make a report read as a quota problem.
    """


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A Pydantic model's JSON schema, in the shape strict structured output wants.

    `response_format: {type: json_schema, strict: true}` requires every object to
    declare `additionalProperties: false` and to list **every** property in
    `required`; it rejects `default`, and it rejects the format/annotation keywords
    Pydantic emits for free. Pydantic's own `model_json_schema()` does none of that,
    so this walks the schema (`$defs` included -- refs are supported and are how
    nested wire models stay readable) and fixes it in place.

    Optionality still works: a field typed `X | None` keeps its `anyOf` with a null
    branch, which is how strict mode expresses "may be absent" -- the key is present,
    the value may be null, and `_LenientWireModel` already tolerates that.
    """

    schema = model.model_json_schema()
    _strictify(schema)
    return schema


#: Keywords strict mode rejects outright. `default` is the load-bearing one: every
#: `_Wire*` field has one, and leaving them in makes the API reject the whole request
#: with a schema error rather than anything that looks like a model problem.
_UNSUPPORTED_KEYWORDS = ("default", "format", "examples", "$comment", "readOnly", "writeOnly")


def _strictify(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _strictify(item)
        return
    if not isinstance(node, dict):
        return

    for keyword in _UNSUPPORTED_KEYWORDS:
        node.pop(keyword, None)

    if node.get("type") == "object" or "properties" in node:
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            #: Every property, not just the ones Pydantic marked required. Strict
            #: mode has no notion of an optional key.
            node["required"] = list(properties)

    for value in node.values():
        _strictify(value)


class MistralClient:
    """One key rotation, one retry policy, one JSONL log, one model.

    **There is no in-flight cap.** The semaphore this class was built around is gone:
    a real run found no 429s at all without it (owner, 2026-09-06), which is the
    opposite of the Gemini result the caution was inherited from -- Google's free-tier
    edge sheds on concurrency with a hard wall between 3 and 4, and Mistral simply does
    not. ADR-0090's `mistral_max_in_flight` went with it.

    What still bounds concurrency is `httpx.Limits(max_connections=128)` below, per
    client. **One client per model, so a hybrid run with a Mistral thinker has two**,
    and the real ceiling is their sum rather than 128. That is a deliberate consequence
    rather than an oversight -- the two ladders have different models and different
    retry histories to keep apart -- but it means the ceiling nobody has measured is
    256, not 128.
    """

    def __init__(self, settings: Settings, model: str | None = None) -> None:
        self._keys = settings.mistral_api_key_list
        if not self._keys:
            raise ValueError(
                "SPOIN_MISTRAL_API_KEYS is empty. Set it to a comma-separated list "
                "(one key is fine; the client round-robins over however many it has)."
            )
        self._base_url = settings.mistral_base_url.rstrip("/")
        self._model = model or settings.mistral_model
        self._timeout = settings.mistral_timeout_seconds
        self._max_attempts = settings.mistral_max_attempts
        self._backoff_base = settings.mistral_backoff_base_seconds
        self._max_tokens = settings.mistral_max_output_tokens
        self._temperature = settings.mistral_temperature

        #: Tracked but never gated on: `in_flight_at_send` is what the JSONL records
        #: on every call, and it is the only evidence that the no-semaphore decision
        #: keeps holding as batch sizes grow.
        self._in_flight = 0
        self._state_lock = asyncio.Lock()
        self._key_cursor = 0

        limits = httpx.Limits(max_connections=128, max_keepalive_connections=64)
        self._client = httpx.AsyncClient(timeout=self._timeout, limits=limits)

        self._log_path = _run_log_path(settings.mistral_log_dir)
        self._log_lock = asyncio.Lock()
        logger.info(
            "mistral: model=%s keys=%d in_flight_cap=none (conn_pool=128) log=%s",
            self._model,
            len(self._keys),
            self._log_path,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> MistralClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def invoke(self, schema: type[_SchemaT], prompt: list[tuple[str, Any]]) -> _SchemaT:
        """One structured-output call, retried, parsed into `schema`.

        Raises `MistralCallError` when every attempt failed. The caller treats that
        as a call failure and continues with the next item -- never as a rejection,
        and never by falling back to Gemini: **no cross-provider fallback**, because
        an outage that silently becomes a Gemini bill is a corpus you cannot
        attribute afterwards (ADR-0090).
        """

        messages = _to_messages(prompt)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lstrip("_").lower(),
                    "schema": strict_json_schema(schema),
                    "strict": True,
                },
            },
        }
        prompt_chars = sum(len(str(m["content"])) for m in messages)
        call_name = schema.__name__

        last_detail = "no attempt was made"
        for attempt in range(1, self._max_attempts + 1):
            parsed, retry_after, last_detail = await self._attempt(
                schema=schema,
                payload=payload,
                call_name=call_name,
                attempt=attempt,
                prompt_chars=prompt_chars,
            )
            if parsed is not None:
                return parsed
            if retry_after is None:
                # Not retryable-looking: a 4xx that is not a throttle. Retrying a
                # malformed request just spends the budget on the same rejection.
                break
            if attempt < self._max_attempts:
                await asyncio.sleep(retry_after)

        raise MistralCallError(
            f"{call_name}: {self._max_attempts} attempt(s) failed -- {last_detail}. "
            f"Full request/response records are in {self._log_path}."
        )

    async def _attempt(
        self,
        *,
        schema: type[_SchemaT],
        payload: dict[str, Any],
        call_name: str,
        attempt: int,
        prompt_chars: int,
    ) -> tuple[_SchemaT | None, float | None, str]:
        """One HTTP round trip. Returns `(parsed, backoff_or_None, detail)`.

        A `None` backoff means "do not retry this" -- the failure is ours, not a
        transient of theirs. Every outcome is logged before it is returned, success
        included, so the JSONL is a complete record rather than a failure log.
        """

        async with self._state_lock:
            key = self._keys[self._key_cursor % len(self._keys)]
            key_index = self._key_cursor % len(self._keys)
            self._key_cursor += 1
            self._in_flight += 1
            in_flight_at_send = self._in_flight

        started = time.monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}{_CHAT_PATH}",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            latency = time.monotonic() - started
            await self._log(
                call=call_name,
                attempt=attempt,
                key_index=key_index,
                status=None,
                latency_s=latency,
                in_flight_at_send=in_flight_at_send,
                prompt_chars=prompt_chars,
                outcome="timeout",
                detail=type(exc).__name__,
            )
            return None, self._backoff(attempt, None), f"timeout after {latency:.1f}s"
        except httpx.HTTPError as exc:
            latency = time.monotonic() - started
            await self._log(
                call=call_name,
                attempt=attempt,
                key_index=key_index,
                status=None,
                latency_s=latency,
                in_flight_at_send=in_flight_at_send,
                prompt_chars=prompt_chars,
                outcome="transport",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return None, self._backoff(attempt, None), f"transport error {type(exc).__name__}"
        finally:
            async with self._state_lock:
                self._in_flight -= 1

        latency = time.monotonic() - started
        status = response.status_code
        body = _safe_body(response)
        usage = body.get("usage") if isinstance(body, dict) else None
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")

        if status != 200:
            #: Retryable-looking, deliberately generous and deliberately not a
            #: taxonomy: 429 (throttle), 408, and every 5xx. Everything else is a
            #: request we got wrong, and retrying it is spend without a hypothesis.
            retryable = status == 429 or status == 408 or status >= 500
            await self._log(
                call=call_name,
                attempt=attempt,
                key_index=key_index,
                status=status,
                latency_s=latency,
                in_flight_at_send=in_flight_at_send,
                prompt_chars=prompt_chars,
                outcome=f"http_{status}",
                headers=dict(response.headers),
                body=body,
                usage=usage,
                request_id=request_id,
                retryable=retryable,
            )
            backoff = self._backoff(attempt, _retry_after(response)) if retryable else None
            return None, backoff, f"HTTP {status}: {_snip(response)}"

        try:
            content = body["choices"][0]["message"]["content"]
            parsed = schema.model_validate(json.loads(content))
        except Exception as exc:
            #: A 200 carrying unparseable or schema-invalid JSON is a DIFFERENT
            #: failure from a throttle -- it says the model did not hold our schema
            #: on this call. Retried once or twice because temperature makes it
            #: genuinely transient, and logged with the FULL body so a systematic
            #: schema problem is diagnosable from the record rather than guessed at.
            await self._log(
                call=call_name,
                attempt=attempt,
                key_index=key_index,
                status=status,
                latency_s=latency,
                in_flight_at_send=in_flight_at_send,
                prompt_chars=prompt_chars,
                outcome="bad_schema",
                headers=dict(response.headers),
                body=body,
                usage=usage,
                request_id=request_id,
                detail=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
            return (
                None,
                self._backoff(attempt, None),
                f"unparseable response ({type(exc).__name__})",
            )

        await self._log(
            call=call_name,
            attempt=attempt,
            key_index=key_index,
            status=status,
            latency_s=latency,
            in_flight_at_send=in_flight_at_send,
            prompt_chars=prompt_chars,
            outcome="ok",
            headers=dict(response.headers),
            body=body,
            usage=usage,
            request_id=request_id,
        )
        return parsed, None, "ok"

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """Exponential with jitter, but the provider's own `Retry-After` wins.

        Jitter because every worker coroutine that got throttled in the same second
        would otherwise come back in the same second.
        """

        if retry_after is not None:
            return max(0.0, retry_after)
        return self._backoff_base * (2.0 ** (attempt - 1)) * (1.0 + random.random() * 0.25)

    async def _log(
        self,
        *,
        call: str,
        attempt: int,
        key_index: int,
        status: int | None,
        latency_s: float,
        in_flight_at_send: int,
        prompt_chars: int,
        outcome: str,
        headers: dict[str, str] | None = None,
        body: Any = None,
        usage: Any = None,
        request_id: str | None = None,
        detail: str = "",
        retryable: bool | None = None,
    ) -> None:
        """One JSONL line per attempt, plus a one-line summary in the main log.

        The summary matches the existing `lbprobe call` shape so a terminal stays
        readable while the file carries everything.
        """

        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "call": call,
            "attempt": attempt,
            "key_index": key_index,
            "model": self._model,
            "status": status,
            "outcome": outcome,
            "latency_s": round(latency_s, 3),
            "in_flight_at_send": in_flight_at_send,
            "prompt_chars": prompt_chars,
            "prompt_tokens_est": prompt_chars // _CHARS_PER_TOKEN,
            "usage": usage,
            "request_id": request_id,
            "retryable": retryable,
            "detail": detail,
            "headers": headers or {},
            "body": body,
        }
        line = json.dumps(record, default=str, ensure_ascii=False)
        async with self._log_lock:
            try:
                with self._log_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as exc:  # pragma: no cover - a full disk should not kill a run
                logger.warning("mistral: could not write the JSONL record: %s", exc)

        logger.info(
            "mistral call key=%d model=%s attempt=%d latency=%.2f chars=%d "
            "inflight=%d outcome=%s%s",
            key_index,
            self._model,
            attempt,
            latency_s,
            prompt_chars,
            in_flight_at_send,
            outcome,
            f" -- {detail}" if detail else "",
        )


def _run_log_path(log_dir: str) -> Path:
    """One file per run, named so two runs never interleave into one record.

    A file rather than stdout, deliberately: the whole response body on every call
    would drown the pipeline log, and the pipeline log is what a human watches.
    """

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"mistral-{stamp}-{os.getpid()}.jsonl"


def _to_messages(prompt: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """LangChain's `(role, content)` tuples -> OpenAI-shaped messages.

    `human` is LangChain's name for what this API calls `user`. A multimodal content
    list raises rather than being silently flattened: `ministral-8b` is text-only, and
    a card repair that quietly lost its rendered image would produce a plausible repair
    of something the model never saw. `HybridContentGenerator` keeps those on Gemini,
    so reaching this is a routing bug, not a runtime condition.
    """

    role_map = {"human": "user", "system": "system", "ai": "assistant", "assistant": "assistant"}
    messages: list[dict[str, Any]] = []
    for role, content in prompt:
        if not isinstance(content, str):
            raise MistralCallError(
                f"multimodal content cannot be sent to {role!r}: this model is text-only. "
                "HybridContentGenerator routes image-carrying prompts to Gemini; reaching "
                "here means that routing was bypassed."
            )
        messages.append({"role": role_map.get(role, "user"), "content": content})
    return messages


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after") or response.headers.get("ratelimit-reset")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"_raw_text": response.text[:20000]}


def _snip(response: httpx.Response) -> str:
    return response.text[:300].replace("\n", " ")
