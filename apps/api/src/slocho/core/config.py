"""Settings.

Everything that changes between free tier and paid tier lives here, because
ADR-0003 §2 commits us to that being a config change and never a code change.
Same for the ranking weights (ADR-0010) and the difficulty mix
(content-model.md) — both will be tuned against real engagement data, and
tuning must not require a deploy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from slocho.domain.enums import Difficulty

GeneratorBackend = Literal["fake", "gemini", "local"]
EmbedderBackend = Literal["hash", "fastembed"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SLOCHO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://slocho:slocho@localhost:5432/slocho"
    #: Comma-separated. Deliberately a plain string rather than a list: a list-typed
    #: setting makes pydantic-settings JSON-parse the env var, so a perfectly
    #: ordinary `SLOCHO_CORS_ORIGINS=http://localhost:3000` fails to start the app.
    #: Read it through `cors_origin_list`.
    cors_origins: str = "http://localhost:3000"

    # -- generation (ADR-0002, ADR-0008) --------------------------------------
    # `fake` everywhere except production: tests and local dev must never call a
    # real model, never burn quota, and run in milliseconds.
    generator: GeneratorBackend = "fake"
    gemini_model: str = "gemini-2.5-flash"
    #: Comma-separated, same plain-string reasoning as `cors_origins` (a list-typed
    #: setting would make pydantic-settings JSON-parse the env var). One free-tier
    #: Gemini key per project; the quota governor (generation/quota.py) rotates
    #: through these when the active one hits `quota_daily_requests` for the day.
    gemini_api_keys: str = ""
    local_generator_base_url: str = "http://localhost:11434/v1"
    local_generator_model: str = "qwen3:14b"

    #: Caps requests in flight at once across an ENTIRE generation run, regardless
    #: of how many subtopics (or topics) fan out concurrently — without this, a
    #: topic with 20 subtopics dispatches 20 simultaneous calls, blowing through
    #: `quota_rpm` and turning key exhaustion into a burst of simultaneous
    #: failures instead of a predictable, one-at-a-time rotation.
    max_concurrent_generation_calls: int = 5

    # Batch sizes (ADR-0005). The free tier meters requests, not tokens, so these
    # are the difference between the corpus filling and not filling.
    generation_batch_size: int = 10
    judge_batch_size: int = 20
    question_batch_size: int = 25

    # Coverage threshold as a fraction of target_cards (content-model.md, open
    # questions: "somewhere around 50-60% is the intuition, check against real
    # rejection rates"). Config so it can be retuned without a deploy once real
    # quality-gate rejection rates exist.
    min_cards_fraction: float = 0.6

    # -- quota governor (ADR-0003 §6) ------------------------------------------
    quota_daily_requests: int = 1500
    quota_rpm: int = 15

    # -- embeddings (hard rule 5) ----------------------------------------------
    embedder: EmbedderBackend = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Topic canonicalization bands (ADR-0004).
    #
    # PLACEHOLDERS. These are guesses, and ADR-0004 is explicit that a guessed
    # threshold "produces a system that looks tuned but is a superstition".
    # docs/tasks/0001 exists to replace them with measured values. They are
    # specific to `embedding_model` and must be recalibrated if it changes.
    topic_merge_high: float = 0.92
    topic_merge_low: float = 0.80

    # Card near-duplicate threshold. Different vectors, different numbers — the
    # topic threshold does not transfer (content-model.md, open questions).
    card_duplicate_threshold: float = 0.93

    # -- feed (ADR-0010) --------------------------------------------------------
    rank_w_quality: float = 1.0
    rank_w_affinity: float = 0.8
    rank_w_coverage: float = 0.6
    rank_w_freshness: float = 0.3
    rank_epsilon: float = 0.10

    slate_size: int = 25
    plan_size: int = 50
    slate_ttl_seconds: int = 1800
    page_size: int = 10

    #: Consecutive slots one topic wins in the interleave plan.
    #:
    #: ADR-0010 specifies slots "spread evenly rather than clumped", which is
    #: `1` — and at 1 an unfiltered feed alternates topics every single card, so
    #: the client's per-topic headings appear before every card and stop being
    #: headings at all. Above 1 each topic's *share* is unchanged; only the
    #: granularity of alternation is. Config rather than code, so the two
    #: concerns can be balanced against real engagement data.
    feed_topic_run: int = 3

    # Degraded-mode hysteresis (ADR-0006 §3). Two thresholds, deliberately: a
    # single one flaps as the pool sits on the line.
    pool_low: int = 5
    pool_high: int = 15

    # -- engagement (ADR-0011) --------------------------------------------------
    dwell_complete_ms: int = 8000
    dwell_max_ms: int = 300_000  # a tab open overnight is not a nine-hour read

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def gemini_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.gemini_api_keys.split(",") if key.strip()]

    @property
    def pool_thresholds_are_sane(self) -> bool:
        return self.pool_low < self.pool_high

    def rank_weights(self) -> dict[str, float]:
        return {
            "quality": self.rank_w_quality,
            "affinity": self.rank_w_affinity,
            "coverage": self.rank_w_coverage,
            "freshness": self.rank_w_freshness,
        }


# The difficulty mix, per user tier (content-model.md). Config, not code: these
# will be tuned against engagement data.
#
# The upward slice is load-bearing beyond variety — it is the promotion signal.
# A beginner who consistently engages with their 20% intermediate cards is telling
# us they are ready to move up, so do not "simplify" it away.
DIFFICULTY_MIX: dict[Difficulty, dict[Difficulty, float]] = {
    Difficulty.BEGINNER: {
        Difficulty.BEGINNER: 0.80,
        Difficulty.INTERMEDIATE: 0.20,
    },
    Difficulty.INTERMEDIATE: {
        Difficulty.BEGINNER: 0.20,
        Difficulty.INTERMEDIATE: 0.70,
        Difficulty.ADVANCED: 0.10,
    },
    Difficulty.ADVANCED: {
        Difficulty.BEGINNER: 0.02,
        Difficulty.INTERMEDIATE: 0.08,
        Difficulty.ADVANCED: 0.90,
    },
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
