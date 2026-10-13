import { and, eq, sql } from "drizzle-orm";
import { Type } from "typebox";
import type { Db } from "../db/client.ts";
import { harnessRecord } from "../db/schema.ts";
import { recordsStored } from "../harness/outputs.ts";
import { changeRecord, createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import { CLOSED, Id, MAP_KINDS, MapItem, MapRecord, Text } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { passageExists } from "./pages.ts";

/*
 * ADR-0100's maps, A to J, before any prose (corpus-authoring-system.md, task 0045): each a
 * versioned record. Code checks what each map must carry and that every cited passage exists.
 */

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
      await checkMap(context.db, params.map, params.items);
      const map = await createRecord(context.db, MapRecord, {
        kind: "map",
        author: context.author,
        body: { topic: topicId, map: params.map, items: params.items, summary: params.summary },
      });
      return recordsStored(context.db, deps.prompts, [map]);
    },
  };
}

const ChangeMapParameters = Type.Object({ map: Id, reason: Text, ...MapBody }, CLOSED);

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
      await checkMap(context.db, latest.body.map, params.items);
      const changed = await changeRecord(context.db, MapRecord, {
        from: refOf(latest),
        status: "active",
        author: context.author,
        reason: params.reason,
        body: { ...latest.body, items: params.items, summary: params.summary },
      });
      return recordsStored(context.db, deps.prompts, [changed]);
    },
  };
}

function topicOf(context: ToolContext): string {
  if (!context.chat.topicId) throw new ToolError("Only a topic's tadpole writes its maps.");
  return context.chat.topicId;
}

/** A topic's map of one kind, its latest version. */
export async function mapOf(db: Db, topicId: string, kind: string): Promise<MapRecord | undefined> {
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
    if (kind === "D" && (!item.sourceTier || item.evidence.length === 0)) {
      problems.push(`${where}: an evidence entry names its source tier and cites its passages`);
    }
    if (kind === "B" && !item.after)
      problems.push(`${where}: give \`after\`, empty when nothing comes first`);
    if (kind === "J" && !item.checkBy) problems.push(`${where}: a time-sensitive claim gives \`checkBy\``);
    for (const cited of item.evidence) {
      if (!(await passageExists(db, cited.page, cited.passage))) {
        problems.push(`${where}: page ${cited.page} has no stored passage ${cited.passage}`);
      }
    }
  }
  if (kind === "B") problems.push(...graphProblems(items, names));
  if (problems.length > 0) {
    throw new ToolError(`Nothing was stored; fix every problem and call again:\n- ${problems.join("\n- ")}`);
  }
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
