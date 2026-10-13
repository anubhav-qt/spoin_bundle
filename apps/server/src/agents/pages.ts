import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { and, asc, cosineDistance, eq, gte, sql } from "drizzle-orm";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import { page, pagePassage } from "../db/schema.ts";
import { withoutTag } from "../harness/prompt-tags.ts";
import { CLOSED, Id } from "../harness/schemas.ts";
import { type HarnessTool, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { htmlText } from "./html-text.ts";

/*
 * Pages from the web (harness-tools.md, task 0045): fetched over plain HTTP, or in headless
 * Chromium when the HTML holds no real text; public pages only, robots.txt ignored, paced per
 * site. A page's text is kept on disk and its passages in Postgres with their embeddings, numbered
 * so a map can cite one, and every chat finds what any chat read before it goes to the web again.
 */

/** The tag a page's text is wrapped in: web content, which no one in spoin wrote. */
const TAG = "page_text";
/** A passage's size: a paragraph or a few, cut at paragraph breaks. */
const PASSAGE_CHARS = 1200;
/** What one call shows of a page; the rest comes from read_page. */
const SHOWN_CHARS = 14_000;
/** HTML with less text than this is read again in the browser. */
const REAL_TEXT_CHARS = 600;
/** The longest a page is kept: past it, a page is mostly navigation or a dump. */
const MAX_TEXT_CHARS = 400_000;
/** The least time between two fetches from one site. */
const PACE_MS = 2_000;
const FETCH_TIMEOUT_MS = 30_000;
const SEARCH_RESULTS = 8;

/** When each site was last fetched from, shared by every chat in the process. */
const lastFetch = new Map<string, number>();

type Page = typeof page.$inferSelect;

const FetchParameters = Type.Object(
  {
    url: Type.String({ minLength: 1, description: "An http or https address" }),
    fresh: Type.Optional(Type.Boolean({ description: "Fetch it again even if it is stored" })),
  },
  CLOSED,
);

export function fetchTool(deps: AgentDeps): HarnessTool<typeof FetchParameters> {
  return {
    name: "fetch",
    label: "Fetch a page",
    description: deps.prompts.render("tools/fetch.njk", {}),
    parameters: FetchParameters,
    kind: "read",
    async execute(params, context) {
      const url = publicUrl(params.url);
      const [stored] = await deps.db.select().from(page).where(eq(page.url, url));
      let found = stored;
      if (!found || params.fresh) found = await fetchAndStore(deps, url, context.signal);
      return { value: await shown(deps, found, 1), dataSeen: [], recordsWritten: [] };
    },
  };
}

const ReadPageParameters = Type.Object(
  { page: Id, from_passage: Type.Integer({ minimum: 1, description: "The first passage to read" }) },
  CLOSED,
);

export function readPageTool(deps: AgentDeps): HarnessTool<typeof ReadPageParameters> {
  return {
    name: "read_page",
    label: "Read on in a page",
    description: deps.prompts.render("tools/read-page.njk", {}),
    parameters: ReadPageParameters,
    kind: "read",
    async execute(params) {
      const [found] = await deps.db.select().from(page).where(eq(page.id, params.page));
      if (!found) throw new ToolError(`There is no stored page ${params.page}: fetch it first.`);
      return { value: await shown(deps, found, params.from_passage), dataSeen: [], recordsWritten: [] };
    },
  };
}

const SearchPagesParameters = Type.Object(
  { query: Type.String({ minLength: 1, description: "What you want a page to say" }) },
  CLOSED,
);

export function searchPagesTool(deps: AgentDeps): HarnessTool<typeof SearchPagesParameters> {
  return {
    name: "search_pages",
    label: "Search the stored pages",
    description: deps.prompts.render("tools/search-pages.njk", {}),
    parameters: SearchPagesParameters,
    kind: "read",
    async execute(params) {
      const [vector] = await deps.embedder.embedQuery([params.query]);
      if (!vector) throw new ToolError("The query could not be embedded.");
      const distance = cosineDistance(pagePassage.embedding, vector);
      const hits = await deps.db
        .select({
          page: page.id,
          url: page.url,
          title: page.title,
          passage: pagePassage.ordinal,
          text: pagePassage.text,
          score: sql<number>`1 - (${distance})`.mapWith(Number),
        })
        .from(pagePassage)
        .innerJoin(page, eq(page.id, pagePassage.pageId))
        .orderBy(distance)
        .limit(SEARCH_RESULTS);
      const shownHits = hits.map((hit) => ({ ...hit, text: withoutTag(hit.text, TAG) }));
      return {
        value: deps.prompts.render("tool-results/page-hits.njk", { query: params.query, hits: shownHits }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

/** Whether a stored page has a passage of this number. */
export async function passageExists(db: Db, pageId: string, ordinal: number): Promise<boolean> {
  const [found] = await db
    .select({ ordinal: pagePassage.ordinal })
    .from(pagePassage)
    .where(and(eq(pagePassage.pageId, pageId), eq(pagePassage.ordinal, ordinal)));
  return found !== undefined;
}

/**
 * The address, if it is a public web page's. Private and local addresses are refused, so a chat
 * can't reach the database, the proxy or anything else on the worker's network.
 */
function publicUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    throw new ToolError(`${raw} is not a web address.`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ToolError("Only http and https pages can be fetched.");
  }
  const host = url.hostname.toLowerCase();
  const local =
    !host.includes(".") ||
    host.endsWith(".local") ||
    host.endsWith(".internal") ||
    /^(127\.|10\.|192\.168\.|169\.254\.|0\.)/.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    host.startsWith("[");
  if (local) throw new ToolError(`${host} is not a public site.`);
  url.hash = "";
  return url.toString();
}

async function fetchAndStore(deps: AgentDeps, url: string, signal: AbortSignal): Promise<Page> {
  await paced(new URL(url).hostname, signal);
  let read = await overHttp(url, signal);
  let fetchedWith = "http";
  if (read.text.length < REAL_TEXT_CHARS) {
    try {
      const inBrowser = await deps.browser.pageText(url, signal);
      if (inBrowser.text.trim().length > read.text.length) {
        read = { title: inBrowser.title || read.title, text: tidy(inBrowser.text) };
        fetchedWith = "browser";
      }
    } catch (error) {
      if (signal.aborted) throw error;
      if (read.text.length === 0) {
        throw new ToolError(`${url} has no text over HTTP, and the browser couldn't read it either.`);
      }
    }
  }
  if (read.text.length === 0) throw new ToolError(`${url} has no text to read.`);
  const text = read.text.slice(0, MAX_TEXT_CHARS);
  const passages = passagesOf(text);
  const vectors = await deps.embedder.embedPassage(passages);
  const hash = createHash("sha256").update(url).digest("hex");
  const path = `${hash.slice(0, 2)}/${hash}.txt`;
  mkdirSync(join(deps.files.pages, hash.slice(0, 2)), { recursive: true });
  writeFileSync(join(deps.files.pages, path), text);
  const contentHash = createHash("sha256").update(text).digest("hex");

  return deps.db.transaction(async (tx) => {
    const values = { url, title: read.title || null, path, contentHash, fetchedWith, fetchedAt: new Date() };
    const [stored] = await tx
      .insert(page)
      .values(values)
      .onConflictDoUpdate({ target: page.url, set: values })
      .returning();
    if (!stored) throw new Error(`${url} could not be stored.`);
    await tx.delete(pagePassage).where(eq(pagePassage.pageId, stored.id));
    await tx.insert(pagePassage).values(
      passages.map((passage, index) => ({
        pageId: stored.id,
        ordinal: index + 1,
        text: passage,
        embedding: vectors[index] as number[],
        embeddingModel: deps.embedder.modelName,
      })),
    );
    return stored;
  });
}

/** Waits until the site's last fetch is far enough behind. */
async function paced(host: string, signal: AbortSignal): Promise<void> {
  const wait = (lastFetch.get(host) ?? 0) + PACE_MS - Date.now();
  lastFetch.set(host, Date.now() + Math.max(0, wait));
  if (wait <= 0) return;
  await new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, wait);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

async function overHttp(url: string, signal: AbortSignal): Promise<{ title: string; text: string }> {
  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; spoin-research/1.0)",
        Accept: "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
      },
      redirect: "follow",
      signal: AbortSignal.any([signal, AbortSignal.timeout(FETCH_TIMEOUT_MS)]),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    return { title: "", text: "" };
  }
  if (!response.ok) {
    if (response.status === 404 || response.status === 410) {
      throw new ToolError(`${url} answered ${response.status}: there is no such page.`);
    }
    return { title: "", text: "" };
  }
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("pdf")) {
    throw new ToolError(`${url} is a PDF, which fetch can't read yet: find the same material as a web page.`);
  }
  const body = await response.text();
  if (type.includes("text/plain")) return { title: "", text: tidy(body) };
  return htmlText(body);
}

/** Lines trimmed, and runs of blank lines folded to one. */
function tidy(text: string): string {
  return text
    .split("\n")
    .map((line) => line.replace(/[ \t ]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** The text cut into passages at paragraph breaks, each about PASSAGE_CHARS long. */
export function passagesOf(text: string): string[] {
  const passages: string[] = [];
  let current = "";
  for (const paragraph of text.split(/\n{2,}/)) {
    const pieces = [];
    // A paragraph longer than a passage is cut at sentence ends, or hard when it has none.
    if (paragraph.length <= PASSAGE_CHARS) pieces.push(paragraph);
    else {
      let rest = paragraph;
      while (rest.length > PASSAGE_CHARS) {
        let cut = rest.lastIndexOf(". ", PASSAGE_CHARS);
        if (cut < PASSAGE_CHARS / 2) cut = PASSAGE_CHARS;
        else cut += 1;
        pieces.push(rest.slice(0, cut).trim());
        rest = rest.slice(cut).trim();
      }
      if (rest) pieces.push(rest);
    }
    for (const piece of pieces) {
      if (current && current.length + piece.length + 2 > PASSAGE_CHARS) {
        passages.push(current);
        current = "";
      }
      current = current ? `${current}\n\n${piece}` : piece;
    }
  }
  if (current) passages.push(current);
  return passages;
}

/** The page from a passage on, as much as one call shows, with how to read the rest. */
async function shown(deps: AgentDeps, found: Page, from: number): Promise<string> {
  const passages = await deps.db
    .select({ ordinal: pagePassage.ordinal, text: pagePassage.text })
    .from(pagePassage)
    .where(and(eq(pagePassage.pageId, found.id), gte(pagePassage.ordinal, from)))
    .orderBy(asc(pagePassage.ordinal));
  const [total] = await deps.db
    .select({ count: sql<number>`count(*)`.mapWith(Number) })
    .from(pagePassage)
    .where(eq(pagePassage.pageId, found.id));
  if (passages.length === 0) throw new ToolError(`Page ${found.id} has no passage ${from}.`);
  const shownPassages = [];
  let size = 0;
  for (const passage of passages) {
    if (shownPassages.length > 0 && size + passage.text.length > SHOWN_CHARS) break;
    shownPassages.push({ ...passage, text: withoutTag(passage.text, TAG) });
    size += passage.text.length;
  }
  const last = shownPassages.at(-1)?.ordinal ?? from;
  return deps.prompts.render("tool-results/page.njk", {
    page: { ...found, title: withoutTag(found.title ?? "", TAG) },
    passages: shownPassages,
    total: total?.count ?? 0,
    next: last < (total?.count ?? 0) ? last + 1 : null,
  });
}
