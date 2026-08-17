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

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  created_at: string;
}

export interface Feed {
  cards: Card[];
  next_position: number;
  /** The pool could not satisfy the difficulty mix, so this page is short by design. */
  degraded: boolean;
  /** True end of feed. Show "more coming soon" — never an indefinite spinner. */
  exhausted: boolean;
}

export interface Topic {
  id: string;
  /** Always this user's own name for the topic (ADR-0004). */
  display_name: string;
  slug: string;
  is_custom: boolean;
  current_difficulty: Difficulty;
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

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (response.status === 401 && retry && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    const refreshToken = localStorage.getItem("spoin_refresh_token");
    if (refreshToken) {
      try {
        const refreshResp = await fetch(`${BASE_URL}/auth/refresh`, {
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
    // Refresh failed or no refresh token, log out
    localStorage.removeItem("spoin_access_token");
    localStorage.removeItem("spoin_refresh_token");
    window.location.href = "/login";
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, detail ?? `${init?.method ?? "GET"} ${path} failed`);
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

  completeOnboarding: (topicIds: string[], entryDifficulty: Difficulty) =>
    request<Topic[]>("/topics/onboarding/complete", {
      method: "POST",
      body: JSON.stringify({ topic_ids: topicIds, entry_difficulty: entryDifficulty }),
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

  subscribeTopic: (topicId: string) =>
    request<Topic>(`/topics/${topicId}/subscribe`, { method: "POST" }),

  requestTopic: (name: string, description?: string) =>
    request<TopicRequestResult>("/topics", {
      method: "POST",
      body: JSON.stringify({ name, description: description || undefined }),
    }),

  topicStats: (topicId: string) => request<TopicStats>(`/topics/${topicId}/stats`),

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
};
