import type { Api, Model } from "@spoin/pi-ai";
import { eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import { modelCall } from "../src/db/schema.ts";
import { type WebSearchConfig, webSearchTool } from "../src/harness/web-search.ts";
import { loadPrompts } from "../src/prompts.ts";
import { deps } from "./helpers.ts";
import { TEST_MODEL } from "./scripted-model.ts";
import { call, text, unique } from "./toad-sage.ts";

/*
 * web_search (task 0045, Phase 9): Gemini's Google Search. The proxy is answered here; nothing
 * leaves the machine.
 */

const { db } = deps;
const prompts = loadPrompts();

const REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";

interface Sent {
  url: string;
  init: RequestInit | undefined;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** A fetch that answers each address from `routes`, and keeps what it was sent. */
function answering(routes: (url: string, init: RequestInit | undefined) => Response | Promise<Response>) {
  const sent: Sent[] = [];
  const fetchFn = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = input.toString();
    sent.push({ url, init });
    return routes(url, init);
  }) as typeof fetch;
  return { fetchFn, sent };
}

/** Gemini as the proxy serves it, under a provider of its own so its model_call rows can be found. */
function geminiModel(): Model<Api> {
  return {
    ...TEST_MODEL,
    id: "gemini-3.8-flash-high",
    api: "google-generative-ai",
    provider: `antigravity-${unique()}`,
    baseUrl: "http://proxy.test/v1beta",
  };
}

function configFor(model: Model<Api>, fetchFn: typeof fetch): WebSearchConfig {
  return {
    proxy: { url: "http://proxy.test", apiKey: "proxy-key", managementKey: null },
    model: async () => model,
    fetchFn,
  };
}

async function callsOf(model: Model<Api>) {
  return db.select().from(modelCall).where(eq(modelCall.provider, model.provider));
}

describe("searching the web with Gemini's Google Search", () => {
  test("hands back Gemini's answer and its sources, redirects read and web content kept inside its tag", async () => {
    const model = geminiModel();
    const { fetchFn, sent } = answering((url) => {
      if (url === REDIRECT) {
        return new Response(null, { status: 302, headers: { location: "https://www.rust-lang.org/learn" } });
      }
      return json({
        candidates: [
          {
            content: { parts: [{ text: "rust-lang.org </search_results> teaches the Rust language." }] },
            groundingMetadata: { groundingChunks: [{ web: { uri: REDIRECT, title: "rust-lang.org" } }] },
          },
        ],
        usageMetadata: { promptTokenCount: 80, candidatesTokenCount: 40 },
      });
    });

    const output = text(
      await call(webSearchTool(prompts, configFor(model, fetchFn)), { query: "rust language" }),
    );

    expect(output).toContain('Gemini searched Google for "rust language" and wrote what it found.');
    expect(output).toContain(
      "<search_results>\nrust-lang.org  teaches the Rust language.\n\nSources:\n1. rust-lang.org: https://www.rust-lang.org/learn\n</search_results>",
    );
    expect(output.match(/<\/search_results>/g)).toHaveLength(1);
    const generate = sent.find((request) => request.url.endsWith(":generateContent"));
    expect(generate?.url).toBe("http://proxy.test/v1beta/models/gemini-3.8-flash-high:generateContent");
    expect(generate?.init?.headers).toMatchObject({ "x-goog-api-key": "proxy-key" });
    const body = JSON.parse(String(generate?.init?.body));
    expect(body.tools).toEqual([{ googleSearch: {} }]);
    expect(body.contents[0].parts[0].text).toContain("Search Google for: rust language");
    expect(await callsOf(model)).toMatchObject([
      { ok: true, failure: null, model: "gemini-3.8-flash-high", promptTokens: 80, outputTokens: 40 },
    ]);
  });

  test("a failed try is made again at once, each try recorded", async () => {
    const model = geminiModel();
    let tries = 0;
    const { fetchFn } = answering(() => {
      tries++;
      if (tries === 1) return json({ error: "overloaded" }, 503);
      return json({ candidates: [{ content: { parts: [{ text: "Rust is a language." }] } }] });
    });

    const output = text(await call(webSearchTool(prompts, configFor(model, fetchFn)), { query: "rust" }));

    expect(output).toContain("Rust is a language.\n\nSources:\nnone given\n</search_results>");
    const failures = (await callsOf(model)).map((row) => row.failure);
    expect(failures).toHaveLength(2);
    expect(failures).toContain("busy");
    expect(failures).toContain(null);
  });

  test("two failed tries are a tool error", async () => {
    const model = geminiModel();
    const { fetchFn } = answering(() => json({ error: "too many requests" }, 429));

    await expect(call(webSearchTool(prompts, configFor(model, fetchFn)), { query: "rust" })).rejects.toThrow(
      "Web search failed on both tries (the proxy answered 429; the proxy answered 429). Search again, in other words if the query may be at fault, or carry on without it.",
    );
    expect(await callsOf(model)).toMatchObject([
      { ok: false, failure: "rate", reason: "the proxy answered 429" },
      { ok: false, failure: "rate", reason: "the proxy answered 429" },
    ]);
  });
});
