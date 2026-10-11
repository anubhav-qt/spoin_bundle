/**
 * The app database. Ported column for column from the SQLAlchemy models; the comments
 * keep only what a reader could not get from the line itself, and cite the ADR behind
 * a shape. content-model.md calls `card` the highest-leverage schema in the project:
 * change it deliberately.
 */
import { EMBEDDING_DIM } from "@spoin/frog/embeddings";
import {
  CARD_REPORT_REASONS,
  CARD_SOURCES,
  CARD_STATUSES,
  DIFFICULTIES,
  ENGAGEMENT_KINDS,
  QUESTION_KINDS,
  QUESTION_STATUSES,
  QUIZ_KINDS,
  REJECTION_STAGES,
  REPAIR_MODES,
  REPAIR_STATUSES,
  SEEN_STATES,
  TOPIC_EDGE_KINDS,
  VISUAL_KINDS,
} from "@spoin/shared/enums";
import { sql } from "drizzle-orm";
import {
  boolean,
  check,
  customType,
  doublePrecision,
  index,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  primaryKey,
  text,
  timestamp,
  unique,
  uniqueIndex,
  uuid,
  varchar,
  vector,
} from "drizzle-orm/pg-core";

const bytea = customType<{ data: Buffer; driverData: Buffer }>({ dataType: () => "bytea" });

const id = () => uuid("id").primaryKey().defaultRandom();
const tz = (name: string) => timestamp(name, { withTimezone: true });
const createdAt = () => tz("created_at").notNull().defaultNow();
const updatedAt = () =>
  tz("updated_at")
    .notNull()
    .defaultNow()
    .$onUpdate(() => new Date());
const userRef = (name = "user_id") => uuid(name).references(() => appUser.id, { onDelete: "cascade" });
const topicRef = (name = "topic_id") => uuid(name).references(() => topic.id, { onDelete: "cascade" });
const cardRef = (name = "card_id") => uuid(name).references(() => card.id, { onDelete: "cascade" });

export const difficulty = pgEnum("difficulty", DIFFICULTIES);
export const cardStatus = pgEnum("card_status", CARD_STATUSES);
export const cardReportReason = pgEnum("card_report_reason", CARD_REPORT_REASONS);
export const repairMode = pgEnum("repair_mode", REPAIR_MODES);
export const repairStatus = pgEnum("repair_status", REPAIR_STATUSES);
export const cardSource = pgEnum("card_source", CARD_SOURCES);
export const rejectionStage = pgEnum("rejection_stage", REJECTION_STAGES);
export const seenState = pgEnum("seen_state", SEEN_STATES);
export const engagementKind = pgEnum("engagement_kind", ENGAGEMENT_KINDS);
export const questionKind = pgEnum("question_kind", QUESTION_KINDS);
export const questionStatus = pgEnum("question_status", QUESTION_STATUSES);
export const quizKind = pgEnum("quiz_kind", QUIZ_KINDS);
export const topicEdgeKind = pgEnum("topic_edge_kind", TOPIC_EDGE_KINDS);
export const visualKind = pgEnum("visual_kind", VISUAL_KINDS);

// --------------------------------------------------------------- accounts --
// Better Auth's four tables (ADR-0106). The JS property names are the ones Better
// Auth expects; the column names follow this database's snake_case.

/**
 * A user. A guest is an anonymous Better Auth user (`is_anonymous`), a real row from
 * their first card so progress is keyed off one id from the start; claiming an
 * account links to that same row (ADR-0033).
 */
export const appUser = pgTable("app_user", {
  id: id(),
  /** Better Auth's `name`: the display name. */
  name: varchar("display_name", { length: 80 }).notNull(),
  email: varchar("email", { length: 320 }).notNull().unique("uq_app_user_email"),
  emailVerified: boolean("email_verified").notNull().default(false),
  image: text("image"),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
  isAnonymous: boolean("is_anonymous").notNull().default(false),
  /** Better Auth's admin plugin. "admin" opens the admin pages (closes task 0035). */
  role: varchar("role", { length: 32 }).notNull().default("user"),
  banned: boolean("banned").notNull().default(false),
  banReason: text("ban_reason"),
  banExpires: tz("ban_expires"),
  /** Gates onboarding, not signup. */
  onboardingComplete: boolean("onboarding_complete").notNull().default(false),
  age: integer("age"),
  gender: varchar("gender", { length: 32 }),
  avatarIcon: varchar("avatar_icon", { length: 32 }),
  /** Denormalized so "has a photo?" never touches the bytes, which live in `user_avatar`. */
  hasAvatarImage: boolean("has_avatar_image").notNull().default(false),
  /**
   * A target the profile's activity is read against. Deliberately NOT a feed input:
   * selection stays governed by progression and the server-side difficulty mix (ADR-0010).
   */
  dailyCardGoal: integer("daily_card_goal").notNull().default(10),
});

export const authSession = pgTable(
  "auth_session",
  {
    id: id(),
    expiresAt: tz("expires_at").notNull(),
    token: text("token").notNull().unique("uq_auth_session_token"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    ipAddress: text("ip_address"),
    userAgent: text("user_agent"),
    userId: userRef().notNull(),
    impersonatedBy: text("impersonated_by"),
  },
  (t) => [index("ix_auth_session_user_id").on(t.userId)],
);

export const authAccount = pgTable(
  "auth_account",
  {
    id: id(),
    accountId: text("account_id").notNull(),
    providerId: text("provider_id").notNull(),
    userId: userRef().notNull(),
    accessToken: text("access_token"),
    refreshToken: text("refresh_token"),
    idToken: text("id_token"),
    accessTokenExpiresAt: tz("access_token_expires_at"),
    refreshTokenExpiresAt: tz("refresh_token_expires_at"),
    scope: text("scope"),
    password: text("password"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [index("ix_auth_account_user_id").on(t.userId)],
);

export const authVerification = pgTable("auth_verification", {
  id: id(),
  identifier: text("identifier").notNull(),
  value: text("value").notNull(),
  expiresAt: tz("expires_at").notNull(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

/** The avatar's bytes, apart from `app_user` so no auth or `/auth/me` read ever carries them. */
export const userAvatar = pgTable("user_avatar", {
  userId: userRef().primaryKey(),
  data: bytea("data").notNull(),
  /** Sniffed from the bytes at upload, never taken from the request. */
  mediaType: varchar("media_type", { length: 32 }).notNull(),
  updatedAt: updatedAt(),
});

// ----------------------------------------------------------------- topics --
// ADR-0004's shared entity, personal label: `topic` owns the corpus, `topic_alias`
// maps raw strings onto it, `user_topic` is what THIS user calls it.

/** The canonical entity. Content is generated once per topic and shared. */
export const topic = pgTable(
  "topic",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    slug: varchar("slug", { length: 120 }).notNull().unique("uq_topic_slug"),
    /** The system's name. Never rendered: the UI shows `user_topic.display_name`. */
    canonicalName: varchar("canonical_name", { length: 120 }).notNull(),
    description: text("description"),
    embedding: vector("embedding", { dimensions: EMBEDDING_DIM }),
    embeddingModel: varchar("embedding_model", { length: 120 }),
    isSeeded: boolean("is_seeded").notNull().default(false),
    /** A survey gets a breadth curriculum and deep-dive edges; the completion copy differs (ADR-0007). */
    isSurvey: boolean("is_survey").notNull().default(false),
    /** When an authored curriculum was last projected onto this topic. */
    curriculumGeneratedAt: tz("curriculum_generated_at"),
    /** The corpus version that projection ran against, so "the corpus moved" is a comparison. */
    curriculumCorpusVersion: varchar("curriculum_corpus_version", { length: 64 }),
    /** Denormalised for fill priority, maintained by a batch job: never counted per request (ADR-0006). */
    subscriberCount: integer("subscriber_count").notNull().default(0),
  },
  (t) => [
    check(
      "ck_topic_embedding_names_its_model",
      sql`(${t.embedding} IS NULL) = (${t.embeddingModel} IS NULL)`,
    ),
  ],
);

/**
 * Every raw string a user has typed and where it resolved. Merges are reversible by
 * construction: fixing a bad merge is repointing an alias (ADR-0004).
 */
export const topicAlias = pgTable("topic_alias", {
  id: id(),
  createdAt: createdAt(),
  /** Post-normalization, by the same function at write and match time, or the cache silently misses. */
  normalizedText: varchar("normalized_text", { length: 200 })
    .notNull()
    .unique("uq_topic_alias_normalized_text"),
  rawText: varchar("raw_text", { length: 200 }).notNull(),
  topicId: topicRef().notNull(),
  /** Who decided the match, kept so a bad decision can be audited. */
  decidedBy: varchar("decided_by", { length: 20 }).notNull(),
  similarity: doublePrecision("similarity"),
});

/** A subscription, plus the name this user gave it. */
export const userTopic = pgTable(
  "user_topic",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    displayName: varchar("display_name", { length: 120 }).notNull(),
    isCustom: boolean("is_custom").notNull().default(false),
    /**
     * 0-359, -1 opts out of topic colour (ADR-0051), null renders the client's default.
     * Per subscription, so two users can colour the same topic differently (ADR-0075).
     */
    accentHue: integer("accent_hue"),
  },
  (t) => [unique("uq_user_topic_user_id_topic_id").on(t.userId, t.topicId)],
);

/** A flat edge for discovery, not a tree: hierarchy would rebuild unbounded nesting (ADR-0007). */
export const topicEdge = pgTable(
  "topic_edge",
  {
    id: id(),
    createdAt: createdAt(),
    fromTopicId: topicRef("from_topic_id").notNull(),
    toTopicId: topicRef("to_topic_id").notNull(),
    kind: topicEdgeKind("kind").notNull().default("deep_dive"),
  },
  (t) => [
    unique("uq_topic_edge_from_topic_id_to_topic_id_kind").on(t.fromTopicId, t.toTopicId, t.kind),
    check("ck_topic_edge_no_self_edge", sql`${t.fromTopicId} <> ${t.toTopicId}`),
  ],
);

/**
 * A curriculum slot. Generation targets one of these, never a bare topic: a model is
 * far more reliable pointed at a target than told to avoid a list (ADR-0007).
 */
export const subtopic = pgTable(
  "subtopic",
  {
    id: id(),
    createdAt: createdAt(),
    topicId: topicRef().notNull(),
    /** One id per concept, shared by its 1-3 tiers. */
    subtopicGroupId: uuid("subtopic_group_id").notNull().defaultRandom(),
    difficulty: difficulty("difficulty").notNull(),
    title: varchar("title", { length: 160 }).notNull(),
    /** Read by the generation prompt, so it is prose for a model, not a label for a human. */
    description: text("description").notNull(),
    /** The planner's ideal count: a ceiling and a priority weight. */
    targetCards: integer("target_cards").notNull(),
    /**
     * The coverage threshold. Completion is defined against this, not `target_cards`,
     * or users sit at 94% forever once the gate rejects some drafts (ADR-0007).
     */
    minCards: integer("min_cards").notNull(),
    position: integer("position").notNull().default(0),
    cardTypeQuotas: jsonb("card_type_quotas").$type<Record<string, number>>(),
    /**
     * The corpus sections this tier may be written from, as authored:
     * `<path relative to corpus/>#<exact ## heading>`. Text, not chunk ids, because
     * re-ingestion rebuilds chunks and stored ids would rot. Null means no declared scope.
     */
    groundingRefs: text("grounding_refs").array(),
  },
  (t) => [
    index("ix_subtopic_topic_id_difficulty").on(t.topicId, t.difficulty),
    index("ix_subtopic_group_id").on(t.subtopicGroupId),
    check("ck_subtopic_min_within_target", sql`${t.minCards} <= ${t.targetCards}`),
    check("ck_subtopic_target_cards_band", sql`${t.targetCards} BETWEEN 5 AND 25`),
  ],
);

// ------------------------------------------------------------------ cards --

export const card = pgTable(
  "card",
  {
    id: id(),
    createdAt: createdAt(),
    /**
     * Groups every version of a card. Regenerating makes a NEW ROW: engagement attaches
     * to a card id, so overwriting would re-attribute every like to different content.
     */
    familyId: uuid("family_id").notNull(),
    version: integer("version").notNull().default(1),
    /** System-owned: a card is `draft` until the gate passes it. */
    status: cardStatus("status").notNull().default("draft"),
    topicId: topicRef().notNull(),
    subtopicId: uuid("subtopic_id")
      .notNull()
      .references(() => subtopic.id, { onDelete: "cascade" }),
    /** Requested, then independently re-rated by the gate: only a blind rating can disagree. */
    difficulty: difficulty("difficulty").notNull(),
    judgedDifficulty: difficulty("judged_difficulty"),
    title: varchar("title", { length: 120 }).notNull(),
    /** The literal name of the concept, never playful; every non-feed consumer reads this (ADR-0022). */
    canonicalTitle: varchar("canonical_title", { length: 160 }).notNull(),
    /** A purpose-written hook, not a truncation of `body`. */
    summary: text("summary").notNull(),
    /** Markdown. */
    body: text("body").notNull(),
    source: cardSource("source").notNull().default("generated"),
    authorId: uuid("author_id").references(() => appUser.id, { onDelete: "set null" }),
    /** Derived from `body` alone, locally. */
    contentEmbedding: vector("content_embedding", { dimensions: EMBEDDING_DIM }),
    embeddingModel: varchar("embedding_model", { length: 120 }),
    /**
     * The corpus chunk ids that were in this card's prompt (ADR-0089). NULL and `[]` are
     * different facts: NULL means retrieval never ran, `[]` means it ran and found nothing.
     * No foreign key: `chunk` lives in another database (ADR-0088).
     */
    groundedChunkIds: uuid("grounded_chunk_ids").array(),
    /** model, prompt version, run, backend: what lets a bad batch be traced and retired. */
    genMeta: jsonb("gen_meta").$type<Record<string, unknown>>().notNull().default({}),
    /** Content shapes derived from `body`, never self-reported (ADR-0017). */
    archetype: text("archetype").array().notNull().default(sql`'{}'::text[]`),
    /** At most one per subtopic (ADR-0017). */
    isHero: boolean("is_hero").notNull().default(false),
    /** An ASCII scene's library id or an image's catalog id (ADR-0021, ADR-0095). */
    visualId: varchar("visual_id", { length: 64 }),
    visualKind: visualKind("visual_kind"),
    visualSlots: jsonb("visual_slots").$type<Record<string, string>>(),
  },
  (t) => [
    index("ix_card_subtopic_id_status_difficulty").on(t.subtopicId, t.status, t.difficulty),
    index("ix_card_topic_id_status_difficulty").on(t.topicId, t.status, t.difficulty),
    /** Exactly one active row per family, enforced by the database: ranking depends on it. */
    uniqueIndex("uq_card_family_id_active").on(t.familyId).where(sql`status = 'active'`),
    unique("uq_card_family_id_version").on(t.familyId, t.version),
    check("ck_card_version_positive", sql`${t.version} >= 1`),
    /** GIN: "which cards did this chunk ground?" is a containment question (ADR-0089). */
    index("ix_card_grounded_chunk_ids").using("gin", t.groundedChunkIds),
    check(
      "ck_card_embedding_names_its_model",
      sql`(${t.contentEmbedding} IS NULL) = (${t.embeddingModel} IS NULL)`,
    ),
    check(
      "ck_card_visual_kind_accompanies_visual_id",
      sql`(${t.visualId} IS NULL) = (${t.visualKind} IS NULL)`,
    ),
  ],
);

/**
 * Derived aggregate, rebuildable from the event log (ADR-0011). No COUNT(*) over
 * engagement in a user-facing request, ever.
 */
export const cardStats = pgTable("card_stats", {
  cardId: cardRef().primaryKey(),
  createdAt: createdAt(),
  impressions: integer("impressions").notNull().default(0),
  expands: integer("expands").notNull().default(0),
  likes: integer("likes").notNull().default(0),
  bookmarks: integer("bookmarks").notNull().default(0),
  explicitCompletes: integer("explicit_completes").notNull().default(0),
  dwellCompletes: integer("dwell_completes").notNull().default(0),
  skips: integer("skips").notNull().default(0),
  avgDwellMs: doublePrecision("avg_dwell_ms").notNull().default(0),
  /** A RATE, never a count: counts make old cards dominant and new ones invisible. */
  quality: doublePrecision("quality").notNull().default(0),
  recomputedAt: tz("recomputed_at"),
});

/** A draft that never became a card, kept with the reason as a labelled example (ADR-0030). */
export const rejectedCard = pgTable(
  "rejected_card",
  {
    id: id(),
    createdAt: createdAt(),
    topicId: topicRef().notNull(),
    subtopicId: uuid("subtopic_id")
      .notNull()
      .references(() => subtopic.id, { onDelete: "cascade" }),
    requestedDifficulty: difficulty("requested_difficulty").notNull(),
    title: varchar("title", { length: 120 }).notNull(),
    canonicalTitle: varchar("canonical_title", { length: 160 }).notNull(),
    summary: text("summary").notNull(),
    body: text("body").notNull(),
    stage: rejectionStage("stage").notNull(),
    reason: text("reason").notNull(),
    genMeta: jsonb("gen_meta").$type<Record<string, unknown>>().notNull().default({}),
  },
  (t) => [index("ix_rejected_card_subtopic_id").on(t.subtopicId)],
);

/** A reader flagging a live card as structurally broken (ADR-0076): a moderation signal, never a ranking input. */
export const cardReport = pgTable(
  "card_report",
  {
    id: id(),
    createdAt: createdAt(),
    cardId: cardRef().notNull(),
    userId: userRef().notNull(),
    reason: cardReportReason("reason").notNull(),
    note: text("note"),
    /** Reports for one card are resolved together, by card. */
    resolvedAt: tz("resolved_at"),
  },
  (t) => [
    unique("uq_card_report_card_user").on(t.cardId, t.userId),
    index("ix_card_report_unresolved").on(t.cardId).where(sql`resolved_at IS NULL`),
  ],
);

/** The operator's instruction for a reported card, plus its audit trail (ADR-0076). */
export const cardRepair = pgTable(
  "card_repair",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    cardId: cardRef().notNull(),
    jobId: uuid("job_id").references(() => generationJob.id, { onDelete: "set null" }),
    mode: repairMode("mode").notNull(),
    /** Required for REMAKE (the brief), optional for FIX; enforced at the API. */
    guidance: text("guidance"),
    /** The card rendered to PNG by the admin page, the FIX call's visual reference. */
    sourceImage: bytea("source_image"),
    status: repairStatus("status").notNull().default("pending"),
    resultCardId: uuid("result_card_id").references(() => card.id, { onDelete: "set null" }),
    error: text("error"),
    resolvedAt: tz("resolved_at"),
    dismissedAt: tz("dismissed_at"),
  },
  (t) => [index("ix_card_repair_status").on(t.status)],
);

/** One persistent AskAI thread per topic per user; at most one active (ADR-0077). */
export const askConversation = pgTable(
  "ask_conversation",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    /** 'active' | 'archived'. */
    status: varchar("status", { length: 16 }).notNull().default("active"),
    lastMessageAt: tz("last_message_at"),
  },
  (t) => [uniqueIndex("uq_ask_conversation_active").on(t.userId, t.topicId).where(sql`status = 'active'`)],
);

export const askMessage = pgTable(
  "ask_message",
  {
    id: id(),
    createdAt: createdAt(),
    conversationId: uuid("conversation_id")
      .notNull()
      .references(() => askConversation.id, { onDelete: "cascade" }),
    /** 'user' | 'assistant'. */
    role: varchar("role", { length: 16 }).notNull(),
    content: text("content").notNull(),
    /** Assistant rows: false when refused, and `content` is the server-built hint, never model prose. */
    onTopic: boolean("on_topic").notNull().default(true),
  },
  (t) => [index("ix_ask_message_conversation").on(t.conversationId, t.createdAt)],
);

/** AskAI turns that reached a model, per user per UTC day. Refusals cost nothing and are not counted. */
export const askUsage = pgTable(
  "ask_usage",
  {
    day: tz("day").notNull(),
    userId: userRef().notNull(),
    questionsSpent: integer("questions_spent").notNull().default(0),
  },
  (t) => [primaryKey({ columns: [t.day, t.userId] })],
);

// ------------------------------------------------------------- engagement --
// Three kinds of data, not one table (ADR-0011): append-only events, mutable state,
// and derived aggregates rebuildable from the events.

/** Immutable, never updated: the truth every aggregate is rebuilt from. */
export const engagementEvent = pgTable(
  "engagement_event",
  {
    /** Client-generated and the primary key, so a retried batch collides instead of inserting twice. */
    id: uuid("id").primaryKey(),
    userId: userRef().notNull(),
    cardId: cardRef().notNull(),
    topicId: uuid("topic_id").notNull(),
    subtopicId: uuid("subtopic_id").notNull(),
    kind: engagementKind("kind").notNull(),
    dwellMs: integer("dwell_ms"),
    /** SERVER-assigned, always: client clocks are wrong, sometimes deliberately. */
    occurredAt: tz("occurred_at").notNull().defaultNow(),
    /** For ordering within a batch only. */
    clientOccurredAt: tz("client_occurred_at"),
    sessionId: uuid("session_id"),
  },
  (t) => [
    index("ix_engagement_event_card_id_kind").on(t.cardId, t.kind),
    index("ix_engagement_event_user_id_occurred_at").on(t.userId, t.occurredAt),
    check("ck_engagement_event_dwell_non_negative", sql`${t.dwellMs} IS NULL OR ${t.dwellMs} >= 0`),
  ],
);

export const cardLike = pgTable(
  "card_like",
  { userId: userRef().notNull(), cardId: cardRef().notNull(), createdAt: createdAt() },
  (t) => [primaryKey({ columns: [t.userId, t.cardId] })],
);

export const cardBookmark = pgTable(
  "card_bookmark",
  { userId: userRef().notNull(), cardId: cardRef().notNull(), createdAt: createdAt() },
  (t) => [primaryKey({ columns: [t.userId, t.cardId] })],
);

/** Private: never shared, never fed to ranking. */
export const cardNote = pgTable(
  "card_note",
  {
    userId: userRef().notNull(),
    cardId: cardRef().notNull(),
    body: text("body").notNull(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.cardId] })],
);

/** Seen-state, the source of truth: three states plus a cycle counter (ADR-0010). */
export const userCardState = pgTable(
  "user_card_state",
  {
    userId: userRef().notNull(),
    cardId: cardRef().notNull(),
    /** Denormalised so the feed's eligibility query does not join back to `card`. */
    topicId: uuid("topic_id").notNull(),
    subtopicId: uuid("subtopic_id").notNull(),
    state: seenState("state").notNull().default("unseen"),
    /** The cycle this card was deferred in; eligible again once the topic's cycle moves past it. */
    deferredCycle: integer("deferred_cycle"),
    /** Which path marked it SEEN: both satisfy the gate, they are very different ranking signals. */
    completedVia: engagementKind("completed_via"),
    seenAt: tz("seen_at"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [
    primaryKey({ columns: [t.userId, t.cardId] }),
    index("ix_user_card_state_user_id_topic_id_state").on(t.userId, t.topicId, t.state),
  ],
);

/** Advances when nothing UNSEEN remains at a difficulty, which releases the DEFERRED pile. */
export const userTopicCycle = pgTable(
  "user_topic_cycle",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    difficulty: difficulty("difficulty").notNull(),
    cycle: integer("cycle").notNull().default(0),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId, t.difficulty] })],
);

/** Long-run engagement weight per topic; drives the interleave plan. */
export const userTopicAffinity = pgTable(
  "user_topic_affinity",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    affinity: doublePrecision("affinity").notNull().default(1),
    recomputedAt: tz("recomputed_at"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId] })],
);

/**
 * The CURRENT session's weight per topic (ADR-0055). Separate from affinity on purpose:
 * "what do they like" and "what are they doing now" are different numbers, and the
 * session reset must not destroy weeks of history.
 */
export const userSessionTopicSignal = pgTable(
  "user_session_topic_signal",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    /** Signed: skips and un-likes push a topic toward its floor share. */
    score: doublePrecision("score").notNull().default(0),
    /** The session boundary, server-assigned: a client session id would fragment and be spoofable. */
    lastEventAt: tz("last_event_at").notNull().defaultNow(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId] })],
);

/** seen_count / total_count: the 80% coverage gate's inputs. */
export const userSubtopicProgress = pgTable(
  "user_subtopic_progress",
  {
    userId: userRef().notNull(),
    subtopicId: uuid("subtopic_id")
      .notNull()
      .references(() => subtopic.id, { onDelete: "cascade" }),
    seenCount: integer("seen_count").notNull().default(0),
    totalCount: integer("total_count").notNull().default(0),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.subtopicId] })],
);

/** Across a whole tier of one topic: the difficulty-mix ramp's input (`feed/strata`). */
export const userTopicDifficultyProgress = pgTable(
  "user_topic_difficulty_progress",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    difficulty: difficulty("difficulty").notNull(),
    seenCount: integer("seen_count").notNull().default(0),
    totalCount: integer("total_count").notNull().default(0),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId, t.difficulty] })],
);

/** Derived read model over `user_card_state`, always rebuildable (ADR-0010). */
export const userSeenBitmap = pgTable(
  "user_seen_bitmap",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    bits: bytea("bits").notNull(),
    rebuiltAt: tz("rebuilt_at"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId] })],
);

/**
 * ~25 ranked card ids for ONE topic. Per topic because quality is a rate, and rates are
 * only commensurable within a topic (ADR-0010).
 */
export const feedSlate = pgTable(
  "feed_slate",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    cardIds: uuid("card_ids").array().notNull(),
    /** How far into this slate the user has read; survives filter changes, so filtering never repeats. */
    position: integer("position").notNull().default(0),
    /** Built under a starved pool (ADR-0006), so the end of feed can be honest. */
    degraded: boolean("degraded").notNull().default(false),
    expiresAt: tz("expires_at").notNull(),
  },
  (t) => [unique("uq_feed_slate_user_id_topic_id").on(t.userId, t.topicId)],
);

/** The interleave plan: cheap and regenerated freely, a single integer position into it. */
export const feedPlan = pgTable("feed_plan", {
  id: id(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
  userId: userRef().notNull().unique("uq_feed_plan_user_id"),
  topicOrder: uuid("topic_order").array().notNull(),
  position: integer("position").notNull().default(0),
  /** The filter this plan was built for; a change rebuilds the plan and keeps every slate. */
  filterKey: varchar("filter_key", { length: 64 }).notNull().default(""),
  /** Quantized topic shares, so only a share crossing a bucket counts as a shift (ADR-0055). */
  shareFingerprint: varchar("share_fingerprint", { length: 64 }).notNull().default(""),
});

// ------------------------------------------------------------ preferences --

/** One row per user, created on first write (ADR-0070). */
export const userPreference = pgTable("user_preference", {
  userId: userRef().primaryKey(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
  palette: varchar("palette", { length: 64 }).notNull().default("notebook"),
  /** `[{id, name, bg, fg, accent, accent2}]`, schema-checked at the API boundary. */
  customPalettes: jsonb("custom_palettes").$type<Record<string, string>[]>().notNull().default([]),
  font: varchar("font", { length: 64 }).notNull().default("literata"),
});

/** An imported font file. Every read is scoped to the caller in the query itself. */
export const userFont = pgTable(
  "user_font",
  {
    id: id(),
    createdAt: createdAt(),
    userId: userRef().notNull(),
    name: varchar("name", { length: 80 }).notNull(),
    /** Sniffed from the file's magic bytes, never the declared content type. */
    format: varchar("format", { length: 8 }).notNull(),
    data: bytea("data").notNull(),
    byteSize: integer("byte_size").notNull(),
  },
  (t) => [
    check("ck_user_font_format_valid", sql`${t.format} IN ('woff2', 'ttf', 'otf')`),
    index("ix_user_font_user_id").on(t.userId),
  ],
);

// ------------------------------------------------------------------- quiz --

/** Generated FROM A CARD, never from the topic in the abstract: every wrong answer links to what teaches it. */
export const question = pgTable(
  "question",
  {
    id: id(),
    createdAt: createdAt(),
    subtopicId: uuid("subtopic_id")
      .notNull()
      .references(() => subtopic.id, { onDelete: "cascade" }),
    cardId: cardRef().notNull(),
    difficulty: difficulty("difficulty").notNull(),
    kind: questionKind("kind").notNull(),
    stem: text("stem").notNull(),
    options: text("options").array(),
    correctIndex: integer("correct_index"),
    /** Explicit 0-3 levels: inconsistent grading between attempts destroys trust faster than harsh grading. */
    rubric: text("rubric"),
    referenceAnswer: text("reference_answer"),
    explanation: text("explanation"),
    status: questionStatus("status").notNull().default("draft"),
    embedding: vector("embedding", { dimensions: EMBEDDING_DIM }),
    embeddingModel: varchar("embedding_model", { length: 120 }),
    genMeta: jsonb("gen_meta").$type<Record<string, unknown>>().notNull().default({}),
  },
  (t) => [
    index("ix_question_subtopic_id_status").on(t.subtopicId, t.status),
    check(
      "ck_question_kind_fields_present",
      sql`(${t.kind} = 'mcq' AND ${t.options} IS NOT NULL AND ${t.correctIndex} IS NOT NULL) OR (${t.kind} = 'free_text' AND ${t.rubric} IS NOT NULL)`,
    ),
    check(
      "ck_question_embedding_names_its_model",
      sql`(${t.embedding} IS NULL) = (${t.embeddingModel} IS NULL)`,
    ),
  ],
);

export const userQuestionSeen = pgTable(
  "user_question_seen",
  {
    userId: userRef().notNull(),
    questionId: uuid("question_id")
      .notNull()
      .references(() => question.id, { onDelete: "cascade" }),
    createdAt: createdAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.questionId] })],
);

export const quizAttempt = pgTable("quiz_attempt", {
  id: id(),
  createdAt: createdAt(),
  userId: userRef().notNull(),
  topicId: topicRef().notNull(),
  difficulty: difficulty("difficulty").notNull(),
  kind: quizKind("kind").notNull(),
  /** Weighted 70% MCQ / 30% free text, or the written answer would be 10% of the grade. */
  score: doublePrecision("score"),
  passed: boolean("passed"),
  startedAt: tz("started_at").notNull(),
  submittedAt: tz("submitted_at"),
  gradedAt: tz("graded_at"),
});

export const quizAttemptQuestion = pgTable(
  "quiz_attempt_question",
  {
    attemptId: uuid("attempt_id")
      .notNull()
      .references(() => quizAttempt.id, { onDelete: "cascade" }),
    questionId: uuid("question_id")
      .notNull()
      .references(() => question.id, { onDelete: "cascade" }),
    createdAt: createdAt(),
    /** Length-capped before it is stored, so a pasted answer cannot blow the grading call. */
    userAnswer: text("user_answer"),
    correct: boolean("correct"),
    rubricLevel: integer("rubric_level"),
    /** The grader's justification, kept so a disputed score can be audited. */
    justification: text("justification"),
  },
  (t) => [primaryKey({ columns: [t.attemptId, t.questionId] })],
);

/**
 * Per-user, per-topic progression. `tier_unlocked` is LATCHED and never recomputed:
 * background generation must never silently revoke earned progress.
 */
export const userTopicProgress = pgTable(
  "user_topic_progress",
  {
    userId: userRef().notNull(),
    topicId: topicRef().notNull(),
    currentDifficulty: difficulty("current_difficulty").notNull().default("beginner"),
    /** The QUIZ unlock latch per tier, not "may read this tier". */
    tierUnlocked: boolean("tier_unlocked").array().notNull().default(sql`ARRAY[false, false, false]`),
    tierContentComplete: boolean("tier_content_complete")
      .array()
      .notNull()
      .default(sql`ARRAY[false, false, false]`),
    tierQuizPassed: boolean("tier_quiz_passed").array().notNull().default(sql`ARRAY[false, false, false]`),
    /** Permanent once set, never revoked by a later failed attempt. */
    masteredAt: tz("mastered_at"),
    revisitMode: boolean("revisit_mode").notNull().default(false),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [primaryKey({ columns: [t.userId, t.topicId] })],
);

/**
 * A unit of work for the worker. `generate` runs one topic's pipeline and is coalesced
 * per topic; `repair` fixes or remakes one reported card and is coalesced per card
 * (ADR-0076). The tadpole harness replaces the generate half (ADR-0106).
 */
export const generationJob = pgTable(
  "generation_job",
  {
    id: id(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
    /** 'generate' | 'repair'. */
    kind: varchar("kind", { length: 16 }).notNull().default("generate"),
    topicId: topicRef().notNull(),
    cardId: cardRef(),
    /** 'pending' | 'running' | 'completed' | 'failed'. */
    status: varchar("status", { length: 16 }).notNull().default("pending"),
    /** Live progress for the request-a-topic view; best-effort, never blocks the work. */
    progress: jsonb("progress").$type<Record<string, unknown>>(),
    /** Higher runs first: a real user waiting outranks speculative work. */
    priority: integer("priority").notNull().default(0),
    attempts: integer("attempts").notNull().default(0),
    lastError: text("last_error"),
    completedAt: tz("completed_at"),
  },
  (t) => [
    uniqueIndex("uq_generation_job_topic_pending")
      .on(t.topicId)
      .where(sql`kind = 'generate' AND status IN ('pending', 'running')`),
    uniqueIndex("uq_generation_job_card_pending")
      .on(t.cardId)
      .where(sql`kind = 'repair' AND status IN ('pending', 'running')`),
    index("ix_generation_job_status_priority").on(t.status, t.priority),
  ],
);

/** Every background job's last success and last failure, for the admin status view (breader's pattern). */
export const jobRuns = pgTable("job_runs", {
  name: varchar("name", { length: 64 }).primaryKey(),
  lastOkAt: tz("last_ok_at"),
  lastError: text("last_error"),
  lastErrorAt: tz("last_error_at"),
  detail: jsonb("detail").$type<Record<string, unknown>>(),
});
