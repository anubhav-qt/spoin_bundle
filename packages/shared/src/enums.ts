/**
 * Domain enums, stored as native Postgres enums: adding a value is a migration, which
 * is the point. The set of card states is not something a stray string literal should
 * be able to change.
 */

export const DIFFICULTIES = ["beginner", "intermediate", "advanced"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export function difficultyRank(d: Difficulty): number {
  return DIFFICULTIES.indexOf(d);
}

export function nextTier(d: Difficulty): Difficulty | null {
  return DIFFICULTIES[difficultyRank(d) + 1] ?? null;
}

/**
 * A card is `draft` until the gate passes it and never reaches the corpus otherwise.
 * `retired` was live, then pulled by an operator (ADR-0076): distinct from `rejected`
 * (the gate threw out a draft) and `superseded` (a newer version replaced it).
 */
export const CARD_STATUSES = ["draft", "active", "rejected", "superseded", "retired"] as const;
export type CardStatus = (typeof CARD_STATUSES)[number];

/** An enum, not free text, so per-reason counts are a GROUP BY (ADR-0076). */
export const CARD_REPORT_REASONS = ["art", "diagram", "code_block", "formatting", "other"] as const;
export type CardReportReason = (typeof CARD_REPORT_REASONS)[number];

/** FIX repairs structure from the rendered image; REMAKE regenerates from a required brief (ADR-0076). */
export const REPAIR_MODES = ["fix", "remake"] as const;
export type RepairMode = (typeof REPAIR_MODES)[number];

export const REPAIR_STATUSES = ["pending", "running", "done", "failed"] as const;
export type RepairStatus = (typeof REPAIR_STATUSES)[number];

export const CARD_SOURCES = ["generated", "authored"] as const;
export type CardSource = (typeof CARD_SOURCES)[number];

/** Where in the gate a draft was thrown out, kept on the row so rates per stage are a GROUP BY (ADR-0030). */
export const REJECTION_STAGES = ["structural", "near_duplicate", "verification"] as const;
export type RejectionStage = (typeof REJECTION_STAGES)[number];

/**
 * Three states, not a boolean (ADR-0010). DEFERRED is what makes scrolling past cost
 * nothing: the card comes back after the difficulty cycle completes.
 */
export const SEEN_STATES = ["unseen", "deferred", "seen"] as const;
export type SeenState = (typeof SEEN_STATES)[number];

/**
 * `explicit_complete` and `dwell_complete` are two events, not one (ADR-0011):
 * equivalent for the progression gate, weighted very differently for ranking. Merging
 * them would discard the distinction permanently.
 */
export const ENGAGEMENT_KINDS = [
  "impression",
  "expand",
  "collapse",
  "dwell",
  "skip",
  "like",
  "unlike",
  "bookmark",
  "unbookmark",
  "note",
  "share",
  "ask_ai",
  "explicit_complete",
  "dwell_complete",
] as const;
export type EngagementKind = (typeof ENGAGEMENT_KINDS)[number];

/** Both mark a card SEEN; a set so nobody is tempted to merge the underlying events. */
export const COMPLETION_KINDS: ReadonlySet<EngagementKind> = new Set(["explicit_complete", "dwell_complete"]);

export const QUESTION_KINDS = ["mcq", "free_text"] as const;
export type QuestionKind = (typeof QUESTION_KINDS)[number];

export const QUESTION_STATUSES = ["draft", "active", "rejected"] as const;
export type QuestionStatus = (typeof QUESTION_STATUSES)[number];

/** One mechanism, three uses (ADR-0009). */
export const QUIZ_KINDS = ["placement", "promotion", "mastery"] as const;
export type QuizKind = (typeof QUIZ_KINDS)[number];

/**
 * A survey tours a field (ADR-0007), a topic teaches one subject in three tiers, a
 * one-shot teaches something small in one pass. Only `topic` has tiers: the other two
 * serve their cards easy to advanced and end in one mastery quiz (ADR-0106). The
 * corpus's `document_scope` mirrors these values; frog does not import this package.
 */
export const TOPIC_SCOPES = ["survey", "topic", "one_shot"] as const;
export type TopicScope = (typeof TOPIC_SCOPES)[number];

export const isTierless = (scope: TopicScope): boolean => scope !== "topic";

export const TOPIC_EDGE_KINDS = ["deep_dive"] as const;
export type TopicEdgeKind = (typeof TOPIC_EDGE_KINDS)[number];

export const CARD_TYPES = ["prose", "image", "code", "diagram", "comparison", "ascii"] as const;
export type CardType = (typeof CARD_TYPES)[number];

/**
 * Stored explicitly rather than inferred from `visual_id`'s string shape: rendering
 * must not depend on an implicit format rule (task 0040 Phase 3).
 */
export const VISUAL_KINDS = ["ascii", "image"] as const;
export type VisualKind = (typeof VISUAL_KINDS)[number];

/**
 * Why a model call failed, breader's kinds (task 0045), which decide what the balancer does next:
 * `rate` 429; `busy` 5xx or "overloaded"; `slow` 504, a timeout, a dropped stream; `empty` an
 * answer with no text and no tool call; `cut` the answer hit max_tokens; `bad` another 4xx, the
 * request itself is wrong; `gone` 401, 403 or 404, the model isn't open to the key.
 */
export const MODEL_CALL_FAILURES = ["rate", "busy", "slow", "empty", "cut", "bad", "gone"] as const;
export type ModelCallFailure = (typeof MODEL_CALL_FAILURES)[number];
