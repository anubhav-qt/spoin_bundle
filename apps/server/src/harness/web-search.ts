import type { Api, Model } from "@spoin/pi-ai";
import type { ModelCallFailure } from "@spoin/shared/enums";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import { modelCall } from "../db/schema.ts";
import { log } from "../log.ts";
import { kindOf } from "../models/calls.ts";
import { GEMINI_THINKING, type ProxyConfig } from "../models/proxy.ts";
import type { Prompts } from "../prompts.ts";
import { checkValue } from "./check.ts";
import { indiaTime } from "./india-time.ts";
import { CLOSED } from "./schemas.ts";
import { type HarnessTool, ToolError } from "./tools.ts";
import { withoutTag } from "./untrusted.ts";

/**
 * Searching the web (harness-tools.md, task 0045): Google, through spoin's own SearXNG. When Google
 * can't be reached that way, Gemini searches Google instead and writes what it found, in a call of
 * its own: its googleSearch can't share a request with function tools (model-numbers.md).
 */

/** How many results a search hands back: SearXNG's first page. */
const RESULTS = 10;

/** The tag the results are wrapped in: web content, which no one in spoin wrote. */
const TAG = "search_results";

export interface WebSearchConfig {
  /** SearXNG's address, without a trailing slash. */
  searxngUrl: string;
  /** Gemini through the proxy, for when SearXNG is down; null in a process without the proxy. */
  gemini: { proxy: ProxyConfig; model: () => Promise<Model<Api>> } | null;
  /** Tests answer in SearXNG's and Gemini's place. */
  fetchFn?: typeof fetch;
}

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  date: string | null;
}

/** The fields of SearXNG's JSON the tool reads. */
const SearxngAnswer = Type.Object({
  results: Type.Array(
    Type.Object({
      url: Type.String(),
      title: Type.String(),
      content: Type.Optional(Type.String()),
      publishedDate: Type.Optional(Type.Union([Type.String(), Type.Null()])),
    }),
  ),
  /** Each engine that failed, with why: `["google", "CAPTCHA"]`. */
  unresponsive_engines: Type.Array(Type.Array(Type.String())),
});

/** The fields of Gemini's generateContent answer the tool reads. */
const GeminiAnswer = Type.Object({
  candidates: Type.Optional(
    Type.Array(
      Type.Object({
        content: Type.Optional(
          Type.Object({
            parts: Type.Optional(Type.Array(Type.Object({ text: Type.Optional(Type.String()) }))),
          }),
        ),
        groundingMetadata: Type.Optional(
          Type.Object({
            groundingChunks: Type.Optional(
              Type.Array(
                Type.Object({
                  web: Type.Optional(
                    Type.Object({ uri: Type.String(), title: Type.Optional(Type.String()) }),
                  ),
                }),
              ),
            ),
          }),
        ),
      }),
    ),
  ),
  usageMetadata: Type.Optional(
    Type.Object({
      promptTokenCount: Type.Optional(Type.Number()),
      candidatesTokenCount: Type.Optional(Type.Number()),
    }),
  ),
});

const WebSearchParameters = Type.Object(
  { query: Type.String({ minLength: 1, description: "What to search Google for" }) },
  CLOSED,
);

export function webSearchTool(
  prompts: Prompts,
  config: WebSearchConfig,
): HarnessTool<typeof WebSearchParameters> {
  return {
    name: "web_search",
    label: "Search the web",
    description: prompts.render("tools/web-search.njk", {}),
    parameters: WebSearchParameters,
    kind: "read",
    async execute(params, context) {
      const google = await searchGoogle(config, params.query, context.signal);
      if (google.results) {
        return {
          value: prompts.render("tool-results/web-search.njk", {
            by: "google",
            query: params.query,
            results: google.results,
          }),
          dataSeen: [],
          recordsWritten: [],
        };
      }

      log.warn({ reason: google.down }, "web search fell back to Gemini");
      if (!config.gemini) {
        throw new ToolError(
          `Web search is down (${google.down}). Carry on without it, or search again later.`,
        );
      }
      const gemini = await searchWithGemini(config.gemini, prompts, params.query, {
        db: context.db,
        runId: context.run.id,
        signal: context.signal,
        fetchFn: config.fetchFn ?? fetch,
      });
      if (gemini.failed !== undefined) {
        throw new ToolError(
          `Web search is down (${google.down}), and Gemini's Google Search failed too (${gemini.failed}). Carry on without it, or search again later.`,
        );
      }
      return {
        value: prompts.render("tool-results/web-search.njk", {
          by: "gemini",
          query: params.query,
          answer: gemini.answer,
          sources: gemini.sources,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

type GoogleSearch = { results: SearchResult[]; down?: undefined } | { results?: undefined; down: string };

/** Google through SearXNG, or why Google couldn't be reached that way. */
async function searchGoogle(
  config: WebSearchConfig,
  query: string,
  signal: AbortSignal,
): Promise<GoogleSearch> {
  const fetchFn = config.fetchFn ?? fetch;
  const url = `${config.searxngUrl}/search?${new URLSearchParams({ q: query, format: "json" })}`;
  let response: Response;
  try {
    response = await fetchFn(url, { signal });
  } catch (error) {
    if (signal.aborted) throw error;
    return { down: `SearXNG isn't answering at ${config.searxngUrl}` };
  }
  if (!response.ok) return { down: `SearXNG answered ${response.status}` };
  const answer = checkValue(SearxngAnswer, await response.json(), "SearXNG's answer");

  const results = answer.results.slice(0, RESULTS).map((result) => {
    let date: string | null = null;
    if (result.publishedDate) date = result.publishedDate.slice(0, 10);
    return {
      title: withoutTag(result.title, TAG),
      url: withoutTag(result.url, TAG),
      snippet: withoutTag(result.content ?? "", TAG),
      date,
    };
  });
  // Google turning SearXNG away (a CAPTCHA, a rate limit) leaves no results and says so here.
  if (results.length === 0 && answer.unresponsive_engines.length > 0) {
    const reasons = answer.unresponsive_engines.map((engine) => engine.join(": ")).join("; ");
    return { down: `Google didn't answer SearXNG: ${reasons}` };
  }
  return { results };
}

type GeminiSearch =
  | { answer: string; sources: { title: string; url: string }[]; failed?: undefined }
  | { answer?: undefined; sources?: undefined; failed: string };

interface CallContext {
  db: Db;
  runId: string;
  signal: AbortSignal;
  fetchFn: typeof fetch;
}

/** One generateContent call with googleSearch as its only tool, written to model_call like every Gemini call. */
async function searchWithGemini(
  gemini: NonNullable<WebSearchConfig["gemini"]>,
  prompts: Prompts,
  query: string,
  context: CallContext,
): Promise<GeminiSearch> {
  let model: Model<Api>;
  try {
    model = await gemini.model();
  } catch (error) {
    let reason = String(error);
    if (error instanceof Error) reason = error.message;
    return { failed: reason };
  }
  const startedAt = new Date();
  const text = prompts.render("web-search-gemini.njk", { query, today: indiaTime(startedAt) });
  const body = {
    contents: [{ role: "user", parts: [{ text }] }],
    tools: [{ googleSearch: {} }],
    generationConfig: { thinkingConfig: { thinkingLevel: GEMINI_THINKING.toUpperCase() } },
  };
  const call = { db: context.db, runId: context.runId, model, startedAt };

  let response: Response;
  try {
    response = await context.fetchFn(`${model.baseUrl}/models/${model.id}:generateContent`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": gemini.proxy.apiKey },
      body: JSON.stringify(body),
      signal: context.signal,
    });
  } catch (error) {
    if (context.signal.aborted) throw error;
    const reason = "the proxy isn't answering";
    await recordCall(call, { failure: "busy", reason });
    return { failed: reason };
  }
  if (!response.ok) {
    const reason = `the proxy answered ${response.status}`;
    await recordCall(call, { failure: kindOf(response.status), reason });
    return { failed: reason };
  }

  const answered = checkValue(GeminiAnswer, await response.json(), "Gemini's answer");
  const usage = {
    prompt: answered.usageMetadata?.promptTokenCount,
    output: answered.usageMetadata?.candidatesTokenCount,
  };
  const [candidate] = answered.candidates ?? [];
  const parts = candidate?.content?.parts ?? [];
  const answer = parts.map((part) => part.text ?? "").join("");
  if (!answer.trim()) {
    const reason = "Gemini answered with no text";
    await recordCall(call, { failure: "empty", reason, usage });
    return { failed: reason };
  }
  await recordCall(call, { failure: null, reason: null, usage });

  const chunks = candidate?.groundingMetadata?.groundingChunks ?? [];
  const sources: { title: string; url: string }[] = [];
  for (const chunk of chunks) {
    if (!chunk.web) continue;
    const url = await realUrl(chunk.web.uri, context);
    sources.push({ title: withoutTag(chunk.web.title ?? url, TAG), url: withoutTag(url, TAG) });
  }
  return { answer: withoutTag(answer, TAG), sources };
}

/**
 * Where a grounding link leads. Gemini's sources are Google redirect links, and the page they open
 * is the one the agent fetches and the page store keys by, so the redirect is read without
 * following it. A link that won't say still leads there.
 */
async function realUrl(uri: string, context: CallContext): Promise<string> {
  try {
    const response = await context.fetchFn(uri, {
      method: "HEAD",
      redirect: "manual",
      signal: context.signal,
    });
    const location = response.headers.get("location");
    if (location) return location;
  } catch (error) {
    if (context.signal.aborted) throw error;
  }
  return uri;
}

async function recordCall(
  call: { db: Db; runId: string; model: Model<Api>; startedAt: Date },
  outcome: {
    failure: ModelCallFailure | null;
    reason: string | null;
    usage?: { prompt: number | undefined; output: number | undefined };
  },
): Promise<void> {
  await call.db.insert(modelCall).values({
    runId: call.runId,
    startedAt: call.startedAt,
    provider: call.model.provider,
    model: call.model.id,
    ok: outcome.failure === null,
    failure: outcome.failure,
    reason: outcome.reason,
    firstTokenMs: null,
    totalMs: Date.now() - call.startedAt.getTime(),
    promptTokens: outcome.usage?.prompt ?? null,
    outputTokens: outcome.usage?.output ?? null,
  });
}
