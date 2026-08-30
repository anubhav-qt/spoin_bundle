/**
 * The only place in the web app that knows the API exists.
 *
 * This file is a transport layer and nothing else. **No business logic may live
 * here or anywhere in apps/web** — the React Native app will call the same
 * endpoints with no privileged access, and logic that creeps in here either
 * cannot be reached from mobile or has to be written twice. That is the most
 * common way "we'll add mobile later" projects rot.
 *
 * The types below are hand-written placeholders. They are replaced by
 * `packages/api-types`, generated from the OpenAPI schema — run `make api-types`
 * with the API up. CI fails the build on drift (ADR-0001).
 */

export function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (envUrl && !envUrl.includes("localhost") && !envUrl.includes("127.0.0.1")) {
      return envUrl;
    }
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export type Difficulty = "beginner" | "intermediate" | "advanced";

/** Content shapes present in a card's `body`, derived server-side from the
 *  markdown itself (never client-guessed) — see content/archetype.py on the
 *  API. A card can carry more than one; rendering picks a priority order for
 *  the collapsed teaser only, the expanded view always shows everything. */
export type ArchetypeTag = "code" | "diagram" | "comparison";

export interface Card {
  id: string;
  topic_id: string;
  subtopic_id: string;
  /** The curriculum slot's title — used as the station label when filtered to one topic. */
  subtopic_title: string;
  difficulty: Difficulty;
  title: string;
  /** The collapsed-state hook — a purpose-written line, not a truncation of body. */
  summary: string;
  body: string;
  archetype: ArchetypeTag[];
  /** At most one true per subtopic (ADR-0017) — the client renders this card
   *  never-collapsed with anchor styling; it does not decide for itself. */
  is_hero: boolean;
  /** ASCII scene reference (ADR-0021), or a model-given label for freehand
   *  art on the free-form generation testing branch. Null for most cards.
   *  Renders at the TOP of the card, above the title, and as the entire
   *  collapsed/preview face when present — see `visual_slots`. */
  visual_id: string | null;
  /** {"art": <raw ascii, newline-separated>, "alt": <one sentence>}, or null
   *  together with `visual_id`. Never markdown — rendered in a dedicated
   *  monospace box, not through the body's Markdown parser. */
  visual_slots: Record<string, string> | null;
  created_at: string;
  /** This user's private note on this card, or null if they never wrote one. */
  note: string | null;
  /** True iff this user has already marked this card SEEN (ADR-0010) —
   *  server-authoritative so collections that re-show the same card across
   *  page loads (saved, liked, notes) don't reset it to unmarked on reload. */
  seen: boolean;
}

export interface Feed {
  cards: Card[];
  next_position: number;
  /** The pool could not satisfy the difficulty mix, so this page is short by design. */
  degraded: boolean;
  /** True end of feed. Show "more coming soon" — never an indefinite spinner. */
  exhausted: boolean;
  /** This page includes a repeat pass — everything at some difficulty has been
   *  shown once and is being served again in a fresh order. */
  recycling: boolean;
}

export interface Topic {
  id: string;
  /** Always this user's own name for the topic (ADR-0004). */
  display_name: string;
  slug: string;
  is_custom: boolean;
  current_difficulty: Difficulty;
  /** 0-359, -1 to opt out of topic color entirely (ADR-0051, follow the
   *  theme's own accent), or null to use the deterministic default
   *  (ADR-0034). Read through `topicHue()`/`explicitTopicHue()`
   *  (`lib/topicColor.ts`), never directly -- the sentinel renders as a real
   *  (red) hue if fed straight into `oklch()`. */
  accent_hue: number | null;
}

export type EngagementKind =
  | "impression"
  | "expand"
  | "collapse"
  | "dwell"
  | "skip"
  | "like"
  | "unlike"
  | "bookmark"
  | "unbookmark"
  | "note"
  | "share"
  | "ask_ai"
  /** User tapped "Got it". A deliberate claim of comprehension. */
  | "explicit_complete"
  /** Dwell threshold passed. Weaker: they may have been making tea. */
  | "dwell_complete";

export interface EngagementEvent {
  /** Client-generated, and the idempotency key. Retries must collide, not inflate. */
  id: string;
  card_id: string;
  kind: EngagementKind;
  dwell_ms?: number;
  client_occurred_at?: string;
  session_id?: string;
}

/** Carries the HTTP status so callers that need to branch on it (409 already
 *  subscribed vs. 403 limit reached, say) don't have to parse the message. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Inject token
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("spoin_access_token");
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  const response = await fetch(`${getBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (response.status === 401 && retry && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    const refreshToken = localStorage.getItem("spoin_refresh_token");
    if (refreshToken) {
      try {
        const refreshResp = await fetch(`${getBaseUrl()}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken })
        });
        if (refreshResp.ok) {
          const data = await refreshResp.json();
          localStorage.setItem("spoin_access_token", data.access_token);
          localStorage.setItem("spoin_refresh_token", data.refresh_token);
          // Retry original request
          return request<T>(path, init, false);
        }
      } catch (e) {}
    }
    // Refresh failed or no refresh token, log out. A hard reload rather than
    // client-side navigation: AuthProvider isn't reachable from this module
    // (it's a transport layer, see the file header), so this is the fallback
    // for a session that expires mid-use, not the normal signed-out path.
    localStorage.removeItem("spoin_access_token");
    localStorage.removeItem("spoin_refresh_token");
    window.location.href = "/signup";
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, detail ?? `${init?.method ?? "GET"} ${path} failed`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  /** null for a guest — see api/routers/auth.py's `_user_out`. */
  email: string | null;
  display_name: string;
  is_guest: boolean;
  onboarding_complete: boolean;
  age?: number | null;
  gender?: string | null;
  avatar_icon?: string | null;
  has_avatar_image?: boolean;
  /** Cards-per-day target. Rides on this payload rather than a separate
   *  preferences fetch — see UserOut in api/schemas.py. */
  daily_card_goal?: number;
  /** Palette, saved themes, font, and imported-font metadata (ADR-0070).
   *  Populated ONLY on `/auth/me` — the payload AuthProvider reads on load,
   *  where the client reconciles its pre-paint `localStorage` cache against
   *  the server. Absent on PATCH /profile/me and avatar responses. */
  preferences?: Preferences;
}

/** One user-saved theme (ADR-0070). The four colours everything else derives
 *  from via `globals.css`'s `[data-palette="custom"]` `color-mix` rules, plus a
 *  name and a client-generated id referenced as `custom:<id>`. */
export interface CustomPalette {
  id: string;
  name: string;
  bg: string;
  fg: string;
  accent: string;
  accent2: string;
}

/** Metadata for an imported font. The bytes are fetched separately from
 *  `GET /profile/me/fonts/{id}` and registered as an `@font-face` client-side. */
export interface ImportedFont {
  id: string;
  name: string;
  format: string;
  byte_size: number;
}

export interface Preferences {
  /** A built-in palette key (`notebook`…) or `custom:<id>`. */
  palette: string;
  custom_palettes: CustomPalette[];
  /** A built-in font key (`literata`…) or `import:<id>`. */
  font: string;
  imported_fonts: ImportedFont[];
}

/** Whole-object replace (PUT), not PATCH — the client always holds the full
 *  picture. Adding/removing a font goes through its own endpoints. */
export interface PreferencesUpdate {
  palette: string;
  custom_palettes: CustomPalette[];
  font: string;
}

export interface Progress {
  topic_id: string;
  current_difficulty: Difficulty;
  /** Coverage of the weakest subtopic in the current tier — the 80% gate. */
  coverage: number;
  /** Latched server-side: once earned it is never recomputed. */
  quiz_unlocked: boolean;
  tier_quiz_passed: boolean[];
  mastered: boolean;
}

export interface TopicDiscover {
  topic_id: string;
  /** canonical_name, not a personal label — see ADR-0015. */
  display_name: string;
  subscriber_count: number;
  /** Always false from `discoverTopics`. Set per-topic from `allTopics`
   *  (ADR-0038) so the modal can grey out Follow on a topic already
   *  followed instead of offering a second subscribe. */
  followed: boolean;
}

export type DiscoverMode = "popular" | "for_you";

export interface TopicRequestResult {
  topic: Topic;
  /** "generating" means a brand-new topic was minted and generation was just
   *  enqueued — no cards yet, could take a while (ADR-0003: free-tier
   *  generation is minutes-to-hours, never synchronous). "subscribed" means
   *  the name matched an existing topic, which may already have cards. */
  status: "subscribed" | "generating";
}

export interface TopicBatchEntry {
  name: string;
  /** 1–2 sentences on what the reader wants from this topic — optional,
   *  threaded to the curriculum/card prompts as context (task 0032). */
  description?: string;
  entryDifficulty?: Difficulty;
}

export interface TopicBatchItemResult {
  /** Index into the submitted entries, so each result pairs back to its
   *  row (ADR-0025's `request_index` convention). */
  request_index: number;
  /** "generating" / "subscribed" — as `TopicRequestResult.status`.
   *  "already_subscribed" — the name resolved to a topic already followed;
   *  nothing minted. "rejected" — failed the word-count rule or the name
   *  validator; `detail` carries the reason for this row. */
  status: "generating" | "subscribed" | "already_subscribed" | "rejected";
  topic: Topic | null;
  detail: string | null;
}

export interface TopicBatchResult {
  results: TopicBatchItemResult[];
}

/** One `(key, model)` cell's daily state (B4, ADR-0003 §6 / ADR-0058). A
 *  configured cell with no ledger row today still appears, `requests_spent: 0`. */
export interface QuotaCell {
  backend: string;
  key_index: number;
  model: string;
  /** "thinking" | "generator" | "other" (a ledger row for a model no longer
   *  in a configured ladder). */
  pool: string;
  requests_spent: number;
  /** The ladder rung's RPD; null if the model isn't in a current ladder. */
  daily_ceiling: number | null;
  /** Set once `requests_spent` hit the ceiling; never reset. */
  exhausted_at: string | null;
  /** A per-minute 429 parked this cell until this time — transient, daily
   *  budget still has room. Distinct from `exhausted_at`. */
  cooldown_until: string | null;
}

export interface ParkedModel {
  model: string;
  excluded_at: string;
  expires_at: string;
  reason: string;
}

/** `GET /admin/quota`. ADR-0065's three terminal conditions stay SEPARATE
 *  counts (`cells_daily_exhausted` / `cells_minute_throttled` / `models_parked`)
 *  — never fold them into one "exhausted". */
export interface QuotaStatus {
  day: string;
  generated_at: string;
  cells: QuotaCell[];
  parked_models: ParkedModel[];
  cells_total: number;
  cells_daily_exhausted: number;
  cells_minute_throttled: number;
  models_parked: number;
}

export interface TopicStats {
  topic_id: string;
  current_difficulty: Difficulty;
  coverage: number;
  quiz_unlocked: boolean;
  mastered: boolean;
  tier_quiz_passed: boolean[];
  likes: number;
  saves: number;
  notes: number;
  shares: number;
}

export interface SubtopicProgress {
  subtopic_id: string;
  title: string;
  difficulty: Difficulty;
  total_cards: number;
  seen_cards: number;
  coverage: number;
  covered: boolean;
}

export interface TopicCurriculum {
  topic_id: string;
  subtopics: SubtopicProgress[];
}

export interface CustomTopicStatus {
  topic_id: string;
  display_name: string;
  slug: string;
  /** null when the requested name matched an existing, already-generated
   *  topic and no job was ever enqueued — nothing to poll for that one. */
  generation_status: "pending" | "running" | "completed" | "failed" | null;
  requested_at: string;
}

export interface GenerationSubtopicProgress {
  subtopic_id: string;
  group_title: string;
  difficulty: Difficulty;
  cards_target: number;
  cards_done: number;
  /** Null until the cards phase has committed for this tier — see the API's
   *  GenerationSubtopicProgressOut docstring. */
  questions_target: number | null;
  questions_done: number;
}

export interface GenerationProgress {
  status: "pending" | "running" | "completed" | "failed";
  stage: "curriculum" | "cards" | "done" | null;
  topic_name: string | null;
  subtopics: GenerationSubtopicProgress[];
  error: string | null;
  /** Crossed ADR-0053's live-coverage threshold -- the same moment this
   *  topic starts appearing in Topics/Discover for users who didn't request
   *  it. A separate, usually-earlier milestone than `status === "completed"`. */
  topic_live: boolean;
}

export interface QuizMcqQuestion {
  question_id: string;
  stem: string;
  /** Never `correct_index` — the client can't grade itself. */
  options: string[];
}

export interface QuizFreeTextQuestion {
  question_id: string;
  stem: string;
}

export interface QuizStart {
  attempt_id: string;
  topic_id: string;
  difficulty: Difficulty;
  kind: "placement" | "promotion" | "mastery";
  mcq: QuizMcqQuestion[];
  free_text: QuizFreeTextQuestion;
}

export interface McqResult {
  question_id: string;
  correct: boolean;
  correct_index: number;
  explanation: string;
}

export interface QuizMcqSubmitResult {
  attempt_id: string;
  results: McqResult[];
  /** Fraction correct, 0-1. Final score isn't known until free text is graded too. */
  mcq_score: number;
}

export interface QuizFreeTextResult {
  question_id: string;
  /** 0-3 rubric level. */
  rubric_level: number;
  correct: boolean;
  justification: string;
}

export interface RemediationCard {
  card_id: string;
  title: string;
  subtopic_title: string;
}

export interface Note {
  card_id: string;
  body: string;
  updated_at: string;
}

/** One row of the "all my notes" view -- the note plus enough card/topic
 *  context to render a full card without a per-note follow-up request. */
export interface NoteWithCard {
  note: Note;
  card: Card;
  /** This user's own name for the card's topic (ADR-0004). */
  topic_name: string;
}

/** One row of the liked collection -- the card the user hearted, the user's
 *  own name for its topic (ADR-0004), and when they liked it for sorting. */
export interface LikedCard {
  card: Card;
  topic_name: string;
  /** ISO 8601 server timestamp from `card_like.created_at`. */
  liked_at: string;
}

/** One row of the saved (bookmarked) collection -- the card the user bookmarked,
 *  the user's own topic name, and when they saved it for sorting. */
export interface SavedCard {
  card: Card;
  topic_name: string;
  /** ISO 8601 server timestamp from `card_bookmark.created_at`. */
  saved_at: string;
}

export interface QuizFreeTextSubmitResult {
  attempt_id: string;
  free_text: QuizFreeTextResult;
  /** Weighted 70% MCQ / 30% free text. */
  score: number;
  passed: boolean;
  /** Empty unless `passed` is false. */
  remediation: RemediationCard[];
  /** True only if this attempt actually advanced the tier or conferred mastery. */
  progressed: boolean;
}

export const api = {
  // -- Auth -----------------------------------------------------------------
  login: (credentials: { email: string; password: string }) =>
    request<AuthTokens>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),

  register: (details: { email: string; password: string; display_name: string }) =>
    request<AuthTokens>("/auth/register", {
      method: "POST",
      body: JSON.stringify(details),
    }),

  /** Mints a fresh anonymous user + token pair — see docs/adr on guest identity. */
  guest: () => request<AuthTokens>("/auth/guest", { method: "POST" }),

  /** Attaches email/password to the CALLER's own guest account in place. */
  claim: (details: { email: string; password: string; display_name: string }) =>
    request<AuthTokens>("/auth/claim", {
      method: "POST",
      body: JSON.stringify(details),
    }),

  googleAuth: (idToken: string) =>
    request<AuthTokens>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    }),

  me: () => request<User>("/auth/me"),

  completeOnboarding: (topics: { topic_id: string; entry_difficulty: Difficulty }[]) =>
    request<Topic[]>("/topics/onboarding/complete", {
      method: "POST",
      body: JSON.stringify({ topics }),
    }),

  // -- Feed -----------------------------------------------------------------
  feed: (position?: number, topics?: string[]) => {
    const query = new URLSearchParams();
    if (position !== undefined) query.set("position", String(position));
    for (const topic of topics ?? []) query.append("topics", topic);
    const suffix = query.toString();
    return request<Feed>(`/feed${suffix === "" ? "" : `?${suffix}`}`);
  },

  topics: () => request<Topic[]>("/topics"),

  progress: (topicId: string) => request<Progress>(`/topics/${topicId}/progress`),

  discoverTopics: (mode: DiscoverMode) =>
    request<TopicDiscover[]>(`/topics/discover?mode=${mode}`),

  allTopics: () => request<TopicDiscover[]>("/topics/all"),

  subscribeTopic: (topicId: string) =>
    request<Topic>(`/topics/${topicId}/subscribe`, { method: "POST" }),

  unsubscribeTopic: (topicId: string) =>
    request<void>(`/topics/${topicId}/subscribe`, { method: "DELETE" }),

  requestTopic: (name: string, entryDifficulty?: Difficulty, description?: string) =>
    request<TopicRequestResult>("/topics", {
      method: "POST",
      body: JSON.stringify({
        name,
        description: description || undefined,
        entry_difficulty: entryDifficulty,
      }),
    }),

  /** Several custom topics in one submission — ADR-0025's batched matcher runs
   *  once for the whole list (task 0032). A partly-rejected batch still
   *  resolves; read each row's `status`/`detail`, don't treat it as a failure. */
  requestTopics: (entries: TopicBatchEntry[]) =>
    request<TopicBatchResult>("/topics/batch", {
      method: "POST",
      body: JSON.stringify({
        items: entries.map((e) => ({
          name: e.name,
          description: e.description || undefined,
          entry_difficulty: e.entryDifficulty,
        })),
      }),
    }),

  topicStats: (topicId: string) => request<TopicStats>(`/topics/${topicId}/stats`),

  topicCurriculum: (topicId: string) => request<TopicCurriculum>(`/topics/${topicId}/curriculum`),

  customTopics: () => request<CustomTopicStatus[]>("/topics/custom"),

  generationProgress: (topicId: string) =>
    request<GenerationProgress>(`/topics/${topicId}/generation-progress`),

  /** Only works while the job is still "pending" (not yet claimed by a
   *  worker) -- 409s otherwise. Removes the job, the caller's own
   *  subscription, and the topic itself if nobody else was following it. */
  cancelGeneration: (topicId: string) =>
    request<void>(`/topics/${topicId}/generation-job`, { method: "DELETE" }),

  setTopicColor: (topicId: string, hue: number | null) =>
    request<Topic>(`/topics/${topicId}/color`, {
      method: "PATCH",
      body: JSON.stringify({ hue }),
    }),

  /** Dev-only (see api/routers/dev.py) — resets this user's progress and
   *  unfollows a couple of topics back to Discover. Returns the refreshed
   *  topic list. */
  resetDemo: () => request<Topic[]>("/dev/reset", { method: "POST" }),

  sendEvents: (events: EngagementEvent[]) =>
    request<{ accepted: number; duplicates: number; rejected: number }>(
      "/engagement/events",
      { method: "POST", body: JSON.stringify({ events }) },
    ),

  startQuiz: (topicId: string, difficulty: Difficulty) =>
    request<QuizStart>(`/topics/${topicId}/quiz/start`, {
      method: "POST",
      body: JSON.stringify({ difficulty }),
    }),

  submitMcq: (attemptId: string, answers: { question_id: string; selected_index: number }[]) =>
    request<QuizMcqSubmitResult>(`/quiz/attempts/${attemptId}/submit-mcq`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  submitFreeText: (attemptId: string, answer: string) =>
    request<QuizFreeTextSubmitResult>(`/quiz/attempts/${attemptId}/submit-free-text`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),

  // -- Notes ------------------------------------------------------------------
  saveNote: (cardId: string, body: string) =>
    request<Note>(`/cards/${cardId}/note`, {
      method: "PUT",
      body: JSON.stringify({ body }),
    }),

  deleteNote: (cardId: string) => request<void>(`/cards/${cardId}/note`, { method: "DELETE" }),

  listNotes: () => request<NoteWithCard[]>("/notes"),

  likedCards: (topicId?: string, sort?: string) => {
    const query = new URLSearchParams();
    if (topicId) query.set("topic_id", topicId);
    if (sort) query.set("sort", sort);
    const suffix = query.toString();
    return request<LikedCard[]>(`/cards/liked${suffix === "" ? "" : `?${suffix}`}`);
  },

  savedCards: (topicId?: string, sort?: string) => {
    const query = new URLSearchParams();
    if (topicId) query.set("topic_id", topicId);
    if (sort) query.set("sort", sort);
    const suffix = query.toString();
    return request<SavedCard[]>(`/cards/saved${suffix === "" ? "" : `?${suffix}`}`);
  },

  getCard: (cardId: string) => request<Card>(`/cards/${cardId}`),

  // --- Profile ---
  getProfileStats: (year: number, month: number) =>
    request<ProfileStatsOut>(`/profile/me/stats?year=${year}&month=${month}`),

  /** Cards read today against the daily goal (ADR-0062). `tzOffsetMinutes`
   *  is `-new Date().getTimezoneOffset()` — local-minus-UTC — so "today" is
   *  the reader's calendar day. */
  today: (tzOffsetMinutes: number) =>
    request<DailyGoal>(`/profile/me/today?tz_offset_minutes=${tzOffsetMinutes}`),
    
  updateProfile: (updates: UserProfileUpdateIn) => 
    request<User>("/profile/me", {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
    
  uploadAvatar: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
  
    const token = localStorage.getItem("spoin_access_token");
    const response = await fetch(`${getBaseUrl()}/profile/me/avatar`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: formData,
    });
  
    if (!response.ok) {
      const detail = await response
        .json()
        .then((body: any) => body.detail)
        .catch(() => undefined);
      throw new ApiError(response.status, detail ?? `POST /profile/me/avatar failed`);
    }
  
    return response.json() as Promise<User>;
  },
  
  deleteAvatar: () =>
    request<User>("/profile/me/avatar", {
      method: "DELETE",
    }),

  // --- Appearance preferences (ADR-0070) ---
  /** Palette + saved themes + font + imported-font metadata. Also embedded on
   *  `/auth/me`; this standalone read is for a manual refetch. */
  getPreferences: () => request<Preferences>("/profile/me/preferences"),

  /** Whole-object replace. A `custom:<id>` palette must be present in
   *  `custom_palettes` and an `import:<id>` font must be one the caller owns —
   *  both are validated server-side (422 otherwise). */
  updatePreferences: (body: PreferencesUpdate) =>
    request<Preferences>("/profile/me/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /** Import a font file. Format is sniffed from magic bytes server-side (not
   *  the multipart type), size capped at 2MB. Returns the new row's metadata. */
  uploadFont: async (file: File, name: string) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    const token = localStorage.getItem("spoin_access_token");
    const response = await fetch(`${getBaseUrl()}/profile/me/fonts`, {
      method: "POST",
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: formData,
    });
    if (!response.ok) {
      const detail = await response
        .json()
        .then((body: { detail?: string }) => body.detail)
        .catch(() => undefined);
      throw new ApiError(response.status, detail ?? "POST /profile/me/fonts failed");
    }
    return response.json() as Promise<ImportedFont>;
  },

  deleteFont: (id: string) =>
    request<void>(`/profile/me/fonts/${id}`, { method: "DELETE" }),

  /** The font bytes as an object URL, for a client `@font-face` `src`. Same
   *  reason as `avatarObjectUrl`: the endpoint is behind a Bearer token, so a
   *  bare `url()` would 401. The caller owns the returned URL and should
   *  `revokeObjectURL` it when the font is removed. */
  fontObjectUrl: async (id: string) => {
    const token = localStorage.getItem("spoin_access_token");
    const response = await fetch(`${getBaseUrl()}/profile/me/fonts/${id}`, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (!response.ok) {
      throw new ApiError(response.status, "Could not load font file");
    }
    return URL.createObjectURL(await response.blob());
  },

  /** The user's own data as JSON (Settings -> Data & Privacy). Serving-layer
   *  read only — no generation. */
  exportData: () => request<ProfileExport>("/profile/me/export"),

  /** The avatar bytes as an object URL.
   *
   * `/profile/me/avatar/image` sits behind `UserDep` -> `HTTPBearer`
   * (api/deps.py), and the access token lives in localStorage, not a cookie.
   * A bare `<img src={...}>` therefore sends no Authorization header and the
   * endpoint 401s -- every uploaded avatar silently failed to render. Fetching
   * it here lets the token ride along on a real request; the caller gets a
   * blob: URL an <img> can use, and MUST revokeObjectURL it when done.
   *
   * Callers are responsible for cache-busting by re-calling after an upload
   * or delete -- deliberately not a `?t=` on the URL, which (evaluated in a
   * render) re-fetched the image on every single re-render. */
  avatarObjectUrl: async () => {
    const token = localStorage.getItem("spoin_access_token");
    const response = await fetch(`${getBaseUrl()}/profile/me/avatar/image`, {
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (!response.ok) {
      throw new ApiError(response.status, "Could not load avatar image");
    }
    return URL.createObjectURL(await response.blob());
  },

  // -- Admin (B4) --
  /** Today's quota-governor state. `env`-gated on the API (404 in production
   *  until task 0035's admin-role gate lands). */
  adminQuota: () => request<QuotaStatus>("/admin/quota"),
};

export interface UserProfileUpdateIn {
  display_name?: string | null;
  age?: number | null;
  gender?: string | null;
  avatar_icon?: string | null;
  daily_card_goal?: number | null;
}

export interface ProfileExport {
  exported_at: string;
  schema_version: number;
  profile: User;
  topics: unknown[];
  notes: unknown[];
  liked_cards: unknown[];
  saved_cards: unknown[];
  daily_activity: DailyActivityOut[];
}

export interface DailyActivityOut {
  date: string;
  cards_read: number;
}

export interface ProfileStatsOut {
  current_streak: number;
  longest_streak: number;
  total_cards_read: number;
  total_topics: number;
  monthly_activity: DailyActivityOut[];
}

/** `GET /profile/me/today` (ADR-0062). `cards_read` is distinct cards
 *  completed within the caller's LOCAL day — the client sends its own UTC
 *  offset so the ring resets at the reader's midnight, not UTC's. */
export interface DailyGoal {
  cards_read: number;
  goal: number;
}
