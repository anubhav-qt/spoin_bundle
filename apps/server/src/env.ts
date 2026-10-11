import { z } from "zod";

const bool = z.enum(["true", "false", "1", "0"]).transform((v) => v === "true" || v === "1");
const list = z.string().transform((v) =>
  v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);
const num = (fallback: number) => z.coerce.number().default(fallback);
const int = (fallback: number) => z.coerce.number().int().default(fallback);

/**
 * Everything that differs between environments, and every product knob.
 *
 * The knobs live here rather than as constants because tuning them against real
 * engagement must never need a deploy (ADR-0003 §2): ranking weights (ADR-0010), the
 * session taste profile (ADR-0055), quiz shape (ADR-0009). Each is an env var with the
 * shipped value as its default.
 */
const Env = z.object({
  NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"]).default("info"),
  PORT: int(8000),
  RELEASE: z.string().default("dev"),

  /** The app database. */
  DATABASE_URL: z.string().min(1),
  /**
   * `the_spoin_universe` (ADR-0088). Its own variable and **never** a fallback to
   * DATABASE_URL: a convenience fallback is how a corpus migration lands on the app's
   * database. Unset means there is no corpus to read.
   */
  UNIVERSE_DATABASE_URL: z.string().optional(),

  /** Signs Better Auth sessions. At least 32 characters; production refuses the dev default. */
  AUTH_SECRET: z.string().min(32),
  /** This server's own address, where Google sends a reader back after login. */
  PUBLIC_URL: z.string().url().optional(),
  ALLOWED_ORIGINS: list.default(["http://localhost:3000"]),
  GOOGLE_CLIENT_ID: z.string().optional(),
  GOOGLE_CLIENT_SECRET: z.string().optional(),
  /**
   * Where the client's address comes from, for rate limits. Only a header the proxy in
   * front sets itself can be trusted; `none` is the socket's own address (local dev).
   */
  CLIENT_IP_HEADER: z.enum(["none", "cf-connecting-ip", "x-forwarded-for"]).default("none"),

  /** `hash` boots with no model weights and is meaningless for similarity; `qwen3` is the real one (ADR-0097). */
  EMBEDDER: z.enum(["hash", "qwen3"]).default("hash"),
  /** Where ONNX weights are cached between restarts. */
  MODEL_CACHE_DIR: z.string().optional(),

  // -- topics ---------------------------------------------------------------
  /** Coverage threshold as a fraction of target_cards (content-model.md). */
  MIN_CARDS_FRACTION: num(0.6),
  /** Fraction of subtopics at `min_cards` before a topic shows to people who didn't request it (ADR-0053). */
  TOPIC_LIVE_COVERAGE_FRACTION: num(0.5),
  /** The quiz-unlock bar, relative so a thin subtopic cannot strand a user (ADR-0009). */
  COVERAGE_GATE: num(0.8),
  /** A constraint enforced in code, not asked of a model: a topic name, not a sentence. */
  CUSTOM_TOPIC_MAX_WORDS: int(5),
  /** Candidates the embedding pre-filter offers topic matching per incoming name (ADR-0025). */
  TOPIC_MATCH_CANDIDATES: int(5),

  // -- feed (ADR-0010) ------------------------------------------------------
  RANK_W_QUALITY: num(1.0),
  RANK_W_AFFINITY: num(0.8),
  RANK_W_COVERAGE: num(0.6),
  RANK_W_FRESHNESS: num(0.3),
  RANK_EPSILON: num(0.1),
  SLATE_SIZE: int(25),
  PLAN_SIZE: int(50),
  SLATE_TTL_SECONDS: int(1800),
  PAGE_SIZE: int(10),
  /**
   * Consecutive plan slots one topic wins. 1, so the 5% share floor is representable at
   * `PLAN_SIZE` 50 (ADR-0055). Do not raise without raising `PLAN_SIZE`.
   */
  FEED_TOPIC_RUN: int(1),
  /** Degraded-mode hysteresis: two thresholds, because one flaps as the pool sits on the line (ADR-0006). */
  POOL_LOW: int(5),
  POOL_HIGH: int(15),
  /** The difficulty-mix ramp: below start a tier is 100% itself, at end the full mix applies. */
  MIX_RAMP_START: num(0.2),
  MIX_RAMP_END: num(0.6),

  // -- session taste profile (ADR-0055) ---------------------------------------
  /** Not shared with `SLATE_TTL_SECONDS` though both are 1800: they are unrelated facts. */
  SESSION_WINDOW_SECONDS: int(1800),
  SESSION_SHARE_FLOOR: num(0.05),
  SESSION_SHARE_CEILING: num(0.5),
  SESSION_SHARE_BUCKET: num(0.05),
  SESSION_SIGNAL_K: num(10),
  SESSION_SIGNAL_BOOST: num(2),
  SESSION_W_DWELL_PER_SECOND: num(0.05),
  SESSION_W_EXPAND: num(0.5),
  SESSION_W_EXPLICIT_COMPLETE: num(4),
  SESSION_W_DWELL_COMPLETE: num(2),
  SESSION_W_LIKE: num(3),
  SESSION_W_BOOKMARK: num(3),
  SESSION_W_NOTE: num(4),
  SESSION_W_SHARE: num(4),
  SESSION_W_ASK_AI: num(3),
  /** Negative: a skip is evidence, not the absence of it. */
  SESSION_W_SKIP: num(-1.5),

  // -- engagement (ADR-0011) --------------------------------------------------
  DWELL_COMPLETE_MS: int(10_000),
  /** A tab open overnight is not a nine-hour read. */
  DWELL_MAX_MS: int(300_000),

  // -- quiz (ADR-0009, ADR-0027) ----------------------------------------------
  QUIZ_MCQ_COUNT: int(9),
  QUIZ_FREE_TEXT_COUNT: int(1),
  QUIZ_PASS_THRESHOLD: num(0.8),
  QUIZ_MCQ_WEIGHT: num(0.7),
  QUIZ_FREE_TEXT_WEIGHT: num(0.3),
  /** content-model.md's rubric, 0 none / 1 surface / 2 solid / 3 deep: this level or above is correct. */
  QUIZ_FREE_TEXT_PASS_LEVEL: int(2),
  /** Scales with user behaviour, not corpus size, so it is its own limit. */
  QUIZ_FREE_TEXT_GRADES_PER_USER_PER_DAY: int(20),
  QUIZ_FREE_TEXT_ANSWER_MAX_CHARS: int(12_000),

  // -- AskAI (ADR-0077) -------------------------------------------------------
  ASK_AI_DAILY_LIMIT: int(200),
  /** UNCALIBRATED: refuses plainly off-topic questions without a model call. Ignored under `hash`. */
  ASK_AI_TOPIC_SIMILARITY_FLOOR: num(0.18),
  ASK_AI_CONTEXT_NEIGHBOURS: int(4),

  /** Opens `/dev/*` outside production (never in it), and the OpenAPI UI in production too. */
  DEV_ROUTES: bool.default(false),
});

export type Env = z.infer<typeof Env>;

const INSECURE_DEV_SECRET = "spoin-local-development-secret-change-me";

export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  // A blank line in .env (FOO=) means "not set".
  const present = Object.fromEntries(Object.entries(source).filter(([, v]) => v !== ""));
  const parsed = Env.safeParse({ AUTH_SECRET: INSECURE_DEV_SECRET, ...present });
  if (!parsed.success) {
    const problems = parsed.error.issues.map((i) => `  ${i.path.join(".")}: ${i.message}`).join("\n");
    throw new Error(`Invalid environment:\n${problems}`);
  }
  // The dev secret is public in git; a production process carrying it could have every session forged.
  if (parsed.data.NODE_ENV === "production" && parsed.data.AUTH_SECRET === INSECURE_DEV_SECRET) {
    throw new Error("AUTH_SECRET must be set to a real secret in production");
  }
  return parsed.data;
}
