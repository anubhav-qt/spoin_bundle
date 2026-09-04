"""Measures how Mistral's API behaves under our actual load shape, before we
commit to it.

Read `docs/mistral-saga/README.md` for what this is for and
`docs/gemini-saga/05-what-we-learned.md` for why it is shaped the way it is. The
short version: Gemini's binding constraint turned out to be an **undocumented,
IP-keyed concurrency limit** that no amount of quota accounting could see, and it
took four weeks to find through pipeline runs and one afternoon to find with a
controlled sweep. This is that sweep, pointed at Mistral, run *first* this time.

Four design decisions carried over from that experience, each of which cost
something to learn:

1. **Round-trip time is measured alone**, never folded together with time spent
   waiting for a slot. Conflating them made a wave-gate run unreadable: every
   latency climbed to 80-140s and looked like provider slowness when it was our
   own queue.
2. **A failure that never got a verdict and a failure that got a bad one are
   different counts** (CLAUDE.md). A 429, a 503, a timeout and a
   schema-invalid response are four facts, not one "failure rate".
3. **Arms run long enough to degrade.** Gemini's rolling semaphore held clean for
   five minutes and then shed hard; an arm shorter than that would have called it
   a success. `--seconds` defaults accordingly, and `time_to_first_429` is
   reported because *when* it breaks is the finding, not just whether.
4. **Prompts are pipeline-sized.** A 3-round isolation test on Gemini found tiny
   prompts produced 0% bare 429s where heavy ones produced 10% under identical
   pacing. Probing with small prompts measures a limiter we do not run into.

Usage (inside the api container, which already has httpx)::

    docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe models
    docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe schema
    docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe concurrency --max 8
    docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe keycount
    docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe soak --inflight 3

Keys come from ``SPOIN_MISTRAL_API_KEYS`` (comma-separated). Nothing here reads
the database or touches `spoin_db_2`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

#: Mistral's OpenAI-shaped chat endpoint (docs.mistral.ai). Called directly rather
#: than through LangChain on purpose: a client wrapper adds its own retries and
#: timing, and this probe exists to measure the transport, not the wrapper.
BASE_URL = "https://api.mistral.ai/v1"

#: `(tokens per minute, requests per second)` for models CONFIRMED usable by a
#: real call on 2026-09-04 (docs/mistral-saga/03-findings.md), not read off the
#: console page.
#:
#: The console's Organization Limits table is NOT a reliable source for this: it
#: lists rate limits for models this account gets 403'd on ("tier-gated") and does
#: not distinguish a real budget from a permanent `x-ratelimit-limit-req-minute: 0`
#: allocation, which looks identical to a live throttle until you wait past it and
#: it never clears. `mistral-large-2512`, every `mistral-small`/`mistral-medium`/
#: `magistral-*` variant, and `mistral-vibe-cli-*` all read as real limits on that
#: page and are unusable on this account. **Only trust a model here after a direct
#: call returns 200 with real `x-ratelimit-limit-*` headers** -- see
#: `docs/mistral-saga/03-findings.md`'s verified table before adding a model.
#:
#: On the account tested: only the Ministral family and Codestral carry real
#: budget. There is no reasoning-capable model on this tier, which is why
#: docs/mistral-saga/02-validation-plan.md's experiment 3b judges Mistral-drafted
#: content with the existing Gemini gate rather than a Mistral one -- it is the
#: only configuration this tier supports, not a methodology preference.
MODEL_LIMITS: dict[str, tuple[int, float]] = {
    "ministral-3b-2512": (1_300_000, 12.50),
    "ministral-8b-2512": (625_000, 3.13),
    "ministral-14b-2512": (937_500, 0.50),
    "codestral-2508": (625_000, 2.08),
}


def calls_per_minute(model: str, prompt_tokens: int = 12_000) -> float:
    """Sustainable calls/min for `model`, whichever of TPM or RPS binds first.

    The pipeline needs ~34 calls/min for 600 cards/hr (docs/gemini-saga/
    06-provider-alternatives.md). Comparing against THIS, not against a raw TPM,
    is what makes a rung choice defensible -- `ministral-14b` has 1.5x
    `ministral-8b`'s token budget but a sixth of its request rate, so it sustains
    30 calls/min against 8b's 52.
    """

    tpm, rps = MODEL_LIMITS[model]
    return min(tpm / max(1, prompt_tokens), rps * 60.0)

#: Roughly 4 characters per token. Only used to *size* a synthetic prompt into the
#: right ballpark -- nothing here depends on it being exact.
CHARS_PER_TOKEN = 4

#: The pipeline's real per-call prompt weight, measured from run logs
#: (`chars=` in the `lbprobe call` lines): ~6k-13k characters plus the schema.
#: Probing below this measures a limiter we never actually meet.
DEFAULT_PROMPT_TOKENS = 12_000

#: Flat pause between sweep arms. The Gemini work established that sustained load
#: accrues a transient penalty on the source IP, so an arm run immediately after a
#: failing one measures the previous arm as much as its own.
ARM_COOLDOWN_S = 60.0

#: Long enough to catch degradation-after-5-minutes, which is how Gemini's
#: concurrency cap actually failed. A shorter arm would have scored it a pass.
DEFAULT_ARM_SECONDS = 360.0

#: Per-request ceiling. Generous: a slow response is data, a hung one is not.
REQUEST_TIMEOUT_S = 180.0


class ProbeError(RuntimeError):
    """Configuration or setup problem -- not a measurement result."""


def load_keys() -> list[str]:
    raw = os.environ.get("SPOIN_MISTRAL_API_KEYS", "").strip()
    if not raw:
        raise ProbeError(
            "SPOIN_MISTRAL_API_KEYS is empty. Set it to a comma-separated list of "
            "Mistral API keys (3-5 is enough for the concurrency sweep)."
        )
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise ProbeError("SPOIN_MISTRAL_API_KEYS contained no usable keys.")
    return keys


# ------------------------------------------------------------------ outcomes --


@dataclass(frozen=True)
class Outcome:
    """One request's result.

    `kind` deliberately separates the ways a call can fail. Folding a throttle, a
    provider outage, a timeout and a malformed response into one number is the
    mistake CLAUDE.md calls out by name -- it makes a quota-exhausted run read as
    a content-quality catastrophe, and here it would make an outage read as a
    concurrency limit.
    """

    kind: str  # ok | http_429 | http_503 | http_4xx | http_5xx | timeout | transport | bad_schema
    status: int | None
    latency_s: float
    retry_after_s: float | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


@dataclass
class ArmResult:
    label: str
    outcomes: list[Outcome] = field(default_factory=list)
    wall_s: float = 0.0
    #: Seconds from arm start to the first 429. `None` means it never happened --
    #: which is the result that matters most.
    time_to_first_429: float | None = None

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def good(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def failure_rate(self) -> float:
        return 0.0 if not self.total else 100.0 * (self.total - self.good) / self.total

    @property
    def good_per_s(self) -> float:
        return 0.0 if self.wall_s <= 0 else self.good / self.wall_s

    def kind_counts(self) -> dict[str, int]:
        return dict(Counter(o.kind for o in self.outcomes))

    def latency_summary(self) -> str:
        oks = sorted(o.latency_s for o in self.outcomes if o.ok)
        if not oks:
            return "n/a"
        median = statistics.median(oks)
        p95 = oks[min(len(oks) - 1, int(len(oks) * 0.95))]
        return f"min={oks[0]:.1f} med={median:.1f} p95={p95:.1f} max={oks[-1]:.1f}"

    def render(self) -> str:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(self.kind_counts().items()))
        ttf = "never" if self.time_to_first_429 is None else f"{self.time_to_first_429:.0f}s"
        return (
            f"{self.label:<22} n={self.total:<5} fail={self.failure_rate:5.1f}%  "
            f"good/s={self.good_per_s:4.2f}  first429={ttf:<7} "
            f"lat[{self.latency_summary()}]  {counts}"
        )


# -------------------------------------------------------------------- prompt --


#: Mirrors the shape of a real card-drafting batch: a schema the model must fill,
#: and enough context to reach pipeline weight. The content is deliberately inert
#: -- this measures transport behaviour, not generation quality.
CARD_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "body": {"type": "string"},
                    "difficulty": {
                        "type": "string",
                        "enum": ["beginner", "intermediate", "advanced"],
                    },
                },
                "required": ["title", "summary", "body", "difficulty"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}

_FILLER_TOPICS = (
    "consensus protocols", "write-ahead logging", "vector clocks", "quorum reads",
    "leader election", "hash partitioning", "backpressure", "idempotency keys",
    "circuit breakers", "read repair", "gossip membership", "log compaction",
)


def build_prompt(target_tokens: int, cards: int = 6) -> str:
    """A prompt of roughly `target_tokens`, shaped like a real drafting call."""

    head = (
        f"You are drafting {cards} short technical flashcards. Return JSON matching "
        f"the provided schema exactly. Each body must be 2-4 sentences of accurate "
        f"technical prose. Reference material follows.\n\n"
    )
    target_chars = target_tokens * CHARS_PER_TOKEN
    chunks: list[str] = []
    i = 0
    while sum(len(c) for c in chunks) < target_chars - len(head):
        topic = _FILLER_TOPICS[i % len(_FILLER_TOPICS)]
        chunks.append(
            f"[ref {i:04d}] On {topic}: the mechanism trades latency for durability "
            f"under partition, and its failure mode is silent divergence rather than "
            f"an error. Operators typically observe it first as tail-latency drift. "
        )
        i += 1
    return head + "".join(chunks)


# ----------------------------------------------------------------- transport --


async def call_once(
    client: httpx.AsyncClient,
    *,
    key: str,
    model: str,
    prompt: str,
    structured: bool,
) -> Outcome:
    """One chat completion. Returns an `Outcome`, never raises for a bad response.

    `latency_s` is the HTTP round trip and nothing else -- the caller does its own
    admission control outside this function, deliberately, so queue time can never
    leak into the measurement.
    """

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.3,
    }
    if structured:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "card_batch", "schema": CARD_BATCH_SCHEMA, "strict": True},
        }

    started = time.monotonic()
    try:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    except httpx.TimeoutException:
        return Outcome("timeout", None, time.monotonic() - started)
    except httpx.HTTPError as exc:
        return Outcome("transport", None, time.monotonic() - started, detail=type(exc).__name__)

    elapsed = time.monotonic() - started
    if resp.status_code in (429, 503):
        kind = "http_429" if resp.status_code == 429 else "http_503"
        return Outcome(
            kind, resp.status_code, elapsed, retry_after_s=_retry_after(resp), detail=_snip(resp)
        )
    if resp.status_code >= 500:
        return Outcome("http_5xx", resp.status_code, elapsed, detail=_snip(resp))
    if resp.status_code >= 400:
        return Outcome("http_4xx", resp.status_code, elapsed, detail=_snip(resp))

    if structured:
        # A 200 carrying unparseable JSON is a DIFFERENT failure from a throttle:
        # it says the model cannot hold our schema, which no amount of pacing fixes.
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed.get("cards"), list) or not parsed["cards"]:
                return Outcome("bad_schema", 200, elapsed, detail="no cards array")
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            return Outcome("bad_schema", 200, elapsed, detail=f"{type(exc).__name__}")

    return Outcome("ok", 200, elapsed)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after") or resp.headers.get("ratelimit-reset")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _snip(resp: httpx.Response) -> str:
    return resp.text[:200].replace("\n", " ")


# --------------------------------------------------------------------- arms ---


async def run_arm(
    *,
    label: str,
    keys: Sequence[str],
    model: str,
    inflight: int,
    seconds: float,
    prompt: str,
    structured: bool,
) -> ArmResult:
    """Hold exactly `inflight` requests open for `seconds`, rotating over `keys`.

    Exactly `inflight` open at all times is the point: each worker calls, awaits
    the *full* response, then calls again. That is what makes the concurrency
    number a controlled variable rather than a consequence of latency, which is
    the distinction the entire Gemini saga turned on.
    """

    result = ArmResult(label=label)
    deadline = time.monotonic() + seconds
    started = time.monotonic()
    counter = 0
    lock = asyncio.Lock()

    limits = httpx.Limits(max_connections=inflight + 4, max_keepalive_connections=inflight + 4)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, limits=limits) as client:

        async def worker() -> None:
            nonlocal counter
            while time.monotonic() < deadline:
                async with lock:
                    key = keys[counter % len(keys)]
                    counter += 1
                outcome = await call_once(
                    client, key=key, model=model, prompt=prompt, structured=structured
                )
                async with lock:
                    result.outcomes.append(outcome)
                    if outcome.kind == "http_429" and result.time_to_first_429 is None:
                        result.time_to_first_429 = time.monotonic() - started

        await asyncio.gather(*(worker() for _ in range(inflight)))

    result.wall_s = time.monotonic() - started
    return result


async def cooldown(seconds: float = ARM_COOLDOWN_S) -> None:
    print(f"  ... cooling down {seconds:.0f}s (the IP penalty from the last arm decays)")
    await asyncio.sleep(seconds)


# ------------------------------------------------------------------ commands --


async def cmd_models(keys: list[str], args: argparse.Namespace) -> None:
    """Ask the API what it will actually serve this key. Cheaper and more current
    than trusting a docs page or a blog table."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{BASE_URL}/models", headers={"Authorization": f"Bearer {keys[0]}"}
        )
    if resp.status_code != 200:
        print(f"GET /models -> {resp.status_code}: {_snip(resp)}")
        return
    data = resp.json().get("data", [])
    print(f"{len(data)} model(s) visible to this key:\n")
    for m in sorted(data, key=lambda d: str(d.get("id"))):
        caps = m.get("capabilities", {}) or {}
        flags = ",".join(k for k, v in caps.items() if v) or "-"
        ctx = m.get("max_context_length", "?")
        print(f"  {m.get('id')!s:<38} ctx={ctx:<8} caps={flags}")


async def cmd_schema(keys: list[str], args: argparse.Namespace) -> None:
    """Does a pipeline-sized structured-output call actually work? Answer this
    before measuring throughput -- capacity for calls that return unusable content
    is worth nothing."""

    prompt = build_prompt(args.prompt_tokens)
    print(f"model={args.model} prompt~{args.prompt_tokens} tokens ({len(prompt)} chars)")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        for i in range(args.n):
            outcome = await call_once(
                client, key=keys[i % len(keys)], model=args.model, prompt=prompt, structured=True
            )
            note = f" -- {outcome.detail}" if outcome.detail else ""
            print(f"  call {i + 1}: {outcome.kind} in {outcome.latency_s:.1f}s{note}")


async def cmd_concurrency(keys: list[str], args: argparse.Namespace) -> None:
    """THE question. Sweep how many requests are open at once and find the wall.

    On Gemini this produced a hard boundary -- 1.2% failure at N=3, 53.6% at N=4 --
    which is the single fact the whole load balancer now exists to respect. If
    Mistral has no such wall, that is the finding that makes it viable.
    """

    prompt = build_prompt(args.prompt_tokens)
    print(
        f"concurrency sweep: model={args.model} keys={len(keys)} "
        f"prompt~{args.prompt_tokens}tok arm={args.seconds:.0f}s structured={not args.plain}\n"
    )
    results: list[ArmResult] = []
    for n in range(args.min, args.max + 1):
        arm = await run_arm(
            label=f"inflight={n}",
            keys=keys,
            model=args.model,
            inflight=n,
            seconds=args.seconds,
            prompt=prompt,
            structured=not args.plain,
        )
        results.append(arm)
        print("  " + arm.render())
        if n != args.max:
            await cooldown(args.cooldown)
    print("\n=== concurrency sweep ===")
    for arm in results:
        print("  " + arm.render())


async def cmd_keycount(keys: list[str], args: argparse.Namespace) -> None:
    """Does spreading the same load over more keys help, hurt, or do nothing?

    On Gemini the answer was "hurt, while the IP was penalised, and nothing
    otherwise" -- which is what proved the limit was IP-keyed rather than per-key,
    and retroactively invalidated a 109-key pool.
    """

    prompt = build_prompt(args.prompt_tokens)
    counts = [c for c in args.counts if c <= len(keys)]
    if not counts:
        raise ProbeError(f"No key counts <= {len(keys)} available keys. Got {args.counts}.")
    print(f"keycount sweep at inflight={args.inflight}: {counts}\n")
    results: list[ArmResult] = []
    for c in counts:
        arm = await run_arm(
            label=f"keys={c}",
            keys=keys[:c],
            model=args.model,
            inflight=args.inflight,
            seconds=args.seconds,
            prompt=prompt,
            structured=not args.plain,
        )
        results.append(arm)
        print("  " + arm.render())
        if c != counts[-1]:
            await cooldown(args.cooldown)
    print("\n=== keycount sweep ===")
    for arm in results:
        print("  " + arm.render())


async def cmd_soak(keys: list[str], args: argparse.Namespace) -> None:
    """Hold one setting for a long time and watch for degradation.

    Gemini's rolling semaphore ran perfectly clean for five minutes and then shed
    hard; batch-and-pause lasted 8.5. An arm shorter than that scores both a pass.
    This reports per-minute buckets so the *shape* is visible, not just a mean.
    """

    prompt = build_prompt(args.prompt_tokens)
    print(f"soak: inflight={args.inflight} keys={len(keys)} for {args.seconds:.0f}s\n")
    arm = await run_arm(
        label=f"soak i={args.inflight}",
        keys=keys,
        model=args.model,
        inflight=args.inflight,
        seconds=args.seconds,
        prompt=prompt,
        structured=not args.plain,
    )
    print("\n=== soak ===")
    print("  " + arm.render())
    if arm.time_to_first_429 is None:
        print("  no 429 for the whole run -- the finding we are hoping for")
    else:
        print(f"  first 429 at {arm.time_to_first_429:.0f}s -- degradation, not a clean ceiling")


COMMANDS = {
    "models": cmd_models,
    "schema": cmd_schema,
    "concurrency": cmd_concurrency,
    "keycount": cmd_keycount,
    "soak": cmd_soak,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spoin.probes.mistral_probe", description=__doc__)
    p.add_argument("command", choices=sorted(COMMANDS))
    # NOT mistral-small/medium: newest, most capable-sounding, and 20k TPM --
    # 1.6 of our calls a minute. `ministral-8b` sustains 52. See MODEL_LIMITS.
    p.add_argument("--model", default="ministral-8b-2512")
    p.add_argument("--prompt-tokens", type=int, default=DEFAULT_PROMPT_TOKENS)
    p.add_argument("--seconds", type=float, default=DEFAULT_ARM_SECONDS)
    p.add_argument("--cooldown", type=float, default=ARM_COOLDOWN_S)
    p.add_argument("--plain", action="store_true", help="skip structured output")
    p.add_argument("--min", type=int, default=1, help="concurrency: lowest N")
    p.add_argument("--max", type=int, default=6, help="concurrency: highest N")
    p.add_argument("--inflight", type=int, default=3, help="keycount/soak: N to hold")
    p.add_argument("--counts", type=int, nargs="+", default=[1, 3, 5])
    p.add_argument("--n", type=int, default=3, help="schema: how many calls")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        keys = load_keys()
    except ProbeError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(f"# {args.command} -- {len(keys)} key(s) loaded\n")
    asyncio.run(COMMANDS[args.command](keys, args))


if __name__ == "__main__":
    main()
