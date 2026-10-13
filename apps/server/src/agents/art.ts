import { and, asc, desc, eq, isNull, sql } from "drizzle-orm";
import { Type } from "typebox";
import { toCardOut } from "../cards/out.ts";
import type { Db } from "../db/client.ts";
import { card, harnessRecord, subtopic, topic } from "../db/schema.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import { ArtRecord, CLOSED, Id, RenderRecord } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError } from "../harness/tools.ts";
import { log } from "../log.ts";
import type { AgentDeps } from "./context.ts";
import { metaOf } from "./tiers.ts";

/*
 * designer_toad's art (harness-tools.md, task 0045): it draws every accepted card's ASCII art
 * itself, sees it on the real card at a phone's width, and attaches only art it has seen. The
 * width and the character set are checked here, not asked for.
 */

/** The widest line a phone shows without wrapping (ADR-0021). */
export const ART_COLUMNS = 40;
export const ART_LINES = 24;

type CardRow = typeof card.$inferSelect;

/** The art as it is stored: no carriage returns, no trailing spaces, no blank lines around it. */
export function normalizeArt(art: string): string {
  const lines = art
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.trimEnd());
  while (lines.length > 0 && lines[0] === "") lines.shift();
  while (lines.length > 0 && lines.at(-1) === "") lines.pop();
  return lines.join("\n");
}

/** Every fault of the art, named: too wide, too tall, or a character outside printable ASCII. */
export function artProblems(art: string): string[] {
  const problems: string[] = [];
  const lines = art.split("\n");
  if (art.trim() === "") return ["the art is empty"];
  if (lines.length > ART_LINES) problems.push(`it is ${lines.length} lines tall; at most ${ART_LINES}`);
  lines.forEach((line, index) => {
    if (line.length > ART_COLUMNS)
      problems.push(`line ${index + 1} is ${line.length} columns; at most ${ART_COLUMNS}`);
  });
  const outside = new Set<string>();
  for (const character of art) {
    if (character === "\n") continue;
    const code = character.codePointAt(0) ?? 0;
    if (code < 0x20 || code > 0x7e) outside.add(character);
  }
  if (outside.size > 0) {
    const shown = [...outside].slice(0, 8).map((character) => JSON.stringify(character));
    problems.push(`only printable ASCII draws the same everywhere; it has ${shown.join(", ")}`);
  }
  return problems;
}

function topicOfDesigner(context: ToolContext): string {
  if (!context.chat.topicId) throw new ToolError("Only a topic's designer_toad draws its art.");
  return context.chat.topicId;
}

/** The topic's accepted cards still waiting for art. */
function waitingForArt(db: Db, topicId: string) {
  return db
    .select({ card, subtopicTitle: subtopic.title, difficulty: subtopic.difficulty })
    .from(card)
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(
      and(
        eq(card.topicId, topicId),
        eq(card.status, "draft"),
        sql`${card.genMeta} ->> 'stage' = 'accepted'`,
        isNull(card.visualKind),
      ),
    )
    .orderBy(asc(card.createdAt));
}

async function waitingCard(
  context: ToolContext,
  id: string,
): Promise<{ row: CardRow; subtopicTitle: string }> {
  const topicId = topicOfDesigner(context);
  const waiting = await waitingForArt(context.db, topicId);
  const found = waiting.find((one) => one.card.id === id);
  if (!found)
    throw new ToolError(`Card ${id} isn't waiting for art: list_art_requests shows the ones that are.`);
  return { row: found.card, subtopicTitle: found.subtopicTitle };
}

export function listArtRequestsTool(deps: AgentDeps): HarnessTool {
  return {
    name: "list_art_requests",
    label: "List cards waiting for art",
    description: deps.prompts.render("tools/list-art-requests.njk", {}),
    parameters: Type.Object({}, CLOSED),
    kind: "read",
    async execute(_params, context) {
      const waiting = await waitingForArt(context.db, topicOfDesigner(context));
      const cards = waiting.map((one) => ({
        ...one.card,
        meta: metaOf(one.card),
        subtopicTitle: one.subtopicTitle,
      }));
      return {
        value: deps.prompts.render("tool-results/art-requests.njk", { cards }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const ArtParameters = Type.Object(
  {
    card: Id,
    art: Type.String({
      minLength: 1,
      description: `The ASCII art: printable ASCII, at most ${ART_COLUMNS} columns`,
    }),
    alt: Type.String({ minLength: 1, maxLength: 160, description: "One line saying what the art shows" }),
  },
  CLOSED,
);

export function renderArtTool(deps: AgentDeps): HarnessTool<typeof ArtParameters> {
  return {
    name: "render_art",
    label: "Render art on the card",
    description: deps.prompts.render("tools/render-art.njk", { columns: ART_COLUMNS, lines: ART_LINES }),
    parameters: ArtParameters,
    kind: "change",
    async execute(params, context) {
      const { row, subtopicTitle } = await waitingCard(context, params.card);
      const art = normalizeArt(params.art);
      const problems = artProblems(art);
      if (problems.length > 0)
        throw new ToolError(`Nothing was rendered; fix every problem:\n- ${problems.join("\n- ")}`);
      const [named] = await context.db
        .select({ name: topic.canonicalName })
        .from(topic)
        .where(eq(topic.id, row.topicId));
      const render = await createRecord(context.db, RenderRecord, {
        kind: "render",
        author: context.author,
        body: { card: row.id, art },
      });
      const shown = {
        ...row,
        visualId: render.id,
        visualKind: "ascii" as const,
        visualSlots: { art, alt: params.alt },
      };
      let png: Buffer;
      try {
        png = await deps.browser.renderCard(
          { card: toCardOut(shown, subtopicTitle), topicName: named?.name ?? "" },
          context.signal,
        );
      } catch (error) {
        log.warn({ err: error, card: row.id }, "a card wouldn't render");
        throw new ToolError("The card couldn't be rendered just now. Render it again in a moment.");
      }
      const stored = await recordsStored(context.db, deps.prompts, [render]);
      return {
        ...stored,
        value: `${String(stored.value)}\nThe card with this art, as a reader sees it on a phone, is attached. If it reads well, attach_art the same art; if not, draw it again.`,
        images: [{ data: png.toString("base64"), mimeType: "image/png" }],
      };
    },
  };
}

export function attachArtTool(deps: AgentDeps): HarnessTool<typeof ArtParameters> {
  return {
    name: "attach_art",
    label: "Attach art to the card",
    description: deps.prompts.render("tools/attach-art.njk", {}),
    parameters: ArtParameters,
    kind: "change",
    async execute(params, context) {
      const { row } = await waitingCard(context, params.card);
      const art = normalizeArt(params.art);
      // Only art seen on the card in this run goes live: the render is the check.
      const [rendered] = await context.db
        .select({ id: harnessRecord.id })
        .from(harnessRecord)
        .where(
          and(
            eq(harnessRecord.kind, "render"),
            sql`${harnessRecord.author} ->> 'runId' = ${context.run.id}`,
            sql`${harnessRecord.body} ->> 'card' = ${row.id}`,
            sql`${harnessRecord.body} ->> 'art' = ${art}`,
          ),
        )
        .orderBy(desc(harnessRecord.seq))
        .limit(1);
      if (!rendered)
        throw new ToolError("This run hasn't rendered that exact art on that card: render_art it first.");
      const render = await readLatestRecord(context.db, RenderRecord, "render", rendered.id);
      const attached = await context.db.transaction(async (tx) => {
        await tx
          .update(card)
          .set({ visualId: render.id, visualKind: "ascii", visualSlots: { art, alt: params.alt.trim() } })
          .where(eq(card.id, row.id));
        return createRecord(tx, ArtRecord, {
          kind: "art",
          author: context.author,
          body: { card: row.id, render: refOf(render), writer: metaOf(row).writer },
        });
      });
      return recordsStored(context.db, deps.prompts, [attached]);
    },
  };
}
