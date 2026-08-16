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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }

  return (await response.json()) as T;
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

export const api = {
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
};
