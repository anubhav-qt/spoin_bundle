/**
 * The only place in the web app that knows the API exists.
 *
 * This file is a transport layer and nothing else. **No business logic may live
 * here or anywhere in apps/web** — the React Native app will call the same
 * endpoints with no privileged access, and logic that creeps in here either
 * cannot be reached from mobile or has to be written twice. That is the most
 * common way "we'll add mobile later" projects rot.
 *
 * The wire types are `@spoin/shared`'s, the contract the server validates
 * against and generates its OpenAPI document from (ADR-0106). The names below
 * are this app's names for those same types; never hand-write one.
 *
 * Accounts are Better Auth's (`/auth/*`), reached through its client. A
 * session is one bearer token, read from the `set-auth-token` header of the
 * sign-in that opened it. There is no refresh token: a session lasts 90 days
 * and is extended as it is used.
 */

import type {
  AskConversationOut,
  AskEventOut,
  AskMessageOut,
  AsciiSceneActionOut,
  AsciiSceneOut,
  CardOut,
  CardReportReason,
  ClaimIn,
  CustomTopicStatusOut,
  DailyGoalOut,
  Difficulty,
  EngagementAck,
  EngagementEventIn,
  FeedOut,
  GenerationProgressOut,
  GenerationSubtopicProgressOut,
  ImportedFontOut,
  LikedCardOut,
  McqResultOut,
  NoteOut,
  NoteWithCardOut,
  PreferencesOut,
  PreferencesUpdateIn,
  ProfileExportOut,
  ProfileStatsOut,
  ProgressOut,
  QuizFreeTextQuestionOut,
  QuizFreeTextResultOut,
  QuizMcqQuestionOut,
  QuizStartOut,
  QuizSubmitFreeTextOut,
  QuizSubmitMcqOut,
  RemediationCardOut,
  RepairAttemptOut,
  RepairCardOut,
  RepairEnqueuedOut,
  RepairQueueItemOut,
  RepairReportOut,
  SavedCardOut,
  SubtopicProgressOut,
  TopicBatchItemOut,
  TopicBatchOut,
  TopicCurriculumOut,
  TopicDiscoverOut,
  TopicOut,
  TopicRequestOut,
  TopicStatsOut,
  UserOut,
  UserProfileUpdateIn,
} from "@spoin/shared";
import { createAuthClient } from "better-auth/client";
import { anonymousClient } from "better-auth/client/plugins";

export type {
  CardReportReason,
  CustomPalette,
  DailyActivityOut,
  Difficulty,
  EngagementKind,
  ProfileStatsOut,
  UserProfileUpdateIn,
  VisualKind,
} from "@spoin/shared";
export type { TopicScope } from "@spoin/shared/enums";

export type Card = CardOut;
export type Feed = FeedOut;
export type Topic = TopicOut;
export type EngagementEvent = EngagementEventIn;
export type User = UserOut;
export type ImportedFont = ImportedFontOut;
export type Preferences = PreferencesOut;
export type PreferencesUpdate = PreferencesUpdateIn;
export type Progress = ProgressOut;
export type TopicDiscover = TopicDiscoverOut;
export type TopicRequestResult = TopicRequestOut;
export type TopicBatchItemResult = TopicBatchItemOut;
export type TopicBatchResult = TopicBatchOut;
export type TopicStats = TopicStatsOut;
export type SubtopicProgress = SubtopicProgressOut;
export type TopicCurriculum = TopicCurriculumOut;
export type CustomTopicStatus = CustomTopicStatusOut;
export type GenerationSubtopicProgress = GenerationSubtopicProgressOut;
export type GenerationProgress = GenerationProgressOut;
export type QuizMcqQuestion = QuizMcqQuestionOut;
export type QuizFreeTextQuestion = QuizFreeTextQuestionOut;
export type QuizStart = QuizStartOut;
export type McqResult = McqResultOut;
export type QuizMcqSubmitResult = QuizSubmitMcqOut;
export type QuizFreeTextResult = QuizFreeTextResultOut;
export type QuizFreeTextSubmitResult = QuizSubmitFreeTextOut;
export type RemediationCard = RemediationCardOut;
export type Note = NoteOut;
export type NoteWithCard = NoteWithCardOut;
export type LikedCard = LikedCardOut;
export type SavedCard = SavedCardOut;
export type ProfileExport = ProfileExportOut;
export type DailyGoal = DailyGoalOut;
export type AskMessage = AskMessageOut;
export type AskConversation = AskConversationOut;
/** One SSE event from `POST /topics/{id}/ask`. */
export type AskEvent = AskEventOut;
export type RepairCard = RepairCardOut;
export type RepairReport = RepairReportOut;
export type RepairAttempt = RepairAttemptOut;
export type RepairQueueItem = RepairQueueItemOut;
export type RepairEnqueued = RepairEnqueuedOut;
export type AsciiScene = AsciiSceneOut;
export type AsciiSceneAction = AsciiSceneActionOut;

/** The content shapes the collapsed teaser knows how to render. `Card.archetype`
 *  is derived server-side from the body (ADR-0017); a tag outside this list
 *  renders as a plain card. */
export type ArchetypeTag = "code" | "diagram" | "comparison";

export type DiscoverMode = "popular" | "for_you";

export interface TopicBatchEntry {
  name: string;
  /** 1–2 sentences on what the reader wants from this topic — optional,
   *  threaded to the curriculum as context (task 0032). */
  description?: string;
  entryDifficulty?: Difficulty;
}

/** The API when nothing configures it: the Hono stack's port (infra/compose.yml). */
const DEFAULT_API_BASE_URL = "http://localhost:8001";

export function getBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
  if (typeof window === "undefined") return configured;
  const url = new URL(configured);
  // A localhost API means "the machine serving this page". On a phone reaching
  // the dev server over the LAN, localhost is the phone, so the page's own host
  // stands in for it and the configured port is kept.
  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
    url.hostname = window.location.hostname;
  }
  return url.origin;
}

// -- The session --------------------------------------------------------------

const SESSION_KEY = "spoin_session_token";

function sessionToken(): string | null {
  return typeof window === "undefined" ? null : localStorage.getItem(SESSION_KEY);
}

export function hasSession(): boolean {
  return sessionToken() !== null;
}

/** Forgets the session on this device only; `api.signOut` also ends it on the server. */
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

function authHeaders(): Record<string, string> {
  const token = sessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function makeAuthClient() {
  return createAuthClient({
    baseURL: getBaseUrl(),
    basePath: "/auth",
    plugins: [anonymousClient()],
    fetchOptions: {
      // Bearer only. A cookie sent along would make Better Auth treat the
      // request as a cookie session, and the API doesn't allow credentials.
      credentials: "omit",
      auth: { type: "Bearer", token: () => sessionToken() ?? undefined },
      onSuccess: ({ response }) => {
        const token = response.headers.get("set-auth-token");
        if (token) localStorage.setItem(SESSION_KEY, token);
      },
    },
  });
}

let authClient: ReturnType<typeof makeAuthClient> | null = null;

/** Made on first use, in the browser: the base URL depends on the page's host. */
function auth() {
  authClient ??= makeAuthClient();
  return authClient;
}

/** Better Auth answers `{data, error}` rather than throwing; this makes its errors ours. */
async function settled(
  call: Promise<{ error: { status: number; message?: string; code?: string } | null }>,
): Promise<void> {
  const { error } = await call;
  if (error) throw new ApiError(error.status, error.message ?? "Request failed", error.code);
}

// -- Requests -----------------------------------------------------------------

/** Carries the HTTP status so callers that need to branch on it (409 already
 *  subscribed vs. 403 limit reached, say) don't have to parse the message.
 *  `code` is Better Auth's error code, on its endpoints only. */
export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function failure(response: Response, fallback: string): Promise<ApiError> {
  const detail = await response
    .json()
    .then((body: { detail?: string }) => body.detail)
    .catch(() => undefined);
  return new ApiError(response.status, detail ?? fallback);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  for (const [name, value] of Object.entries(authHeaders())) headers.set(name, value);

  const response = await fetch(`${getBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (response.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    // The session is over: expired, or signed out somewhere else. A hard
    // reload rather than client-side navigation: AuthProvider isn't reachable
    // from this module (it's a transport layer, see the file header), so this
    // is the fallback for a session that ends mid-use, not the normal
    // signed-out path.
    clearSession();
    window.location.href = "/signup";
  }

  if (!response.ok) {
    throw await failure(response, `${init?.method ?? "GET"} ${path} failed`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
    cache: "no-store",
  });
  if (!response.ok) {
    throw await failure(response, `POST ${path} failed`);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** A protected file as an object URL. A bare `<img src>` or `url()` sends no
 *  Authorization header and would 401, since the token lives in localStorage,
 *  not a cookie. The caller owns the URL and MUST `revokeObjectURL` it. */
async function objectUrl(path: string, what: string): Promise<string> {
  const response = await fetch(`${getBaseUrl()}${path}`, { headers: authHeaders() });
  if (!response.ok) {
    throw new ApiError(response.status, `Could not load ${what}`);
  }
  return URL.createObjectURL(await response.blob());
}

export const api = {
  // -- Auth -----------------------------------------------------------------
  // Each sign-in stores the session token it is answered with.
  signIn: (credentials: { email: string; password: string }) =>
    settled(auth().signIn.email(credentials)),

  signUp: (details: { email: string; password: string; display_name: string }) =>
    settled(
      auth().signUp.email({
        email: details.email,
        password: details.password,
        name: details.display_name,
      }),
    ),

  /** A guest is a real, anonymous user from the first card (ADR-0033). */
  guest: () => settled(auth().signIn.anonymous()),

  /** An ID token from the page's own Google Sign-In; the API never runs the
   *  redirect flow itself. */
  googleSignIn: (idToken: string) =>
    settled(auth().signIn.social({ provider: "google", idToken: { token: idToken } })),

  /** Ends the session on the server too. The token is forgotten here at once,
   *  whatever the server says, so it rides along explicitly: the client reads
   *  its own token only after an await. */
  signOut: async () => {
    const headers = authHeaders();
    clearSession();
    await settled(auth().signOut({ fetchOptions: { headers } }));
  },

  /** The caller's own guest account gains an email and password in place
   *  (ADR-0033): same user, same session. */
  claim: (details: ClaimIn) =>
    request<User>("/auth/claim", {
      method: "POST",
      body: JSON.stringify(details),
    }),

  /** The same with Google. A 409 means that Google account, or its email,
   *  already has a Spoin account: sign in with it instead. */
  claimGoogle: (idToken: string) =>
    request<User>("/auth/claim/google", {
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

  /** Several custom topics in one submission (task 0032). A partly-rejected
   *  batch still resolves; read each row's `status`/`detail`, don't treat it
   *  as a failure. */
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

  /** Only works while the job is still "pending" -- 409s otherwise. Removes
   *  the job, the caller's own subscription, and the topic itself if nobody
   *  else was following it. */
  cancelGeneration: (topicId: string) =>
    request<void>(`/topics/${topicId}/generation-job`, { method: "DELETE" }),

  setTopicColor: (topicId: string, hue: number | null) =>
    request<Topic>(`/topics/${topicId}/color`, {
      method: "PATCH",
      body: JSON.stringify({ hue }),
    }),

  /** Dev-only (the server's `DEV_ROUTES`) — resets this user's progress and
   *  unfollows a couple of topics back to Discover. Returns the refreshed
   *  topic list. */
  resetDemo: () => request<Topic[]>("/dev/reset", { method: "POST" }),

  sendEvents: (events: EngagementEvent[]) =>
    request<EngagementAck>("/engagement/events", {
      method: "POST",
      body: JSON.stringify({ events }),
    }),

  /** `difficulty` picks the tier on a topic with tiers. A tierless topic has
   *  one quiz, so it is left out there. */
  startQuiz: (topicId: string, difficulty?: Difficulty) =>
    request<QuizStart>(`/topics/${topicId}/quiz/start`, {
      method: "POST",
      body: JSON.stringify(difficulty === undefined ? {} : { difficulty }),
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

  uploadAvatar: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm<User>("/profile/me/avatar", form);
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
  uploadFont: (file: File, name: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    return requestForm<ImportedFont>("/profile/me/fonts", form);
  },

  deleteFont: (id: string) =>
    request<void>(`/profile/me/fonts/${id}`, { method: "DELETE" }),

  /** The font bytes as an object URL, for a client `@font-face` `src`. Revoke
   *  it when the font is removed. */
  fontObjectUrl: (id: string) => objectUrl(`/profile/me/fonts/${id}`, "font file"),

  /** The user's own data as JSON (Settings -> Data & Privacy). Serving-layer
   *  read only — no generation. */
  exportData: () => request<ProfileExport>("/profile/me/export"),

  /** The avatar bytes as an object URL.
   *
   * Callers are responsible for cache-busting by re-calling after an upload
   * or delete -- deliberately not a `?t=` on the URL, which (evaluated in a
   * render) re-fetched the image on every single re-render. */
  avatarObjectUrl: () => objectUrl("/profile/me/avatar/image", "avatar image"),

  // -- Report a card (B14 / ADR-0076) --------------------------------------
  /** Flag a live card as structurally broken. Idempotent per user+card. */
  reportCard: (cardId: string, body: { reason: CardReportReason; note?: string | null }) =>
    request<void>(`/cards/${cardId}/report`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // -- AskAI (B12/13 / ADR-0077, revised) --------------------------------
  ask: {
    /** The active topic conversation's messages + today's turn budget. */
    conversation: (topicId: string) =>
      request<AskConversation>(`/topics/${topicId}/ask`),
    /** Archive the active conversation; the next question opens a fresh one. */
    reset: (topicId: string) =>
      request<void>(`/topics/${topicId}/ask/reset`, { method: "POST" }),
  },

  // -- Admin: card repair queue (B14) ------------------------------------
  adminRepairs: {
    list: () => request<RepairQueueItem[]>("/admin/repairs"),
    delete: (cardId: string) =>
      request<RepairEnqueued>(`/admin/repairs/${cardId}/delete`, { method: "POST" }),
    dismiss: (cardId: string) =>
      request<RepairEnqueued>(`/admin/repairs/${cardId}/dismiss`, { method: "POST" }),
    revert: (cardId: string) =>
      request<RepairEnqueued>(`/admin/repairs/${cardId}/revert`, { method: "POST" }),
    fix: (cardId: string, image: Blob, guidance?: string) => {
      const form = new FormData();
      form.append("file", image, "card.png");
      if (guidance && guidance.trim()) form.append("guidance", guidance.trim());
      return requestForm<RepairEnqueued>(`/admin/repairs/${cardId}/fix`, form);
    },
    remake: (cardId: string, instructions: string, image?: Blob | null) => {
      const form = new FormData();
      form.append("instructions", instructions.trim());
      if (image) form.append("file", image, "card.png");
      return requestForm<RepairEnqueued>(`/admin/repairs/${cardId}/remake`, form);
    },
  },

  // -- Admin: ASCII scene review (ADR-0104) -------------------------------
  adminAscii: {
    list: (topicSlug: string) =>
      request<AsciiScene[]>(`/admin/ascii/${encodeURIComponent(topicSlug)}`),
    keep: (cardId: string, art: string, alt: string) =>
      request<AsciiSceneAction>(`/admin/ascii/scene/${cardId}/keep`, {
        method: "POST",
        body: JSON.stringify({ art, alt }),
      }),
    reject: (cardId: string, note?: string) =>
      request<AsciiSceneAction>(`/admin/ascii/scene/${cardId}/reject`, {
        method: "POST",
        body: JSON.stringify({ note: note ?? null }),
      }),
  },
};

/** Stream an AskAI turn. Yields parsed SSE events until the stream closes.
 *  A network/HTTP failure yields a single synthetic `error` event rather
 *  than throwing, so the caller has one code path. */
export async function* askStream(
  topicId: string,
  body: { question: string; card_id?: string | null },
): AsyncGenerator<AskEvent> {
  let response: Response;
  try {
    response = await fetch(`${getBaseUrl()}/topics/${topicId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    yield { event: "error", cause: "network" };
    return;
  }
  if (!response.ok || !response.body) {
    yield { event: "error", cause: `http_${response.status}` };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let ev = "";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!ev) continue;
      const payload = data ? JSON.parse(data) : {};
      yield { event: ev, ...payload } as AskEvent;
    }
  }
}
