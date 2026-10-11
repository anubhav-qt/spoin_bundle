/**
 * The wire contract. The server validates requests with these and declares its
 * responses with them; the OpenAPI document is generated from them; the web client
 * types its calls with them. A rename here is a breaking change for every client.
 *
 * Field names stay snake_case: this is the contract the web app already speaks.
 */
import { z } from "zod";
import {
  CARD_REPORT_REASONS,
  DIFFICULTIES,
  ENGAGEMENT_KINDS,
  QUIZ_KINDS,
  REPAIR_MODES,
  REPAIR_STATUSES,
  TOPIC_SCOPES,
  VISUAL_KINDS,
} from "./enums.ts";

export const Difficulty = z.enum(DIFFICULTIES);
export const EngagementKind = z.enum(ENGAGEMENT_KINDS);
export const VisualKind = z.enum(VISUAL_KINDS);
export const CardReportReason = z.enum(CARD_REPORT_REASONS);
export const RepairMode = z.enum(REPAIR_MODES);
export const RepairStatus = z.enum(REPAIR_STATUSES);
/** Only `topic` has tiers. Survey and one-shot are tierless: cards easy to advanced, one mastery quiz (ADR-0106). */
export const TopicScope = z.enum(TOPIC_SCOPES);

const Uuid = z.uuid();
/** ISO-8601, as the server serializes a timestamp. */
const DateTime = z.iso.datetime({ offset: true });

/** The body of every error response. `detail` is shown to the user as written. */
export const ErrorOut = z
  .object({ detail: z.string(), request_id: z.string().optional() })
  .meta({ id: "ErrorOut" });

// ---------------------------------------------------------------------- topics --

export const TopicOut = z
  .object({
    id: Uuid,
    /** Always the user's own name for the topic, never `canonical_name` (ADR-0004). */
    display_name: z.string(),
    slug: z.string(),
    is_custom: z.boolean(),
    scope: TopicScope,
    /** Always `beginner` on a tierless topic, which has no tiers to climb. */
    current_difficulty: Difficulty,
    /** 0-359, -1 opts out of topic colour (ADR-0051), null uses the deterministic default (ADR-0034). */
    accent_hue: z.int().nullable().default(null),
  })
  .meta({ id: "TopicOut" });

export const TopicColorIn = z
  .object({ hue: z.int().min(-1).max(359).nullable().default(null) })
  .meta({ id: "TopicColorIn" });

/** A user typing a topic by name. Matching decides whether it joins an existing topic (ADR-0025). */
export const TopicRequestIn = z
  .object({
    name: z.string().min(1).max(120),
    description: z.string().nullable().optional(),
    /** Trusted unconditionally, no quiz gates it (ADR-0027). */
    entry_difficulty: Difficulty.default("beginner"),
  })
  .meta({ id: "TopicRequestIn" });

export const TopicRequestOut = z
  .object({
    topic: TopicOut,
    /** "generating": a new topic was queued; the client shows a building state, never a spinner for cards. */
    status: z.enum(["subscribed", "generating"]),
  })
  .meta({ id: "TopicRequestOut" });

/** Several custom topics in one submission, matched in one call (task 0032). */
export const TopicBatchIn = z.object({ items: z.array(TopicRequestIn).min(1) }).meta({ id: "TopicBatchIn" });

/** One row's own outcome: a batch where 4 of 5 succeed is a success with one rejected row. */
export const TopicBatchItemOut = z
  .object({
    request_index: z.int(),
    status: z.enum(["generating", "subscribed", "already_subscribed", "rejected"]),
    topic: TopicOut.nullable().default(null),
    detail: z.string().nullable().default(null),
  })
  .meta({ id: "TopicBatchItemOut" });

export const TopicBatchOut = z.object({ results: z.array(TopicBatchItemOut) }).meta({ id: "TopicBatchOut" });

export const TopicDiscoverOut = z
  .object({
    topic_id: Uuid,
    /** `canonical_name`: a topic surfaced here has no personal label yet (ADR-0004). */
    display_name: z.string(),
    subscriber_count: z.int(),
    followed: z.boolean().default(false),
  })
  .meta({ id: "TopicDiscoverOut" });

export const CustomTopicStatusOut = z
  .object({
    topic_id: Uuid,
    display_name: z.string(),
    slug: z.string(),
    /** "pending" | "running" | "completed" | "failed", or null when nothing was queued. */
    generation_status: z.string().nullable(),
    requested_at: DateTime,
  })
  .meta({ id: "CustomTopicStatusOut" });

export const GenerationSubtopicProgressOut = z
  .object({
    subtopic_id: Uuid,
    group_title: z.string(),
    difficulty: Difficulty,
    cards_target: z.int(),
    cards_done: z.int(),
    /** Null until this tier's cards have landed: how many need a question isn't known before. */
    questions_target: z.int().nullable(),
    questions_done: z.int(),
  })
  .meta({ id: "GenerationSubtopicProgressOut" });

export const GenerationProgressOut = z
  .object({
    status: z.enum(["pending", "running", "completed", "failed"]),
    stage: z.enum(["curriculum", "cards", "done"]).nullable(),
    topic_name: z.string().nullable(),
    subtopics: z.array(GenerationSubtopicProgressOut),
    error: z.string().nullable(),
    /** True once the topic crossed the live-coverage threshold and shows to everyone (ADR-0053). */
    topic_live: z.boolean(),
  })
  .meta({ id: "GenerationProgressOut" });

export const ProgressOut = z
  .object({
    topic_id: Uuid,
    scope: TopicScope,
    current_difficulty: Difficulty,
    /**
     * Fraction seen in the thinnest subtopic of the current tier, or of the whole topic
     * when it is tierless: the gate is per subtopic.
     */
    coverage: z.number(),
    /** Latched: background generation can never revoke it. */
    quiz_unlocked: z.boolean(),
    /** A tierless topic's one quiz is recorded in the advanced slot. */
    tier_quiz_passed: z.array(z.boolean()),
    mastered: z.boolean(),
  })
  .meta({ id: "ProgressOut" });

export const TopicStatsOut = z
  .object({
    topic_id: Uuid,
    scope: TopicScope,
    current_difficulty: Difficulty,
    coverage: z.number(),
    quiz_unlocked: z.boolean(),
    mastered: z.boolean(),
    tier_quiz_passed: z.array(z.boolean()),
    likes: z.int(),
    saves: z.int(),
    notes: z.int(),
    shares: z.int(),
  })
  .meta({ id: "TopicStatsOut" });

export const SubtopicProgressOut = z
  .object({
    subtopic_id: Uuid,
    title: z.string(),
    difficulty: Difficulty,
    /** 0 means nothing generated yet: render "not generated yet", not 0% coverage. */
    total_cards: z.int(),
    seen_cards: z.int(),
    coverage: z.number(),
    covered: z.boolean(),
  })
  .meta({ id: "SubtopicProgressOut" });

export const TopicCurriculumOut = z
  .object({ topic_id: Uuid, subtopics: z.array(SubtopicProgressOut) })
  .meta({ id: "TopicCurriculumOut" });

export const OnboardingTopicChoice = z
  .object({ topic_id: Uuid, entry_difficulty: Difficulty.default("beginner") })
  .meta({ id: "OnboardingTopicChoice" });

export const OnboardingCompleteIn = z
  .object({ topics: z.array(OnboardingTopicChoice).max(10).default([]) })
  .meta({ id: "OnboardingCompleteIn" });

// ------------------------------------------------------------------------ feed --

export const CardOut = z
  .object({
    id: Uuid,
    topic_id: Uuid,
    subtopic_id: Uuid,
    /** Sent so the feed can label stations without a second round trip on the <100ms path. */
    subtopic_title: z.string(),
    difficulty: Difficulty,
    title: z.string(),
    summary: z.string(),
    body: z.string(),
    /** Content shapes derived from `body` itself, never self-reported (ADR-0017). */
    archetype: z.array(z.string()),
    is_hero: z.boolean(),
    visual_id: z.string().nullable().default(null),
    visual_kind: VisualKind.nullable().default(null),
    /**
     * ASCII: `{art, alt}`. Image: `{title, attribution, display_url, source_page, licence}`.
     * Attribution travels on the card because CC BY makes displaying it a licence condition.
     */
    visual_slots: z.record(z.string(), z.string()).nullable().default(null),
    created_at: DateTime,
    /** This user's private note, from a separate query: notes never feed ranking. */
    note: z.string().nullable().default(null),
    seen: z.boolean().default(false),
  })
  .meta({ id: "CardOut" });

export const FeedOut = z
  .object({
    cards: z.array(CardOut),
    next_position: z.int(),
    /** The pool could not satisfy the mix, so this page is short by design: degraded, not wrong. */
    degraded: z.boolean(),
    /** True end of feed: "more coming soon", never an endless spinner. */
    exhausted: z.boolean(),
    /** A repeat pass, announced once: an unexplained repeat reads as a bug. */
    recycling: z.boolean().default(false),
  })
  .meta({ id: "FeedOut" });

export const LikedCardOut = z
  .object({ card: CardOut, topic_name: z.string(), liked_at: DateTime })
  .meta({ id: "LikedCardOut" });

export const SavedCardOut = z
  .object({ card: CardOut, topic_name: z.string(), saved_at: DateTime })
  .meta({ id: "SavedCardOut" });

export const CollectionSort = z.enum(["recent", "oldest", "topic", "difficulty"]);

// ------------------------------------------------------------------ engagement --

export const EngagementEventIn = z
  .object({
    /** Client-generated and required: the idempotency key, so retries collide rather than inflate. */
    id: Uuid,
    card_id: Uuid,
    kind: EngagementKind,
    dwell_ms: z.int().min(0).nullable().optional(),
    /** For ordering within a batch only; `occurred_at` is server-assigned. */
    client_occurred_at: DateTime.nullable().optional(),
    session_id: Uuid.nullable().optional(),
  })
  .meta({ id: "EngagementEventIn" });

export const EngagementBatchIn = z
  .object({ events: z.array(EngagementEventIn).max(200) })
  .meta({ id: "EngagementBatchIn" });

export const EngagementAck = z
  .object({ accepted: z.int(), duplicates: z.int(), rejected: z.int() })
  .meta({ id: "EngagementAck" });

// ------------------------------------------------------------------------ quiz --

/**
 * `difficulty` picks the tier on a topic with tiers, where leaving it out is a 422. A
 * tierless topic has one quiz, so it is ignored there.
 */
export const QuizStartIn = z.object({ difficulty: Difficulty.optional() }).meta({ id: "QuizStartIn" });

/** Never `correct_index`: that would let the client grade itself. */
export const QuizMcqQuestionOut = z
  .object({ question_id: Uuid, stem: z.string(), options: z.array(z.string()) })
  .meta({ id: "QuizMcqQuestionOut" });

export const QuizFreeTextQuestionOut = z
  .object({ question_id: Uuid, stem: z.string() })
  .meta({ id: "QuizFreeTextQuestionOut" });

export const QuizStartOut = z
  .object({
    attempt_id: Uuid,
    topic_id: Uuid,
    /** `advanced` on a tierless topic, whose one quiz is a mastery quiz across every difficulty. */
    difficulty: Difficulty,
    kind: z.enum(QUIZ_KINDS),
    mcq: z.array(QuizMcqQuestionOut),
    free_text: QuizFreeTextQuestionOut,
  })
  .meta({ id: "QuizStartOut" });

export const McqAnswerIn = z
  .object({ question_id: Uuid, selected_index: z.int().min(0) })
  .meta({ id: "McqAnswerIn" });

export const QuizSubmitMcqIn = z.object({ answers: z.array(McqAnswerIn) }).meta({ id: "QuizSubmitMcqIn" });

export const McqResultOut = z
  .object({ question_id: Uuid, correct: z.boolean(), correct_index: z.int(), explanation: z.string() })
  .meta({ id: "McqResultOut" });

/** Immediate and deterministic: the free-text answer is a separate call so this never waits on a model. */
export const QuizSubmitMcqOut = z
  .object({ attempt_id: Uuid, results: z.array(McqResultOut), mcq_score: z.number() })
  .meta({ id: "QuizSubmitMcqOut" });

export const QuizSubmitFreeTextIn = z.object({ answer: z.string() }).meta({ id: "QuizSubmitFreeTextIn" });

export const QuizFreeTextResultOut = z
  .object({ question_id: Uuid, rubric_level: z.int(), correct: z.boolean(), justification: z.string() })
  .meta({ id: "QuizFreeTextResultOut" });

export const RemediationCardOut = z
  .object({ card_id: Uuid, title: z.string(), subtopic_title: z.string() })
  .meta({ id: "RemediationCardOut" });

export const QuizSubmitFreeTextOut = z
  .object({
    attempt_id: Uuid,
    free_text: QuizFreeTextResultOut,
    /** Weighted 70% MCQ / 30% free text (ADR-0009). */
    score: z.number(),
    passed: z.boolean(),
    remediation: z.array(RemediationCardOut),
    progressed: z.boolean(),
  })
  .meta({ id: "QuizSubmitFreeTextOut" });

// ------------------------------------------------------- appearance preferences --

const HexColor = z.string().regex(/^#[0-9a-fA-F]{6}$/u);

export const CustomPalette = z
  .object({
    id: z
      .string()
      .min(1)
      .max(64)
      .regex(/^[A-Za-z0-9_-]+$/u),
    name: z.string().min(1).max(40),
    bg: HexColor,
    fg: HexColor,
    accent: HexColor,
    accent2: HexColor,
  })
  .meta({ id: "CustomPalette" });

/** Metadata only: the bytes are served by their own endpoint, never inlined (ADR-0070). */
export const ImportedFontOut = z
  .object({ id: Uuid, name: z.string(), format: z.string(), byte_size: z.int() })
  .meta({ id: "ImportedFontOut" });

export const PreferencesOut = z
  .object({
    palette: z.string(),
    custom_palettes: z.array(CustomPalette),
    font: z.string(),
    imported_fonts: z.array(ImportedFontOut),
  })
  .meta({ id: "PreferencesOut" });

/** Whole-object replace: the client always holds the full picture. */
export const PreferencesUpdateIn = z
  .object({
    palette: z.string().min(1).max(64),
    // A generous ceiling: the picker scrolls well before this, and the column has no business holding hundreds.
    custom_palettes: z.array(CustomPalette).max(50, "At most 50 saved themes."),
    font: z.string().min(1).max(64),
  })
  .meta({ id: "PreferencesUpdateIn" });

export const UserOut = z
  .object({
    id: Uuid,
    /** Null for a guest. */
    email: z.string().nullable(),
    display_name: z.string(),
    is_guest: z.boolean(),
    onboarding_complete: z.boolean(),
    age: z.int().nullable().default(null),
    gender: z.string().nullable().default(null),
    avatar_icon: z.string().nullable().default(null),
    has_avatar_image: z.boolean().default(false),
    daily_card_goal: z.int().default(10),
    /** Populated only on `/auth/me`, where the client reconciles its pre-paint cache (ADR-0070). */
    preferences: PreferencesOut.nullable().default(null),
    /** True for an operator. Admin pages are shown only to these accounts (ADR-0106). */
    is_admin: z.boolean().default(false),
  })
  .meta({ id: "UserOut" });

/**
 * A guest becoming an account in place (ADR-0033): same user id, so everything keyed
 * off it carries over. Signing up or in from scratch is Better Auth's (`/auth/*`).
 */
export const ClaimIn = z
  .object({
    email: z.email().max(320),
    password: z.string().min(8).max(128),
    display_name: z.string().trim().min(1).max(80),
  })
  .meta({ id: "ClaimIn" });

/** The same, with an ID token from the client's own Google Sign-In. */
export const GoogleClaimIn = z.object({ id_token: z.string().min(1) }).meta({ id: "GoogleClaimIn" });

// ------------------------------------------------------------------------ notes --

export const NoteIn = z.object({ body: z.string().min(1).max(10_000) }).meta({ id: "NoteIn" });

export const NoteOut = z
  .object({ card_id: Uuid, body: z.string(), updated_at: DateTime })
  .meta({ id: "NoteOut" });

export const NoteWithCardOut = z
  .object({ note: NoteOut, card: CardOut, topic_name: z.string() })
  .meta({ id: "NoteWithCardOut" });

// ---------------------------------------------------------------------- profile --

export const UserProfileUpdateIn = z
  .object({
    display_name: z.string().min(1).max(80).nullable().optional(),
    age: z.int().min(1).max(120).nullable().optional(),
    gender: z.string().max(32).nullable().optional(),
    avatar_icon: z.string().max(32).nullable().optional(),
    /** Bounded here, not just in the picker: the endpoint is the authority. */
    daily_card_goal: z.int().min(1).max(200).nullable().optional(),
  })
  .meta({ id: "UserProfileUpdateIn" });

export const DailyActivityOut = z
  .object({ date: z.string(), cards_read: z.int() })
  .meta({ id: "DailyActivityOut" });

export const ProfileStatsOut = z
  .object({
    current_streak: z.int(),
    longest_streak: z.int(),
    total_cards_read: z.int(),
    total_topics: z.int(),
    monthly_activity: z.array(DailyActivityOut),
  })
  .meta({ id: "ProfileStatsOut" });

/** "Today" is the caller's local day: the client sends its offset (ADR-0062). */
export const DailyGoalOut = z.object({ cards_read: z.int(), goal: z.int() }).meta({ id: "DailyGoalOut" });

export const ExportedCardRefOut = z
  .object({ card_id: Uuid, title: z.string(), topic: z.string(), difficulty: Difficulty, at: DateTime })
  .meta({ id: "ExportedCardRefOut" });

export const ExportedNoteOut = z
  .object({
    card_id: Uuid,
    card_title: z.string(),
    topic: z.string(),
    body: z.string(),
    updated_at: DateTime,
  })
  .meta({ id: "ExportedNoteOut" });

export const ExportedTopicOut = z
  .object({
    topic_id: Uuid,
    name: z.string(),
    is_custom: z.boolean(),
    current_difficulty: Difficulty.nullable(),
    followed_at: DateTime,
  })
  .meta({ id: "ExportedTopicOut" });

/** The user's OWN content only: nothing derived, nothing about others, no shared card bodies. */
export const ProfileExportOut = z
  .object({
    exported_at: DateTime,
    schema_version: z.int(),
    profile: UserOut,
    topics: z.array(ExportedTopicOut),
    notes: z.array(ExportedNoteOut),
    liked_cards: z.array(ExportedCardRefOut),
    saved_cards: z.array(ExportedCardRefOut),
    daily_activity: z.array(DailyActivityOut),
  })
  .meta({ id: "ProfileExportOut" });

// ------------------------------------------------- reports and repairs (ADR-0076) --

export const CardReportIn = z
  .object({ reason: CardReportReason, note: z.string().max(2000).nullable().optional() })
  .meta({ id: "CardReportIn" });

export const RepairReportOut = z
  .object({ reason: CardReportReason, note: z.string().nullable(), created_at: DateTime })
  .meta({ id: "RepairReportOut" });

export const RepairAttemptOut = z
  .object({ mode: RepairMode, status: RepairStatus, error: z.string().nullable(), created_at: DateTime })
  .meta({ id: "RepairAttemptOut" });

export const RepairCardOut = z
  .object({
    card_id: Uuid,
    version: z.int(),
    title: z.string(),
    canonical_title: z.string(),
    summary: z.string(),
    body: z.string(),
    archetype: z.array(z.string()),
    visual_id: z.string().nullable(),
    visual_slots: z.record(z.string(), z.string()).nullable(),
  })
  .meta({ id: "RepairCardOut" });

export const RepairQueueItemOut = z
  .object({
    card_id: Uuid,
    topic_id: Uuid,
    family_id: Uuid,
    difficulty: Difficulty,
    before: RepairCardOut,
    after: RepairCardOut.nullable(),
    report_count: z.int(),
    reports: z.array(RepairReportOut),
    latest_repair: RepairAttemptOut.nullable(),
    state: z.enum(["open", "resolved"]),
  })
  .meta({ id: "RepairQueueItemOut" });

export const RepairEnqueuedOut = z
  .object({
    card_id: Uuid,
    action: z.enum(["deleted", "fix_enqueued", "remake_enqueued", "dismissed", "reverted"]),
    job_id: Uuid.nullable().default(null),
  })
  .meta({ id: "RepairEnqueuedOut" });

export const AsciiSceneOut = z
  .object({
    card_id: Uuid,
    title: z.string(),
    canonical_title: z.string(),
    summary: z.string(),
    difficulty: Difficulty,
    subtopic_title: z.string().nullable(),
    art: z.string(),
    alt: z.string(),
    src_id: z.string().nullable(),
    library_title: z.string().nullable(),
    library_art: z.string().nullable(),
    /** Reported rather than enforced. */
    widest_line: z.int(),
    max_width: z.int(),
  })
  .meta({ id: "AsciiSceneOut" });

export const AsciiSceneKeepIn = z
  .object({ art: z.string(), alt: z.string() })
  .meta({ id: "AsciiSceneKeepIn" });

export const AsciiSceneRejectIn = z
  .object({ note: z.string().nullable().optional() })
  .meta({ id: "AsciiSceneRejectIn" });

export const AsciiSceneActionOut = z
  .object({ card_id: Uuid, action: z.enum(["kept", "sent_to_repairs"]) })
  .meta({ id: "AsciiSceneActionOut" });

// ------------------------------------------------------- AskAI (ADR-0077, revised) --

export const AskMessageOut = z
  .object({
    role: z.enum(["user", "assistant"]),
    content: z.string(),
    /** Assistant rows only: false means a refused turn and `content` is the server's hint. */
    on_topic: z.boolean(),
    created_at: DateTime,
  })
  .meta({ id: "AskMessageOut" });

export const AskConversationOut = z
  .object({
    conversation_id: Uuid.nullable(),
    messages: z.array(AskMessageOut),
    spent: z.int(),
    limit: z.int(),
  })
  .meta({ id: "AskConversationOut" });

// -------------------------------------------------------------- types --
// One type per schema, named the same: the value is the validator, the type is its output.

export type Difficulty = z.infer<typeof Difficulty>;
export type EngagementKind = z.infer<typeof EngagementKind>;
export type VisualKind = z.infer<typeof VisualKind>;
export type CardReportReason = z.infer<typeof CardReportReason>;
export type RepairMode = z.infer<typeof RepairMode>;
export type RepairStatus = z.infer<typeof RepairStatus>;
export type ErrorOut = z.infer<typeof ErrorOut>;
export type TopicOut = z.infer<typeof TopicOut>;
export type TopicColorIn = z.infer<typeof TopicColorIn>;
export type TopicRequestIn = z.infer<typeof TopicRequestIn>;
export type TopicRequestOut = z.infer<typeof TopicRequestOut>;
export type TopicBatchIn = z.infer<typeof TopicBatchIn>;
export type TopicBatchItemOut = z.infer<typeof TopicBatchItemOut>;
export type TopicBatchOut = z.infer<typeof TopicBatchOut>;
export type TopicDiscoverOut = z.infer<typeof TopicDiscoverOut>;
export type CustomTopicStatusOut = z.infer<typeof CustomTopicStatusOut>;
export type GenerationSubtopicProgressOut = z.infer<typeof GenerationSubtopicProgressOut>;
export type GenerationProgressOut = z.infer<typeof GenerationProgressOut>;
export type ProgressOut = z.infer<typeof ProgressOut>;
export type TopicStatsOut = z.infer<typeof TopicStatsOut>;
export type SubtopicProgressOut = z.infer<typeof SubtopicProgressOut>;
export type TopicCurriculumOut = z.infer<typeof TopicCurriculumOut>;
export type OnboardingTopicChoice = z.infer<typeof OnboardingTopicChoice>;
export type OnboardingCompleteIn = z.infer<typeof OnboardingCompleteIn>;
export type CardOut = z.infer<typeof CardOut>;
export type FeedOut = z.infer<typeof FeedOut>;
export type LikedCardOut = z.infer<typeof LikedCardOut>;
export type SavedCardOut = z.infer<typeof SavedCardOut>;
export type CollectionSort = z.infer<typeof CollectionSort>;
export type EngagementEventIn = z.infer<typeof EngagementEventIn>;
export type EngagementBatchIn = z.infer<typeof EngagementBatchIn>;
export type EngagementAck = z.infer<typeof EngagementAck>;
export type QuizStartIn = z.infer<typeof QuizStartIn>;
export type QuizMcqQuestionOut = z.infer<typeof QuizMcqQuestionOut>;
export type QuizFreeTextQuestionOut = z.infer<typeof QuizFreeTextQuestionOut>;
export type QuizStartOut = z.infer<typeof QuizStartOut>;
export type McqAnswerIn = z.infer<typeof McqAnswerIn>;
export type QuizSubmitMcqIn = z.infer<typeof QuizSubmitMcqIn>;
export type McqResultOut = z.infer<typeof McqResultOut>;
export type QuizSubmitMcqOut = z.infer<typeof QuizSubmitMcqOut>;
export type QuizSubmitFreeTextIn = z.infer<typeof QuizSubmitFreeTextIn>;
export type QuizFreeTextResultOut = z.infer<typeof QuizFreeTextResultOut>;
export type RemediationCardOut = z.infer<typeof RemediationCardOut>;
export type QuizSubmitFreeTextOut = z.infer<typeof QuizSubmitFreeTextOut>;
export type CustomPalette = z.infer<typeof CustomPalette>;
export type ImportedFontOut = z.infer<typeof ImportedFontOut>;
export type PreferencesOut = z.infer<typeof PreferencesOut>;
export type PreferencesUpdateIn = z.infer<typeof PreferencesUpdateIn>;
export type UserOut = z.infer<typeof UserOut>;
export type ClaimIn = z.infer<typeof ClaimIn>;
export type GoogleClaimIn = z.infer<typeof GoogleClaimIn>;
export type NoteIn = z.infer<typeof NoteIn>;
export type NoteOut = z.infer<typeof NoteOut>;
export type NoteWithCardOut = z.infer<typeof NoteWithCardOut>;
export type UserProfileUpdateIn = z.infer<typeof UserProfileUpdateIn>;
export type DailyActivityOut = z.infer<typeof DailyActivityOut>;
export type ProfileStatsOut = z.infer<typeof ProfileStatsOut>;
export type DailyGoalOut = z.infer<typeof DailyGoalOut>;
export type ExportedCardRefOut = z.infer<typeof ExportedCardRefOut>;
export type ExportedNoteOut = z.infer<typeof ExportedNoteOut>;
export type ExportedTopicOut = z.infer<typeof ExportedTopicOut>;
export type ProfileExportOut = z.infer<typeof ProfileExportOut>;
export type CardReportIn = z.infer<typeof CardReportIn>;
export type RepairReportOut = z.infer<typeof RepairReportOut>;
export type RepairAttemptOut = z.infer<typeof RepairAttemptOut>;
export type RepairCardOut = z.infer<typeof RepairCardOut>;
export type RepairQueueItemOut = z.infer<typeof RepairQueueItemOut>;
export type RepairEnqueuedOut = z.infer<typeof RepairEnqueuedOut>;
export type AsciiSceneOut = z.infer<typeof AsciiSceneOut>;
export type AsciiSceneKeepIn = z.infer<typeof AsciiSceneKeepIn>;
export type AsciiSceneRejectIn = z.infer<typeof AsciiSceneRejectIn>;
export type AsciiSceneActionOut = z.infer<typeof AsciiSceneActionOut>;
export type AskMessageOut = z.infer<typeof AskMessageOut>;
export type AskConversationOut = z.infer<typeof AskConversationOut>;
