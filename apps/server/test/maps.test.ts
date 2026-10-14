import { randomUUID } from "node:crypto";
import { describe, expect, test } from "vitest";
import type { AgentDeps } from "../src/agents/context.ts";
import { settleFindingTool } from "../src/agents/documents.ts";
import { handOverTool } from "../src/agents/handovers.ts";
import {
  auditMapsTool,
  changeMapTool,
  claimsNeeded,
  itemProblems,
  mapsFacts,
  mapsHandoverProblems,
  mapsProblems,
  mergeMapItems,
  misconceptionsNeeded,
  type TopicMaps,
} from "../src/agents/maps.ts";
import { page, pagePassage, topic } from "../src/db/schema.ts";
import { endRun, openTopicChat, startRun } from "../src/harness/chats.ts";
import { openingMessageFor } from "../src/harness/instructions.ts";
import { createRecord, listTopicRecords } from "../src/harness/records.ts";
import {
  FindingRecord,
  HandoverRecord,
  IntakeRecord,
  MAP_KINDS,
  type MapItem,
  MapRecord,
} from "../src/harness/schemas.ts";
import type { ToolContext } from "../src/harness/tools.ts";
import { appendActionLogEntry, appendMessage, resultsCutOff } from "../src/harness/transcript.ts";
import { loadPrompts } from "../src/prompts.ts";
import { deps } from "./helpers.ts";

/*
 * A topic's maps before they go to toad_sage (ADR-0110): they hold together, are big enough for the
 * topic's cards, claim no more than their sources give, and are audited against their passages by
 * a call the tadpole doesn't brief, which reads only what changed since it last read.
 */

const { db } = deps;
const prompts = loadPrompts();

const PAGES = {
  book: randomUUID(),
  reference: randomUUID(),
  blogA: randomUUID(),
  blogB: randomUUID(),
  forum: randomUUID(),
};

const cite = (pageId: string, passage = 1) => ({ page: pageId, passage });

function claim(name: string, domain: string, pages: string[], extra: Partial<MapItem> = {}): MapItem {
  return {
    name,
    text: `${name} holds.`,
    claimType: "mechanistic",
    scope: "universal",
    confidence: "high",
    domain,
    evidence: pages.map((one) => cite(one)),
    ...extra,
  };
}

function source(name: string, tier: MapItem["sourceTier"], date: string, pageId: string): MapItem {
  return { name, text: `${name}.`, sourceTier: tier, sourceDate: date, evidence: [cite(pageId)] };
}

/** Maps A to J for a topic of one domain, ownership, that hold together for six cards. */
function itemsByKind(
  pages: Record<keyof typeof PAGES, string> = PAGES,
): Record<(typeof MAP_KINDS)[number], MapItem[]> {
  const plain = (name: string): MapItem => ({ name, text: `${name}.`, evidence: [] });
  return {
    A: [plain("ownership")],
    B: [{ ...plain("ownership"), after: [] }],
    C: [claim("one owner", "ownership", [pages.book]), claim("moves", "ownership", [pages.reference])],
    D: [
      source("The Rust Book", "official_documentation", "2026-07", pages.book),
      source("The Rust Reference", "primary_specification", "Rust 1.97", pages.reference),
      source("Blog A", "recognised_expert", "2025", pages.blogA),
      source("Blog B", "recognised_expert", "2024", pages.blogB),
      source("A forum", "community_heuristic", "2026", pages.forum),
    ],
    E: [plain("trace a move")],
    F: [plain("a move copies the heap")],
    G: [plain("command-line tools")],
    H: [plain("channels or shared state")],
    I: [plain("custom allocators")],
    J: [{ ...plain("edition 2024"), checkBy: "2027-07-01" }],
  };
}

function topicMaps(changes: Partial<Record<(typeof MAP_KINDS)[number], MapItem[] | null>> = {}): TopicMaps {
  const topicId = randomUUID();
  const maps: TopicMaps = {};
  const items = { ...itemsByKind(), ...changes };
  for (const kind of MAP_KINDS) {
    const kindItems = items[kind];
    if (!kindItems) continue;
    maps[kind] = {
      id: randomUUID(),
      version: 1,
      kind: "map",
      status: "active",
      writtenAt: new Date().toISOString(),
      author: { kind: "owner" },
      body: { topic: topicId, map: kind, items: kindItems, summary: "s" },
    };
  }
  return maps;
}

describe("a map's items", () => {
  test("a claim names its domain, an implementation claim its version, and a source its date", () => {
    expect(itemProblems("C", [claim("one owner", "ownership", [PAGES.book], { domain: undefined })])).toEqual(
      ['"one owner": a claim names its domain, an item of map A'],
    );
    expect(
      itemProblems("C", [claim("Rc counts", "ownership", [PAGES.book], { claimType: "implementation" })]),
    ).toEqual([
      '"Rc counts": an implementation claim gives appliesTo, the product and version it is true of',
    ]);
    const undated = {
      ...source("The Rust Book", "official_documentation", "x", PAGES.book),
      sourceDate: undefined,
    };
    expect(itemProblems("D", [undated])).toEqual([
      '"The Rust Book": a source gives sourceDate, when it was published or the version it documents',
    ]);
  });

  test("a change sends only what changes: an item replaces its namesake where it stood, a new one goes last", () => {
    const items = itemsByKind().C;
    const changed = claim("moves", "ownership", [PAGES.book], { text: "A move hands the value over." });
    const added = claim("drops", "ownership", [PAGES.book]);
    expect(mergeMapItems(items, [changed, added], []).map((item) => item.text)).toEqual([
      "one owner holds.",
      "A move hands the value over.",
      "drops holds.",
    ]);
    expect(mergeMapItems(items, [], ["one owner"]).map((item) => item.name)).toEqual(["moves"]);
    expect(() => mergeMapItems(items, [], ["borrows"])).toThrow(/no item named borrows/);
    expect(() => mergeMapItems(items, [], [])).toThrow(/Give the items that change/);
  });
});

describe("whether the maps hold together", () => {
  test("maps that hold together for the topic's cards have no problems", () => {
    expect(mapsProblems(topicMaps(), 6)).toEqual([]);
  });

  test("a topic needs a claim for every 3 cards and a misconception for every 10", () => {
    expect(claimsNeeded(700)).toBe(234);
    expect(misconceptionsNeeded(700)).toBe(70);
    expect(claimsNeeded(450)).toBe(150);
    expect(misconceptionsNeeded(450)).toBe(45);
    expect(mapsProblems(topicMaps(), 700)).toEqual([
      "map C holds 2 claims, and the topic's 700 cards need at least 234, one for every 3 cards: add them with change_map",
      "map F holds 1 misconceptions, and the topic's 700 cards need at least 70, one for every 10 cards, since a tenth of them are myth-vs-fact cards",
    ]);
  });

  test("high confidence stands on a primary tier, or on two recognised experts that agree", () => {
    const one = topicMaps({
      C: [claim("one owner", "ownership", [PAGES.blogA]), claim("moves", "ownership", [PAGES.reference])],
    });
    expect(mapsProblems(one, 6)).toEqual([
      'map C "one owner": high confidence stands on a specification, official documentation, primary research or an authoritative textbook, or on two recognised experts that agree; its sources are "Blog A" (recognised expert)',
    ]);
    const two = topicMaps({
      C: [
        claim("one owner", "ownership", [PAGES.blogA, PAGES.blogB]),
        claim("moves", "ownership", [PAGES.reference]),
      ],
    });
    expect(mapsProblems(two, 6)).toEqual([]);
  });

  test("an empirical claim cites primary research, and a forum alone carries only a low confidence", () => {
    const maps = topicMaps({
      C: [
        claim("jitter halves calls", "ownership", [PAGES.book], {
          claimType: "empirical",
          confidence: "low",
        }),
        claim("moves", "ownership", [PAGES.forum], { confidence: "medium" }),
        claim("folk wisdom", "ownership", [PAGES.forum], { claimType: "heuristic", confidence: "low" }),
        claim("refs", "ownership", [PAGES.reference]),
      ],
    });
    const problems = mapsProblems(maps, 6);
    expect(problems).toHaveLength(2);
    expect(problems[0]).toMatch(/^map C "jitter halves calls": an empirical claim is measured/);
    expect(problems[1]).toMatch(
      /^map C "moves": medium confidence needs a source of secondary synthesis or better/,
    );
  });

  test("a domain is taught from two sources, or named a gap; a claim's domain is one of map A's", () => {
    const thin = topicMaps({
      C: [claim("one owner", "ownership", [PAGES.book]), claim("moves", "ownership", [PAGES.book])],
    });
    expect(mapsProblems(thin, 6)).toEqual([
      'the domain "ownership" rests on one source, "The Rust Book": find a second, or name what is missing in map I as a gap of the domain',
    ]);
    const gap = {
      name: "no reference",
      text: "The Reference wasn't reached.",
      domain: "ownership",
      evidence: [],
    };
    expect(mapsProblems(topicMaps({ C: thin.C?.body.items ?? [], I: [gap] }), 6)).toEqual([]);
    const elsewhere = topicMaps({
      C: [claim("one owner", "borrowing", [PAGES.book]), claim("moves", "borrowing", [PAGES.reference])],
    });
    expect(mapsProblems(elsewhere, 6)).toEqual([
      '"one owner" names the domain "borrowing", which is not an item of map A',
      '"moves" names the domain "borrowing", which is not an item of map A',
      'the domain "ownership" has no claim in map C: research it, or name it in map I as a gap',
    ]);
  });

  test("a page belongs to one source, every page a claim cites has one, and all ten maps are written", () => {
    const stray = randomUUID();
    const maps = topicMaps({
      C: [
        claim("one owner", "ownership", [PAGES.book, stray], { confidence: "high" }),
        claim("moves", "ownership", [PAGES.reference]),
      ],
      D: [...itemsByKind().D, source("The Book, again", "official_documentation", "2026-07", PAGES.book)],
      J: null,
    });
    expect(mapsProblems(maps, 6)).toEqual([
      "write map J first",
      `map D: page ${PAGES.book} is in both "The Rust Book" and "The Book, again": a page belongs to one source, and a source is one publication`,
      `map C cites page ${stray}, which no source of map D names: give its publication an entry`,
    ]);
  });

  test("toad_sage reads what code counted, each domain with its sources, and every finding kept", () => {
    const facts = mapsFacts(topicMaps(), 6, [
      { item: "C/moves", problem: "Overstated.", settled: { how: "kept", note: "The Reference says so." } },
      { item: "C/one owner", problem: "Vague.", settled: { how: "fixed", note: "Reworded." } },
    ]);
    expect(facts).toContain(
      "Cards: 6. Claims in map C: 2 (at least 2). Misconceptions in map F: 1 (at least 1).",
    );
    expect(facts).toContain("Claims by confidence: high 2.");
    expect(facts).toContain(
      "- ownership: 2 claims, from The Rust Book (official documentation, 2026-07); The Rust Reference (primary specification, Rust 1.97)",
    );
    expect(facts).toContain("- The Rust Book: official documentation, 2026-07; 1 pages, cited by 1 claims");
    expect(facts).toContain("The evidence auditor's findings: 2, 1 fixed, 1 kept as they were.");
    expect(facts).toContain("- kept, C/moves: Overstated. The tadpole's reason: The Reference says so.");
  });
});

/** A topic of six cards with its pages stored and its ten maps written, and its tadpole running. */
async function topicWithMaps() {
  const name = `Rust ${randomUUID().slice(0, 6)}`;
  const [made] = await db
    .insert(topic)
    .values({ slug: name.toLowerCase().replaceAll(/\W+/g, "-"), canonicalName: name, scope: "topic" })
    .returning();
  if (!made) throw new Error("No topic.");
  const pages = { book: "", reference: "", blogA: "", blogB: "", forum: "" };
  for (const key of Object.keys(pages) as (keyof typeof pages)[]) {
    const [stored] = await db
      .insert(page)
      .values({
        url: `https://example.org/${key}/${randomUUID()}`,
        title: key,
        path: `${key}.md`,
        contentHash: randomUUID(),
        fetchedWith: "http",
      })
      .returning();
    if (!stored) throw new Error("No page.");
    await db.insert(pagePassage).values({
      pageId: stored.id,
      ordinal: 1,
      text: `What ${key} says.`,
      embedding: Array.from({ length: 1024 }, () => 0.1),
      embeddingModel: "test",
    });
    pages[key] = stored.id;
  }
  const author = { kind: "owner" as const };
  await createRecord(db, IntakeRecord, {
    kind: "intake",
    author,
    body: {
      topic: made.id,
      name,
      subject: "Rust Programming Language",
      angle: null,
      scope: "topic",
      category: "computer science",
      subCategory: null,
      cardCount: 6,
      brief: "Ownership.",
      buildsOn: [],
    },
  });
  const items = itemsByKind(pages);
  for (const kind of MAP_KINDS) {
    await createRecord(db, MapRecord, {
      kind: "map",
      author,
      body: { topic: made.id, map: kind, items: items[kind], summary: "s" },
    });
  }
  const tadpole = await openTopicChat(db, "tadpole", made.id);
  const run = await startRun(db, {
    chatId: tadpole.id,
    model: "m",
    systemPrompt: "s",
    triggers: [{ kind: "schedule", schedule: "test" }],
  });
  const context = {
    db,
    chat: tadpole,
    run,
    author: { kind: "chat" as const, chatId: tadpole.id, runId: run.id, model: "m" },
    signal: new AbortController().signal,
  } as ToolContext;
  return { topicId: made.id, pages, context };
}

describe("the maps' audit and handover", () => {
  test("the maps go once audited and every finding settled; a change is audited again, and only it is read", async () => {
    const { topicId, pages, context } = await topicWithMaps();
    const prompted: string[] = [];
    let answer = {
      findings: [{ item: "C/one owner", problem: "It says more than the Book.", fix: "Narrow it." }],
    };
    const agentDeps = {
      db,
      prompts,
      oneShot: async (call: { prompt: string }) => {
        prompted.push(call.prompt);
        return answer;
      },
    } as unknown as AgentDeps;

    expect(await mapsHandoverProblems(db, topicId)).toEqual([
      "The maps have never been audited: call audit_maps.",
    ]);
    await auditMapsTool(agentDeps).execute({}, context);
    expect(prompted).toHaveLength(1);
    expect(prompted[0]).toContain('<item key="C/one owner">');
    expect(prompted[0]).toContain('<item key="F/a move copies the heap">');
    expect(prompted[0]).toContain("What book says.");

    const [finding] = await listTopicRecords(db, FindingRecord, "finding", topicId);
    if (!finding) throw new Error("No finding.");
    expect(finding.body.item).toBe("C/one owner");
    expect(await mapsHandoverProblems(db, topicId)).toEqual([
      `Finding ${finding.id} (C/one owner) is not settled.`,
    ]);
    await settleFindingTool(agentDeps).execute(
      { finding: finding.id, how: "fixed", note: "Narrowed." },
      context,
    );
    expect(await mapsHandoverProblems(db, topicId)).toEqual([]);

    const mapC = (await listTopicRecords(db, MapRecord, "map", topicId)).find((map) => map.body.map === "C");
    if (!mapC) throw new Error("No map C.");
    const narrowed = claim("one owner", "ownership", [pages.book], {
      text: "Each value has one owner at a time.",
    });
    await changeMapTool(agentDeps).execute({ map: mapC.id, reason: "Narrowed.", items: [narrowed] }, context);
    expect(await mapsHandoverProblems(db, topicId)).toEqual([
      "Map C changed after the last audit: call audit_maps again.",
    ]);

    answer = { findings: [] };
    await auditMapsTool(agentDeps).execute({}, context);
    expect(prompted).toHaveLength(2);
    expect(prompted[1]).toContain('<item key="C/one owner">');
    expect(prompted[1]).not.toContain('<item key="C/moves">');
    expect(await mapsHandoverProblems(db, topicId)).toEqual([]);
    await expect(auditMapsTool(agentDeps).execute({}, context)).rejects.toThrow(
      /Nothing in maps C and F changed/,
    );

    await handOverTool(agentDeps).execute({ kind: "maps", records: [mapC.id], note: "The maps." }, context);
    const [handover] = await listTopicRecords(db, HandoverRecord, "handover", topicId);
    expect(handover?.body.facts).toContain("Cards: 6. Claims in map C: 2 (at least 2).");
    expect(handover?.body.facts).toContain(
      "The evidence auditor's findings: 1, 1 fixed, 0 kept as they were.",
    );
  });

  test("maps that don't hold together are neither audited nor handed over", async () => {
    const { topicId, context } = await topicWithMaps();
    const mapC = (await listTopicRecords(db, MapRecord, "map", topicId)).find((map) => map.body.map === "C");
    if (!mapC) throw new Error("No map C.");
    const agentDeps = { db, prompts, oneShot: async () => ({ findings: [] }) } as unknown as AgentDeps;
    await changeMapTool(agentDeps).execute({ map: mapC.id, reason: "Thinner.", drop: ["moves"] }, context);
    await expect(auditMapsTool(agentDeps).execute({}, context)).rejects.toThrow(
      /don't hold together yet[\s\S]*map C holds 1 claims/,
    );
    await expect(
      handOverTool(agentDeps).execute({ kind: "maps", records: [mapC.id], note: "The maps." }, context),
    ).rejects.toThrow(/The maps can't go yet/);
  });
});

describe("a run cut off between a call's end and its result", () => {
  test("the chat's next run reads the result instead of calling again", async () => {
    const { context } = await topicWithMaps();
    const run = context.run;
    const toolResult = (toolCallId: string) => ({
      role: "toolResult" as const,
      toolCallId,
      toolName: "fetch",
      content: [{ type: "text" as const, text: "stored" }],
      isError: false,
      timestamp: Date.now(),
    });
    await appendMessage(db, run, toolResult("call_seen"));
    for (const toolCallId of ["call_seen", "call_lost"]) {
      await appendActionLogEntry(db, {
        runId: run.id,
        toolCallId,
        tool: "fetch",
        arguments: { url: `https://example.org/${toolCallId}` },
        reasoning: "",
        result: { ok: true, value: `Page for ${toolCallId}` },
        dataSeen: [],
        recordsWritten: [],
      });
    }
    await endRun(db, run.id, { status: "stopped" });

    const lost = await resultsCutOff(db, context.chat.id);
    expect(lost.map((entry) => entry.toolCallId)).toEqual(["call_lost"]);
    const opening = await openingMessageFor(
      db,
      prompts,
      context.chat,
      [{ kind: "schedule", schedule: "test" }],
      new Date(),
    );
    expect(opening).toContain("Your last run was cut off after these calls finished");
    expect(opening).toContain('fetch {"url":"https://example.org/call_lost"}\nPage for call_lost');
    expect(opening).not.toContain("Page for call_seen");
  });
});
