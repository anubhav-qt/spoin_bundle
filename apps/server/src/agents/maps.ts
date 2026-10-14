import { isDeepStrictEqual } from "node:util";
import type { Tool } from "@spoin/pi-ai";
import { and, eq, sql } from "drizzle-orm";
import { Type } from "typebox";
import type { Db, Tx } from "../db/client.ts";
import { harnessRecord, page, pagePassage } from "../db/schema.ts";
import { intakeOf } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import {
  changeRecord,
  createRecord,
  listTopicRecords,
  readLatestRecord,
  readRecord,
  refOf,
} from "../harness/records.ts";
import {
  CLOSED,
  FindingRecord,
  Id,
  MAP_KINDS,
  MapAuditRecord,
  MapItem,
  MapRecord,
  type SOURCE_TIERS,
  Text,
} from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolOutput } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { passageExists } from "./pages.ts";

/*
 * ADR-0100's maps, A to J, before any prose (corpus-authoring-system.md, task 0045): each a
 * versioned record. Code checks what each map must carry and that every cited passage exists, and
 * before the maps go to toad_sage, that they hold together, are big enough for the topic's cards,
 * and have been audited against their passages by a call the tadpole doesn't brief (ADR-0110).
 */

type Conn = Db | Tx;
type SourceTier = (typeof SOURCE_TIERS)[number];

/**
 * How many cards one claim grounds, at most, and one misconception (the owner's ratios,
 * 2026-10-14): the first maps held 18 to 31 claims and 8 misconceptions for topics of 450 to 700
 * cards, and the myth-vs-fact cards, a tenth of every tier, are written from map F.
 */
export const CARDS_PER_CLAIM = 3;
export const CARDS_PER_MISCONCEPTION = 10;

/** The claims and misconceptions a topic's maps must hold for its cards. */
export function claimsNeeded(cardCount: number): number {
  return Math.ceil(cardCount / CARDS_PER_CLAIM);
}

export function misconceptionsNeeded(cardCount: number): number {
  return Math.ceil(cardCount / CARDS_PER_MISCONCEPTION);
}

/**
 * The tiers a high confidence can stand on alone. A recognised expert needs a second one that
 * agrees, and a community heuristic carries only a low confidence: the first maps rated all 69 of
 * their claims high, a blog's included.
 */
const HIGH_ALONE: readonly SourceTier[] = [
  "primary_specification",
  "official_documentation",
  "primary_research",
  "authoritative_textbook",
];
const MEDIUM_AT_LEAST: readonly SourceTier[] = [...HIGH_ALONE, "recognised_expert", "secondary_synthesis"];

/** The auditor reads this many claims and misconceptions in one call, with their passages. */
const AUDIT_BATCH = 15;
/** And makes this many calls at once. */
const AUDIT_CALLS_AT_ONCE = 4;

/** The maps the evidence auditor reads: what Spoin will teach as true, and what it will correct. */
const AUDITED_MAPS = ["C", "F"] as const;

const MapBody = {
  items: Type.Array(MapItem, { minItems: 1 }),
  summary: Type.String({ minLength: 1, description: "What the map says, and what it leaves open" }),
};

const WriteMapParameters = Type.Object({ map: Type.Enum([...MAP_KINDS]), ...MapBody }, CLOSED);

export function writeMapTool(deps: AgentDeps): HarnessTool<typeof WriteMapParameters> {
  return {
    name: "write_map",
    label: "Write a map",
    description: deps.prompts.render("tools/write-map.njk", {}),
    parameters: WriteMapParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = topicOf(context);
      const existing = await mapOf(context.db, topicId, params.map);
      if (existing) {
        throw new ToolError(`Map ${params.map} exists already (${existing.id}): change it with change_map.`);
      }
      // The domains come first: the helpers research one each and every claim names one. The System
      // Design tadpole of the stage 2 rerun searched alone for an hour with no map A.
      if (params.map !== "A" && !(await mapOf(context.db, topicId, "A"))) {
        throw new ToolError(
          "Write map A first: the domains, which your helpers research one each and every claim names.",
        );
      }
      await checkMap(context.db, params.map, params.items);
      const map = await createRecord(context.db, MapRecord, {
        kind: "map",
        author: context.author,
        body: { topic: topicId, map: params.map, items: params.items, summary: params.summary },
      });
      return withShortfall(context.db, topicId, map, await recordsStored(context.db, deps.prompts, [map]));
    },
  };
}

const ChangeMapParameters = Type.Object(
  {
    map: Id,
    reason: Text,
    items: Type.Optional(
      Type.Array(MapItem, {
        description: "Items to add, or to put in place of the item of the same name",
      }),
    ),
    drop: Type.Optional(Type.Array(Text, { description: "The names of items to take out" })),
    summary: Type.Optional(
      Type.String({ minLength: 1, description: "The map's new summary, when it changes" }),
    ),
  },
  CLOSED,
);

/**
 * A map's next version from only what changes, as a document's sections are: a claim inventory of
 * 234 claims is never sent whole again to fix one.
 */
export function changeMapTool(deps: AgentDeps): HarnessTool<typeof ChangeMapParameters> {
  return {
    name: "change_map",
    label: "Change a map",
    description: deps.prompts.render("tools/change-map.njk", {}),
    parameters: ChangeMapParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = topicOf(context);
      const [row] = await context.db
        .select({ id: harnessRecord.id })
        .from(harnessRecord)
        .where(and(eq(harnessRecord.kind, "map"), eq(harnessRecord.id, params.map)))
        .limit(1);
      if (!row) throw new ToolError(`There is no map ${params.map}.`);
      const latest = await readLatestRecord(context.db, MapRecord, "map", params.map);
      if (latest.body.topic !== topicId) throw new ToolError(`Map ${params.map} is another topic's.`);
      const items = mergeMapItems(latest.body.items, params.items ?? [], params.drop ?? []);
      await checkMap(context.db, latest.body.map, items);
      let summary = latest.body.summary;
      if (params.summary) summary = params.summary;
      const changed = await changeRecord(context.db, MapRecord, {
        from: refOf(latest),
        status: "active",
        author: context.author,
        reason: params.reason,
        body: { ...latest.body, items, summary },
      });
      return withShortfall(
        context.db,
        topicId,
        changed,
        await recordsStored(context.db, deps.prompts, [changed]),
      );
    },
  };
}

/** A map's items once a change is made: each item given replaces its namesake where it stood, a new one goes last. */
export function mergeMapItems(items: MapItem[], changes: MapItem[], drop: string[]): MapItem[] {
  const unknown = drop.filter((name) => !items.some((item) => item.name === name));
  if (unknown.length > 0) throw new ToolError(`The map has no item named ${unknown.join(", ")} to drop.`);
  if (changes.length === 0 && drop.length === 0) {
    throw new ToolError("Give the items that change, or the names to drop.");
  }
  const merged = items.filter((item) => !drop.includes(item.name));
  for (const change of changes) {
    const at = merged.findIndex((item) => item.name === change.name);
    if (at === -1) merged.push(change);
    else merged[at] = change;
  }
  if (merged.length === 0) throw new ToolError("A map keeps at least one item.");
  return merged;
}

/**
 * A map C or F short of the topic's floor says so as it is written, not only at the audit: the
 * Gita's tadpole wrote 18 claims for 450 cards and learned it needed 150 only when it was done.
 */
async function withShortfall(
  db: Conn,
  topicId: string,
  map: MapRecord,
  output: ToolOutput,
): Promise<ToolOutput> {
  const intake = await intakeOf(db, topicId);
  if (!intake) return output;
  const cardCount = intake.body.cardCount;
  const count = map.body.items.length;
  let note = "";
  if (map.body.map === "C" && count < claimsNeeded(cardCount)) {
    note = `Map C holds ${count} claims, and the topic's ${cardCount} cards need at least ${claimsNeeded(cardCount)}: add ${claimsNeeded(cardCount) - count} more with change_map, domain by domain.`;
  }
  if (map.body.map === "F" && count < misconceptionsNeeded(cardCount)) {
    note = `Map F holds ${count} misconceptions, and the topic's ${cardCount} cards need at least ${misconceptionsNeeded(cardCount)}: add ${misconceptionsNeeded(cardCount) - count} more with change_map.`;
  }
  if (!note) return output;
  return { ...output, value: `${String(output.value)}\n${note}` };
}

function topicOf(context: ToolContext): string {
  if (!context.chat.topicId) throw new ToolError("Only a topic's tadpole writes its maps.");
  return context.chat.topicId;
}

/** A topic's map of one kind, its latest version. */
export async function mapOf(db: Conn, topicId: string, kind: string): Promise<MapRecord | undefined> {
  const [first] = await db
    .select({ id: harnessRecord.id })
    .from(harnessRecord)
    .where(
      and(
        eq(harnessRecord.kind, "map"),
        eq(harnessRecord.version, 1),
        sql`${harnessRecord.body} ->> 'topic' = ${topicId}`,
        sql`${harnessRecord.body} ->> 'map' = ${kind}`,
      ),
    )
    .limit(1);
  if (!first) return undefined;
  return readLatestRecord(db, MapRecord, "map", first.id);
}

/** Every problem with a map's items, named at once: what its kind must carry, and its evidence. */
async function checkMap(db: Db, kind: string, items: MapItem[]): Promise<void> {
  const problems = itemProblems(kind, items);
  for (const item of items) {
    for (const cited of item.evidence) {
      if (!(await passageExists(db, cited.page, cited.passage))) {
        problems.push(`"${item.name}": page ${cited.page} has no stored passage ${cited.passage}`);
      }
    }
  }
  if (problems.length > 0) {
    throw new ToolError(`Nothing was stored; fix every problem and call again:\n- ${problems.join("\n- ")}`);
  }
}

/** What each item of a map of this kind must carry, every problem named. */
export function itemProblems(kind: string, items: MapItem[]): string[] {
  const problems: string[] = [];
  const names = new Set<string>();
  for (const item of items) {
    if (names.has(item.name)) problems.push(`two items are named "${item.name}": names are unique in a map`);
    names.add(item.name);
  }
  for (const item of items) {
    const where = `"${item.name}"`;
    if (kind === "C" && (!item.claimType || !item.scope || !item.confidence)) {
      problems.push(`${where}: a claim carries its claimType, scope and confidence`);
    }
    if (kind === "C" && item.evidence.length === 0) {
      problems.push(`${where}: a claim cites the passages it rests on, or it belongs in map I as a gap`);
    }
    if (kind === "C" && !item.domain) {
      problems.push(`${where}: a claim names its domain, an item of map A`);
    }
    if (kind === "C" && item.claimType === "implementation" && !item.appliesTo) {
      problems.push(
        `${where}: an implementation claim gives appliesTo, the product and version it is true of`,
      );
    }
    if (kind === "D" && (!item.sourceTier || item.evidence.length === 0)) {
      problems.push(`${where}: an evidence entry names its source tier and cites its passages`);
    }
    if (kind === "D" && !item.sourceDate) {
      problems.push(`${where}: a source gives sourceDate, when it was published or the version it documents`);
    }
    if (kind === "B" && !item.after)
      problems.push(`${where}: give \`after\`, empty when nothing comes first`);
    if (kind === "J" && !item.checkBy) problems.push(`${where}: a time-sensitive claim gives \`checkBy\``);
  }
  if (kind === "B") problems.push(...graphProblems(items, names));
  return problems;
}

/** Map B's edges name its own items, and form no cycle: a cycle means a concept needs splitting. */
function graphProblems(items: MapItem[], names: Set<string>): string[] {
  const problems: string[] = [];
  const edges = new Map<string, string[]>();
  for (const item of items) {
    const after = item.after ?? [];
    for (const name of after) {
      if (!names.has(name))
        problems.push(`"${item.name}": \`after\` names "${name}", which is not in the map`);
    }
    edges.set(
      item.name,
      after.filter((name) => names.has(name)),
    );
  }
  const state = new Map<string, "open" | "done">();
  const visit = (name: string, path: string[]): string[] | null => {
    state.set(name, "open");
    for (const next of edges.get(name) ?? []) {
      if (state.get(next) === "open") return [...path, name, next];
      if (!state.has(next)) {
        const cycle = visit(next, [...path, name]);
        if (cycle) return cycle;
      }
    }
    state.set(name, "done");
    return null;
  };
  for (const name of edges.keys()) {
    if (state.has(name)) continue;
    const cycle = visit(name, []);
    if (cycle) {
      problems.push(`the prerequisites loop: ${cycle.join(" after ")}; split a concept to break it`);
      break;
    }
  }
  return problems;
}

/** A topic's maps by kind, each its latest version. */
export type TopicMaps = Partial<Record<(typeof MAP_KINDS)[number], MapRecord>>;

export async function mapsOf(db: Conn, topicId: string): Promise<TopicMaps> {
  const maps: TopicMaps = {};
  for (const map of await listTopicRecords(db, MapRecord, "map", topicId)) maps[map.body.map] = map;
  return maps;
}

function itemsOf(maps: TopicMaps, kind: (typeof MAP_KINDS)[number]): MapItem[] {
  const map = maps[kind];
  if (!map) return [];
  return map.body.items;
}

/** A source of map D, by the pages it cites: one entry per publication. */
interface Source {
  name: string;
  tier: SourceTier;
  date: string;
}

/** Each cited page's source, and every page claimed by two sources. */
function sourcesByPage(maps: TopicMaps): { byPage: Map<string, Source>; problems: string[] } {
  const byPage = new Map<string, Source>();
  const problems: string[] = [];
  for (const entry of itemsOf(maps, "D")) {
    if (!entry.sourceTier) continue;
    const source = { name: entry.name, tier: entry.sourceTier, date: entry.sourceDate ?? "undated" };
    for (const cited of entry.evidence) {
      const before = byPage.get(cited.page);
      if (before && before.name !== source.name) {
        problems.push(
          `map D: page ${cited.page} is in both "${before.name}" and "${source.name}": a page belongs to one source, and a source is one publication`,
        );
      }
      byPage.set(cited.page, source);
    }
  }
  return { byPage, problems };
}

/** The sources a claim rests on, by the pages it cites. */
function sourcesOfItem(item: MapItem, byPage: Map<string, Source>): Source[] {
  const found = new Map<string, Source>();
  for (const cited of item.evidence) {
    const source = byPage.get(cited.page);
    if (source) found.set(source.name, source);
  }
  return [...found.values()];
}

/** Why a claim's class or confidence claims more than its sources give, if it does. */
function standingProblems(claim: MapItem, sources: Source[]): string[] {
  const problems: string[] = [];
  const where = `map C "${claim.name}"`;
  const tiers = sources.map((source) => source.tier);
  if (claim.claimType === "empirical" && !tiers.includes("primary_research")) {
    problems.push(
      `${where}: an empirical claim is measured, with a population and conditions, so it cites the primary research that measured it; otherwise label it for what its sources are`,
    );
  }
  if (claim.confidence === "high") {
    const alone = tiers.some((tier) => HIGH_ALONE.includes(tier));
    const experts = tiers.filter((tier) => tier === "recognised_expert").length;
    if (!alone && experts < 2) {
      problems.push(
        `${where}: high confidence stands on a specification, official documentation, primary research or an authoritative textbook, or on two recognised experts that agree; its sources are ${describeTiers(sources)}`,
      );
    }
  }
  if (claim.confidence === "medium" && !tiers.some((tier) => MEDIUM_AT_LEAST.includes(tier))) {
    problems.push(
      `${where}: medium confidence needs a source of secondary synthesis or better; its sources are ${describeTiers(sources)}`,
    );
  }
  return problems;
}

function describeTiers(sources: Source[]): string {
  if (sources.length === 0) return "none in map D";
  return sources.map((source) => `"${source.name}" (${source.tier.replaceAll("_", " ")})`).join(", ");
}

/**
 * Why the maps don't hold together yet (ADR-0110), every problem named at once: all ten written;
 * every claim's and gap's domain an item of map A; every cited page in one source of map D; each
 * claim's confidence and class no more than its sources give; every domain taught from two
 * sources or named a gap; and enough claims and misconceptions for the topic's cards.
 */
export function mapsProblems(maps: TopicMaps, cardCount: number): string[] {
  const problems: string[] = [];
  const missing = MAP_KINDS.filter((kind) => !maps[kind]);
  if (missing.length > 0) problems.push(`write map ${missing.join(", ")} first`);
  const domains = new Set(itemsOf(maps, "A").map((item) => item.name));
  const claims = itemsOf(maps, "C");
  const gaps = itemsOf(maps, "I");
  const { byPage, problems: sourceProblems } = sourcesByPage(maps);
  problems.push(...sourceProblems);
  for (const item of [...claims, ...gaps]) {
    if (item.domain && !domains.has(item.domain)) {
      problems.push(`"${item.name}" names the domain "${item.domain}", which is not an item of map A`);
    }
  }
  const unsourced = new Set<string>();
  for (const claim of claims) {
    for (const cited of claim.evidence) {
      if (!byPage.has(cited.page)) unsourced.add(cited.page);
    }
    problems.push(...standingProblems(claim, sourcesOfItem(claim, byPage)));
  }
  for (const pageId of unsourced) {
    problems.push(
      `map C cites page ${pageId}, which no source of map D names: give its publication an entry`,
    );
  }
  for (const domain of domains) {
    if (gaps.some((gap) => gap.domain === domain)) continue;
    const taught = claims.filter((claim) => claim.domain === domain);
    const sources = new Set(
      taught.flatMap((claim) => sourcesOfItem(claim, byPage).map((source) => source.name)),
    );
    if (taught.length === 0) {
      problems.push(
        `the domain "${domain}" has no claim in map C: research it, or name it in map I as a gap`,
      );
    } else if (sources.size < 2) {
      let resting = "no source of map D";
      if (sources.size === 1) resting = `one source, "${[...sources][0]}"`;
      problems.push(
        `the domain "${domain}" rests on ${resting}: find a second, or name what is missing in map I as a gap of the domain`,
      );
    }
  }
  const neededClaims = claimsNeeded(cardCount);
  if (maps.C && claims.length < neededClaims) {
    problems.push(
      `map C holds ${claims.length} claims, and the topic's ${cardCount} cards need at least ${neededClaims}, one for every ${CARDS_PER_CLAIM} cards: add them with change_map`,
    );
  }
  const misconceptions = itemsOf(maps, "F");
  const neededMisconceptions = misconceptionsNeeded(cardCount);
  if (maps.F && misconceptions.length < neededMisconceptions) {
    problems.push(
      `map F holds ${misconceptions.length} misconceptions, and the topic's ${cardCount} cards need at least ${neededMisconceptions}, one for every ${CARDS_PER_MISCONCEPTION} cards, since a tenth of them are myth-vs-fact cards`,
    );
  }
  return problems;
}

/** A finding as the facts show it: where, what, and how it was settled. */
export interface FactsFinding {
  item: string;
  problem: string;
  settled: { how: "fixed" | "kept"; note: string } | null;
}

function countBy(items: MapItem[], key: "confidence" | "claimType" | "scope"): string {
  const counts = new Map<string, number>();
  for (const item of items) {
    const value = item[key] ?? "unstated";
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()].map(([value, count]) => `${value} ${count}`).join(", ");
}

/**
 * What code counted in the maps, for toad_sage to review beside the tadpole's note (ADR-0110): the
 * first maps went on six times on the tadpole's own description of them.
 */
export function mapsFacts(maps: TopicMaps, cardCount: number, findings: FactsFinding[]): string {
  const lines: string[] = [];
  const claims = itemsOf(maps, "C");
  const gaps = itemsOf(maps, "I");
  const { byPage } = sourcesByPage(maps);
  lines.push(
    `Cards: ${cardCount}. Claims in map C: ${claims.length} (at least ${claimsNeeded(cardCount)}). Misconceptions in map F: ${itemsOf(maps, "F").length} (at least ${misconceptionsNeeded(cardCount)}).`,
  );
  lines.push(`Claims by confidence: ${countBy(claims, "confidence")}.`);
  lines.push(`By class: ${countBy(claims, "claimType")}.`);
  lines.push(`By scope: ${countBy(claims, "scope")}.`);
  lines.push("", "Each domain of map A, with its claims and the sources they rest on:");
  for (const domain of itemsOf(maps, "A")) {
    const taught = claims.filter((claim) => claim.domain === domain.name);
    const sources = new Map<string, Source>();
    for (const claim of taught) {
      for (const source of sourcesOfItem(claim, byPage)) sources.set(source.name, source);
    }
    const named = [...sources.values()].map(
      (source) => `${source.name} (${source.tier.replaceAll("_", " ")}, ${source.date})`,
    );
    let line = `- ${domain.name}: ${taught.length} claims`;
    if (named.length > 0) line += `, from ${named.join("; ")}`;
    const gap = gaps.find((one) => one.domain === domain.name);
    if (gap) line += `. Gap: ${gap.text}`;
    lines.push(line);
  }
  lines.push("", "The sources of map D:");
  for (const entry of itemsOf(maps, "D")) {
    const citing = claims.filter((claim) =>
      claim.evidence.some((cited) => byPage.get(cited.page)?.name === entry.name),
    ).length;
    const pages = new Set(entry.evidence.map((cited) => cited.page)).size;
    lines.push(
      `- ${entry.name}: ${(entry.sourceTier ?? "no tier").replaceAll("_", " ")}, ${entry.sourceDate ?? "undated"}; ${pages} pages, cited by ${citing} claims`,
    );
  }
  const fixed = findings.filter((finding) => finding.settled?.how === "fixed").length;
  const kept = findings.filter((finding) => finding.settled?.how === "kept");
  lines.push(
    "",
    `The evidence auditor's findings: ${findings.length}, ${fixed} fixed, ${kept.length} kept as they were.`,
  );
  for (const finding of kept) {
    lines.push(
      `- kept, ${finding.item}: ${finding.problem} The tadpole's reason: ${finding.settled?.note ?? ""}`,
    );
  }
  return lines.join("\n");
}

/** The topic's map audits, oldest first. */
async function mapAuditsOf(db: Conn, topicId: string) {
  return listTopicRecords(db, MapAuditRecord, "map_audit", topicId);
}

/** Every finding of the topic's map audits, latest versions. */
async function mapFindingsOf(db: Conn, topicId: string) {
  const audits = new Set((await mapAuditsOf(db, topicId)).map((audit) => audit.id));
  const findings = await listTopicRecords(db, FindingRecord, "finding", topicId);
  return findings.filter((finding) => audits.has(finding.body.audit.id));
}

/**
 * Why the evidence auditor's finding can't be settled so, if it can't (ADR-0110). It is never
 * kept, since the auditor read the passages and a reason is only the tadpole's word: in the stage
 * 2 rerun Rust's tadpole kept 104 of 126, "standard syntax; kept" on claims their passages don't
 * make, and toad_sage went on from those reasons. And it is fixed only once its item changed or
 * went, so the next audit reads what was fixed.
 */
export async function mapFindingRefusal(
  db: Conn,
  finding: FindingRecord,
  how: "fixed" | "kept",
): Promise<string | undefined> {
  const key = finding.body.item ?? "";
  if (how === "kept") {
    return `The evidence auditor's findings are fixed, never kept: change ${key} with change_map so it says only what its passages say (cite a passage that says it, narrow it, label it lower, or drop it), then settle this as fixed.`;
  }
  const at = key.indexOf("/");
  const kind = key.slice(0, at);
  const name = key.slice(at + 1);
  const audit = await readRecord(db, MapAuditRecord, finding.body.audit);
  for (const ref of audit.body.maps) {
    const audited = await readRecord(db, MapRecord, ref);
    if (audited.body.map !== kind) continue;
    const before = audited.body.items.find((item) => item.name === name);
    const latest = await readLatestRecord(db, MapRecord, "map", ref.id);
    const now = latest.body.items.find((item) => item.name === name);
    if (before && now && isDeepStrictEqual(before, now)) {
      return `${key} hasn't changed since the audit that found this: change it with change_map first, or drop it.`;
    }
  }
  return undefined;
}

/** The topic's card count, from its intake. */
async function cardCountOf(db: Conn, topicId: string): Promise<number> {
  const intake = await intakeOf(db, topicId);
  if (!intake) throw new ToolError("The topic has no intake to size its maps by.");
  return intake.body.cardCount;
}

/**
 * Why the maps can't go to toad_sage yet: they don't hold together, the latest of maps C and F
 * haven't been audited, or a finding isn't settled. Empty when they can.
 */
export async function mapsHandoverProblems(db: Conn, topicId: string): Promise<string[]> {
  const maps = await mapsOf(db, topicId);
  const problems = mapsProblems(maps, await cardCountOf(db, topicId));
  if (problems.length > 0) return problems;
  const audits = await mapAuditsOf(db, topicId);
  const last = audits.at(-1);
  if (!last) return ["The maps have never been audited: call audit_maps."];
  for (const kind of AUDITED_MAPS) {
    const map = maps[kind];
    const audited = last.body.maps.find((ref) => ref.id === map?.id);
    if (map && audited?.version !== map.version) {
      problems.push(`Map ${kind} changed after the last audit: call audit_maps again.`);
    }
  }
  for (const finding of await mapFindingsOf(db, topicId)) {
    if (!finding.body.settled) problems.push(`Finding ${finding.id} (${finding.body.item}) is not settled.`);
  }
  return problems;
}

/** The facts the maps' handover carries to toad_sage. */
export async function mapsHandoverFacts(db: Conn, topicId: string): Promise<string> {
  const findings = (await mapFindingsOf(db, topicId)).map((finding) => ({
    item: finding.body.item ?? "the maps",
    problem: finding.body.problem,
    settled: finding.body.settled,
  }));
  return mapsFacts(await mapsOf(db, topicId), await cardCountOf(db, topicId), findings);
}

/** A cited passage as the auditor reads it, with its page and source. */
interface CitedPassage {
  page: string;
  passage: number;
  url: string;
  title: string;
  text: string;
  source: string;
}

async function citedPassages(
  db: Conn,
  items: MapItem[],
  byPage: Map<string, Source>,
): Promise<Map<string, CitedPassage>> {
  const found = new Map<string, CitedPassage>();
  for (const item of items) {
    for (const cited of item.evidence) {
      const key = `${cited.page}#${cited.passage}`;
      if (found.has(key)) continue;
      const [row] = await db
        .select({ text: pagePassage.text, url: page.url, title: page.title })
        .from(pagePassage)
        .innerJoin(page, eq(page.id, pagePassage.pageId))
        .where(and(eq(pagePassage.pageId, cited.page), eq(pagePassage.ordinal, cited.passage)));
      if (!row) continue;
      const source = byPage.get(cited.page);
      let named = "no source in map D";
      if (source) named = `${source.name}, ${source.tier.replaceAll("_", " ")}, ${source.date}`;
      found.set(key, {
        page: cited.page,
        passage: cited.passage,
        url: row.url,
        title: row.title ?? "untitled",
        text: row.text,
        source: named,
      });
    }
  }
  return found;
}

/** The items of maps C and F that changed since the last audit read them, or all of them before one. */
async function itemsToAudit(db: Conn, topicId: string, maps: TopicMaps) {
  const last = (await mapAuditsOf(db, topicId)).at(-1);
  const toAudit: { key: string; kind: "C" | "F"; item: MapItem }[] = [];
  for (const kind of AUDITED_MAPS) {
    const map = maps[kind];
    if (!map) continue;
    let before: MapItem[] = [];
    const audited = last?.body.maps.find((ref) => ref.id === map.id);
    if (audited) before = (await readRecord(db, MapRecord, audited)).body.items;
    for (const item of map.body.items) {
      const same = before.find((one) => one.name === item.name);
      if (same && isDeepStrictEqual(same, item)) continue;
      toAudit.push({ key: `${kind}/${item.name}`, kind, item });
    }
  }
  return toAudit;
}

function batchesOf<Item>(items: Item[], size: number): Item[][] {
  const batches: Item[][] = [];
  for (let at = 0; at < items.length; at += size) batches.push(items.slice(at, at + size));
  return batches;
}

/**
 * The evidence auditor (ADR-0110, corpus-authoring-system.md role 12 brought to the maps): one
 * fixed call per batch of claims and misconceptions, reading each with the passages it cites, that
 * the tadpole doesn't brief. It reads only what changed since its last audit, so no item is paid
 * for twice.
 */
export function auditMapsTool(deps: AgentDeps): HarnessTool {
  const parameters = Type.Object({}, CLOSED);
  return {
    name: "audit_maps",
    label: "Audit the maps",
    description: deps.prompts.render("tools/audit-maps.njk", {}),
    parameters,
    kind: "change",
    async execute(_params, context) {
      const topicId = topicOf(context);
      const maps = await mapsOf(context.db, topicId);
      const problems = mapsProblems(maps, await cardCountOf(context.db, topicId));
      if (problems.length > 0) {
        throw new ToolError(
          `The maps don't hold together yet, and the audit reads them once they do:\n- ${problems.join("\n- ")}`,
        );
      }
      const toAudit = await itemsToAudit(context.db, topicId, maps);
      if (toAudit.length === 0) throw new ToolError("Nothing in maps C and F changed since the last audit.");
      const { byPage } = sourcesByPage(maps);
      const passages = await citedPassages(
        context.db,
        toAudit.map((one) => one.item),
        byPage,
      );
      const found: { item: string; problem: string; fix: string }[] = [];
      const batches = batchesOf(toAudit, AUDIT_BATCH);
      for (const round of batchesOf(batches, AUDIT_CALLS_AT_ONCE)) {
        const answers = await Promise.all(
          round.map((batch) => auditBatch(deps, context, batch, passages, maps)),
        );
        for (const answer of answers) found.push(...answer);
      }
      const audited = AUDITED_MAPS.flatMap((kind) => {
        const map = maps[kind];
        if (!map) return [];
        return [refOf(map)];
      });
      const stored = await context.db.transaction(async (tx) => {
        const audit = await createRecord(tx, MapAuditRecord, {
          kind: "map_audit",
          author: { kind: "code", component: "audit_maps" },
          body: { topic: topicId, maps: audited },
        });
        const records = [];
        for (const finding of found) {
          records.push(
            await createRecord(tx, FindingRecord, {
              kind: "finding",
              author: { kind: "code", component: "audit_maps" },
              body: {
                audit: refOf(audit),
                topic: topicId,
                auditor: "evidence",
                path: null,
                item: finding.item,
                problem: finding.problem,
                fix: finding.fix,
                settled: null,
              },
            }),
          );
        }
        return [audit, ...records];
      });
      const output = await recordsStored(context.db, deps.prompts, stored);
      return {
        ...output,
        value: `${String(output.value)}\nThe auditor read ${toAudit.length} items and found ${found.length} problems.`,
      };
    },
  };
}

/** One call of the evidence auditor on a batch, its findings named by the batch's own items. */
async function auditBatch(
  deps: AgentDeps,
  context: ToolContext,
  batch: { key: string; kind: "C" | "F"; item: MapItem }[],
  passages: Map<string, CitedPassage>,
  maps: TopicMaps,
): Promise<{ item: string; problem: string; fix: string }[]> {
  const keys = batch.map((one) => one.key);
  const findingsTool: Tool = {
    name: "report_findings",
    description: deps.prompts.render("tools/report-map-findings.njk", {}),
    parameters: Type.Object({
      findings: Type.Array(
        Type.Object({
          item: Type.Enum(keys, { description: "The item at fault, as its key: C/<name> or F/<name>" }),
          problem: Type.String({ minLength: 1, description: "What is wrong, quoting the words at fault" }),
          fix: Type.String({ minLength: 1, description: "What the item should say or carry instead" }),
        }),
      ),
    }),
  };
  const items = batch.map((one) => ({
    key: one.key,
    kind: one.kind,
    item: one.item,
    passages: one.item.evidence.flatMap((cited) => {
      const found = passages.get(`${cited.page}#${cited.passage}`);
      if (!found) return [];
      return [found];
    }),
  }));
  const domains = itemsOf(maps, "A").map((domain) => domain.name);
  const answer = (await deps.oneShot({
    systemPrompt: deps.prompts.render("auditors/maps.njk", {}),
    prompt: deps.prompts.render("auditors/map-items.njk", { items, domains }),
    tool: findingsTool,
    runId: context.run.id,
    signal: context.signal,
  })) as { findings: { item: string; problem: string; fix: string }[] };
  return answer.findings;
}
