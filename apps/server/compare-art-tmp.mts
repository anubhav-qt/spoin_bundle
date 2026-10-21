/*
 * The art model comparison (2026-10-14, the owner's ask): the same 5 cards drawn by each model as
 * designer_toad, with its real prompt, its real code checks and its real phone render, each model
 * judging its own screenshots and attaching what it picks. Only reads the live DB: renders and
 * attached pieces stay in memory and land in files under the output folder.
 *
 * Run from apps/server: npx tsx compare-art-tmp.mts <outDir> <cardsFile> <modelId:thinking> ...
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { Agent, type AgentMessage } from "@spoin/pi-agent";
import type { Api, Model, ThinkingLevel } from "@spoin/pi-ai";
import { eq, inArray } from "drizzle-orm";
import { Type } from "typebox";
import { artProblems, attachArtTool, listArtRequestsTool, normalizeArt, renderArtTool } from "./src/agents/art.ts";
import { chromiumBrowser } from "./src/agents/browser.ts";
import type { AgentDeps } from "./src/agents/context.ts";
import { lookAtTool } from "./src/agents/pages.ts";
import { metaOf } from "./src/agents/tiers.ts";
import { toCardOut } from "./src/cards/out.ts";
import { connectApp } from "./src/db/client.ts";
import { card, subtopic, topic } from "./src/db/schema.ts";
import { patientGemini } from "./src/harness/gemini.ts";
import { imagesShownOnce } from "./src/harness/run-chat.ts";
import type { ToolContext } from "./src/harness/tools.ts";
import { findModel, loadModels, proxyAnswers } from "./src/models/proxy.ts";
import { loadPrompts } from "./src/prompts.ts";

const [outDir, cardsFile, ...modelArgs] = process.argv.slice(2);
if (!outDir || !cardsFile || modelArgs.length === 0) throw new Error("outDir cardsFile model:thinking ...");
mkdirSync(outDir, { recursive: true });

const env = Object.fromEntries(
  readFileSync("../../infra/.env", "utf8")
    .split("\n")
    .filter((line) => line.includes("=") && !line.trim().startsWith("#"))
    .map((line) => {
      const at = line.indexOf("=");
      return [line.slice(0, at).trim(), line.slice(at + 1).trim().replace(/^"|"$/g, "")];
    }),
);
const proxy = {
  url: "http://127.0.0.1:8319",
  apiKey: env.CLIPROXY_API_KEY ?? "",
  managementKey: env.CLIPROXY_MANAGEMENT_KEY ?? null,
};

const cardIds = readFileSync(cardsFile, "utf8")
  .trim()
  .split("\n")
  .map((line) => line.split("|")[0] ?? "");
// Every connection read-only: the comparison never writes to the live DB.
const app = connectApp(
  "postgres://spoin:spoin@localhost:5434/spoin?options=-c%20default_transaction_read_only%3Don",
);
const rows = await app.db
  .select({ card, subtopicTitle: subtopic.title, difficulty: subtopic.difficulty })
  .from(card)
  .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
  .where(inArray(card.id, cardIds));
const ordered = cardIds.map((id) => {
  const found = rows.find((row) => row.card.id === id);
  if (!found) throw new Error(`No card ${id}`);
  return found;
});
const topicId = ordered[0]?.card.topicId ?? "";
const [topicRow] = await app.db
  .select({ id: topic.id, name: topic.canonicalName, description: topic.description })
  .from(topic)
  .where(eq(topic.id, topicId));
if (!topicRow) throw new Error("No topic");

const prompts = loadPrompts();
const browser = chromiumBrowser("http://localhost:3001");
const deps = { prompts, browser } as unknown as AgentDeps;
const systemPrompt = prompts.render("designer_toad.njk", { summary: null, topic: topicRow });
const opening =
  "Cards of this topic are waiting for art. list_art_requests shows them; draw each, render it, and attach the pieces that read well.";
/** The model, asking the proxy again for a while: its list of served models flickers. */
async function served(modelId: string): Promise<Model<Api>> {
  for (let tries = 1; ; tries++) {
    try {
      return findModel(await loadModels(proxy), modelId);
    } catch (error) {
      if (tries >= 20) throw error;
      console.log(`[${modelId}] not served yet, asking again in 15s`);
      await new Promise((resolve) => setTimeout(resolve, 15_000));
    }
  }
}

const ArtParameters = renderArtTool(deps).parameters;
type Piece = { card: string; art: string; alt: string };

async function draw(modelId: string, thinkingLevel: ThinkingLevel) {
  const model = await served(modelId);
  const rendered = new Set<string>();
  const attached = new Map<string, Piece>();
  const log: string[] = [];
  let renders = 0;
  let refused = 0;
  const waiting = () => ordered.filter((one) => !attached.has(one.card.id));
  const say = (line: string) => {
    log.push(line);
    console.log(`[${modelId}] ${line}`);
  };

  const listTool = listArtRequestsTool(deps);
  const renderTool = renderArtTool(deps);
  const attachTool = attachArtTool(deps);
  const look = lookAtTool(deps);
  const signal = AbortSignal.timeout(40 * 60_000);

  const tools = [
    {
      name: listTool.name,
      label: listTool.label,
      description: listTool.description,
      parameters: Type.Object({}),
      execute: async () => {
        const cards = waiting().map((one) => ({
          ...one.card,
          meta: metaOf(one.card),
          subtopicTitle: one.subtopicTitle,
          redraw: true,
        }));
        const text = prompts.render("tool-results/art-requests.njk", {
          cards,
          total: cards.length,
          redraws: cards.length,
          trial: null,
        });
        say(`list_art_requests: ${cards.length} waiting`);
        return { content: [{ type: "text" as const, text }], details: {} };
      },
    },
    {
      name: renderTool.name,
      label: renderTool.label,
      description: renderTool.description,
      parameters: ArtParameters,
      execute: async (_id: string, params: { art: Piece[] }) => {
        const said: string[] = [];
        const images: { type: "image"; data: string; mimeType: string }[] = [];
        for (const piece of params.art) {
          const one = waiting().find((w) => w.card.id === piece.card);
          if (!one) {
            said.push(`- card ${piece.card}: isn't waiting for art: list_art_requests shows the ones that are`);
            continue;
          }
          const art = normalizeArt(piece.art);
          const kind = metaOf(one.card).art?.kind ?? "gag";
          const problems = artProblems(art, kind);
          if (problems.length > 0) {
            refused += 1;
            say(`render refused ${piece.card.slice(0, 8)}: ${problems.join("; ")}`);
            said.push(`- card ${piece.card}: not rendered; fix every problem: ${problems.join("; ")}`);
            continue;
          }
          const shown = {
            ...one.card,
            visualId: one.card.visualId ?? one.card.id,
            visualKind: "ascii" as const,
            visualSlots: { art, alt: piece.alt },
          };
          const png = await browser.renderCard(
            { card: toCardOut(shown, one.subtopicTitle), topicName: topicRow.name },
            signal,
          );
          renders += 1;
          rendered.add(`${piece.card}\n${art}`);
          images.push({ type: "image", data: png.toString("base64"), mimeType: "image/png" });
          said.push(`- card ${piece.card}: screenshot ${images.length}`);
          say(`rendered ${piece.card.slice(0, 8)}`);
        }
        const text = `${said.join("\n")}\nEach screenshot is the card as a reader sees it on a phone. attach_art the art that reads well; draw the rest again.`;
        return { content: [{ type: "text" as const, text }, ...images], details: {} };
      },
    },
    {
      name: attachTool.name,
      label: attachTool.label,
      description: attachTool.description,
      parameters: ArtParameters,
      execute: async (_id: string, params: { art: Piece[] }) => {
        const problems: string[] = [];
        for (const piece of params.art) {
          if (!rendered.has(`${piece.card}\n${normalizeArt(piece.art)}`)) {
            problems.push(`card ${piece.card}: this run hasn't rendered that exact art on it; render_art it first`);
          }
        }
        if (problems.length > 0) throw new Error(`Nothing was attached:\n- ${problems.join("\n- ")}`);
        for (const piece of params.art) {
          attached.set(piece.card, { card: piece.card, art: normalizeArt(piece.art), alt: piece.alt.trim() });
          say(`attached ${piece.card.slice(0, 8)}`);
        }
        const text = `Attached art to ${params.art.length} card(s).`;
        return { content: [{ type: "text" as const, text }], details: {} };
      },
    },
    {
      name: look.name,
      label: look.label,
      description: look.description,
      parameters: look.parameters,
      execute: async (_id: string, params: { url: string }) => {
        say(`look_at ${params.url}`);
        const seen = await look.execute(params, { signal } as unknown as ToolContext);
        const images = (seen.images ?? []).map((image) => ({ type: "image" as const, ...image }));
        return { content: [{ type: "text" as const, text: String(seen.value) }, ...images], details: {} };
      },
    },
  ];

  const agent = new Agent({
    initialState: { systemPrompt, model, thinkingLevel, tools: tools as never, messages: [] },
    // The harness's patience: a failed call is made again before the model sees it. No call is
    // recorded, and a limit waits by cooling, since only Antigravity's limits can be looked up.
    streamFn: patientGemini({
      record: () => {},
      opensAt: async () => null,
      proxyAnswers: () => proxyAnswers(proxy),
    }),
    transformContext: async (messages: AgentMessage[]) => imagesShownOnce(messages),
    getApiKey: () => proxy.apiKey,
  });
  signal.addEventListener("abort", () => agent.abort(), { once: true });
  const started = Date.now();
  await agent.prompt(opening);
  const messages = agent.state.messages;
  const last = messages.at(-1) as { stopReason?: string; errorMessage?: string } | undefined;
  let tokens = 0;
  for (const message of messages) {
    const usage = (message as { usage?: { totalTokens?: number } }).usage;
    tokens += usage?.totalTokens ?? 0;
  }
  const result = {
    model: modelId,
    thinkingLevel,
    minutes: Math.round((Date.now() - started) / 6000) / 10,
    renders,
    refused,
    tokens,
    stopReason: last?.stopReason,
    error: last?.errorMessage,
    pieces: [...attached.values()],
    log,
  };
  const safe = modelId.replace(/[^a-z0-9.-]/gi, "_");
  writeFileSync(`${outDir}/${safe}.json`, JSON.stringify(result, null, 2));
  writeFileSync(`${outDir}/${safe}.messages.json`, JSON.stringify(messages, null, 2));
  for (const piece of attached.values()) {
    const one = ordered.find((w) => w.card.id === piece.card);
    if (!one) continue;
    const shown = {
      ...one.card,
      visualId: one.card.visualId ?? one.card.id,
      visualKind: "ascii" as const,
      visualSlots: { art: piece.art, alt: piece.alt },
    };
    const png = await browser.renderCard(
      { card: toCardOut(shown, one.subtopicTitle), topicName: topicRow.name },
      AbortSignal.timeout(120_000),
    );
    writeFileSync(`${outDir}/${safe}-${piece.card}.png`, png);
  }
  say(`done: ${attached.size} attached, ${renders} renders, ${refused} refused, ${result.minutes} min, stop ${last?.stopReason}`);
}

await Promise.all(
  modelArgs.map(async (arg) => {
    const [id, level] = arg.split(":");
    try {
      await draw(id ?? "", (level ?? "medium") as ThinkingLevel);
    } catch (error) {
      console.log(`[${id}] FAILED ${String(error)}`);
    }
  }),
);
await app.pool.end();
process.exit(0);
