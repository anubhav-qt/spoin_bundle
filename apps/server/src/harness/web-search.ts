import type { Api, Model } from "@spoin/pi-ai";
import type { ModelCallFailure } from "@spoin/shared/enums";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import { modelCall } from "../db/schema.ts";
import { kindOf } from "../models/calls.ts";
import { GEMINI_THINKING, type ProxyConfig } from "../models/proxy.ts";
import type { Prompts } from "../prompts.ts";
import { checkValue } from "./check.ts";
import { indiaTime } from "./india-time.ts";
import { withoutTag } from "./prompt-tags.ts";
import { CLOSED } from "./schemas.ts";
import { type HarnessTool, ToolError } from "./tools.ts";

/**
 * Searching the web (harness-tools.md, task 0045): Gemini's Google Search, in a call of its own, as
 * googleSearch can't share a request with function tools (model-numbers.md). Google turns away a
 * plain HTTP search, SearXNG's included, so Gemini is the way to its results.
 */

/** The tag the answer is wrapped in: web content, which no one in spoin wrote. */
const TAG = "search_results";

export interface WebSearchConfig {
  proxy: ProxyConfig;
  model: () => Promise<Model<Api>>;
  /** Tests answer in the proxy's place. */
  fetchFn?: typeof fetch;
}

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
      const found = await searchWithGemini(config, prompts, params.query, {
        db: context.db,
        runId: context.run.id,
        signal: context.signal,
        fetchFn: config.fetchFn ?? fetch,
      });
      if (found.failed !== undefined) {
        throw new ToolError(
          `Web search failed (${found.failed}). Carry on without it, or search again later.`,
        );
      }
      return {
        value: prompts.render("tool-results/web-search.njk", {
          query: params.query,
          answer: found.answer,
          sources: found.sources,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
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
  config: WebSearchConfig,
  prompts: Prompts,
  query: string,
  context: CallContext,
): Promise<GeminiSearch> {
  let model: Model<Api>;
  try {
    model = await config.model();
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
      headers: { "Content-Type": "application/json", "x-goog-api-key": config.proxy.apiKey },
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
