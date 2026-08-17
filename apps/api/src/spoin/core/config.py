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

from spoin.domain.enums import Difficulty

GeneratorBackend = Literal["fake", "gemini", "local"]
EmbedderBackend = Literal["hash", "fastembed"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPOIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "ci", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://spoin:spoin@localhost:5432/spoin"
    #: Comma-separated. Deliberately a plain string rather than a list: a list-typed
    #: setting makes pydantic-settings JSON-parse the env var, so a perfectly
    #: ordinary `SPOIN_CORS_ORIGINS=http://localhost:3000` fails to start the app.
    #: Read it through `cors_origin_list`.
    cors_origins: str = "http://localhost:3000"

    # -- auth ---------------------------------------------------------------
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION-KEY-MUST-BE-32-BYTES"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    google_client_id: str = ""

    # -- generation (ADR-0002, ADR-0008, ADR-0028) -----------------------------
    # `fake` everywhere except production: tests and local dev must never call a
    # real model, never burn quota, and run in milliseconds.
    generator: GeneratorBackend = "fake"
    #: Comma-separated. Each entry is assumed to be its OWN Google Cloud project
    #: (a key does NOT get its own quota pool otherwise — Gemini rate limits are
    #: per-project, not per-key; see ADR-0028). The quota governor
    #: (generation/quota.py) treats each entry as one row in its key x model grid.
    gemini_api_keys: str = ""
    #: "model:rpd:rpm,model:rpd:rpm,..." — an ORDERED fallback ladder, strongest
    #: model first. Used for curriculum, topic matching, difficulty/factual
    #: judging, and quiz grading — the calls with a real consequence if the
    #: model is weak (ADR-0008's "trusted for taste, never for constraints"
    #: rule). A model is only skipped once every configured key is exhausted
    #: for it (ADR-0028). Live-verified 2026-08-17 against 9 real keys —
    #: `gemini-2.5-flash` is retired for new accounts (404) and dropped;
    #: `gemini-3.0-flash` never existed as a stable name (only the `-preview`
    #: suffixed one does).
    gemini_thinking_ladder: str = (
        "gemini-3.7-flash:20:5,gemini-3.6-flash:20:5,"
        "gemini-3.5-flash:20:5,gemini-3-flash-preview:20:5"
    )
    #: Same shape, for `generate_cards` AND `generate_questions` (ADR-0029) —
    #: both are high-VOLUME, taste-shaped calls (one per card/question), so
    #: they share the cheap high-volume "lite" ladder instead of competing
    #: with the thinking pool's much smaller daily budget. Live-verified
    #: 2026-08-17 — `gemini-2.5-flash-lite` is retired for new accounts (404,
    #: same as `gemini-2.5-flash` above) and dropped.
    gemini_generator_ladder: str = "gemini-3.5-flash-lite:500:15,gemini-3.1-flash-lite:500:15"
    local_generator_base_url: str = "http://localhost:11434/v1"
    local_generator_model: str = "qwen3:14b"

    #: Caps requests in flight at once across an ENTIRE generation run, regardless
    #: of how many subtopics (or topics) fan out concurrently — without this, a
    #: topic with 20 subtopics dispatches 20 simultaneous calls, blowing through
    #: every ladder rung's RPM and turning key/model exhaustion into a burst of
    #: simultaneous failures instead of a predictable, one-at-a-time rotation.
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

    # -- embeddings (hard rule 5) ----------------------------------------------
    embedder: EmbedderBackend = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    #: How many existing-topic candidates the embedding pre-filter offers the
    #: batched matching call per incoming topic (ADR-0025). Not a threshold — the
    #: LLM decides; this just bounds recall-filter/prompt size.
    topic_match_candidates: int = 5

    # Card near-duplicate threshold. Different vectors, different numbers — the
    # topic threshold does not transfer (content-model.md, open questions).
    # PROVISIONAL: never calibrated against real embeddings (only the
    # deterministic HashEmbedder is exercised in tests, and content-model.md
    # already calls that "not semantically meaningful"). Shipped deliberately
    # more conservative than the original 0.93 guess until real fastembed
    # data justifies a specific number (ADR-0030).
    card_duplicate_threshold: float = 0.9
    #: How many of a subtopic's most-recent near-duplicate `rejected_card` rows
    #: get fed back into the NEXT `generate_cards` call for that subtopic as
    #: "don't write anything like this again" context (ADR-0030 addendum).
    #: Bounded for the same reason `existing_titles` is bounded -- prevention
    #: context must stay small enough that the attention argument holds.
    max_duplicate_feedback_bodies: int = 10
    #: Same shape as `max_duplicate_feedback_bodies`, for a subtopic's most
    #: recent PASS-2 VERIFICATION `rejected_card` rows instead of near-dup
    #: ones -- these carry a real reason the judge model gave (not just a
    #: similarity score), fed back into the next `generate_cards` call so the
    #: writer fixes the actual problem instead of rewording into it again.
    max_verification_feedback_bodies: int = 10
    #: How many of a subtopic-tier's already-active question stems get shown to
    #: `generate_questions` as "don't repeat any of these" context -- unlike the
    #: two settings above (rejected content), this is ACCEPTED content, so the
    #: cap can be looser: stems are short one-liners, not full card bodies, and
    #: a subtopic-tier's whole question set (target_cards-bounded, ADR-0026) is
    #: already a naturally small number.
    max_existing_question_stems: int = 30

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

    # -- quiz (ADR-0009, entry tier amended by ADR-0027) -------------------------
    quiz_mcq_count: int = 9
    quiz_free_text_count: int = 1
    quiz_pass_threshold: float = 0.80
    #: 70/30 (ADR-0009) split across quiz_mcq_count/quiz_free_text_count items.
    quiz_mcq_weight: float = 0.70
    quiz_free_text_weight: float = 0.30
    #: content-model.md's rubric: "0 none / 1 surface / 2 solid / 3 deep" — this
    #: level or above counts the free-text answer as correct.
    quiz_free_text_pass_level: int = 2
    #: Per-USER daily cap on LLM-graded free-text submissions. Unlike every other
    #: quota in this system, this one scales with user behavior, not corpus size
    #: (overview.md, Quiz Grading's cost profile) — a separate axis from the
    #: generation quota governor's per-(key, model) ladder, so it is its own
    #: setting rather than borrowing from `gemini_thinking_ladder`.
    quiz_free_text_grades_per_user_per_day: int = 20
    #: Server-side length cap (ADR-0009): nominally unlimited, capped generously
    #: so a pasted answer cannot blow the grading call's context window.
    quiz_free_text_answer_max_chars: int = 12_000

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
