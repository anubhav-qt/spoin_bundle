import { and, asc, desc, eq, inArray, isNull, or, sql } from "drizzle-orm";
import { Type } from "typebox";
import { toCardOut } from "../cards/out.ts";
import type { Db } from "../db/client.ts";
import { card, harnessRecord, subtopic, topic } from "../db/schema.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord, readLatestRecord, refOf } from "../harness/records.ts";
import { ArtRecord, CLOSED, Id, RenderRecord } from "../harness/schemas.ts";
import { type HarnessTool, type ToolContext, ToolError, type ToolImage } from "../harness/tools.ts";
import { log } from "../log.ts";
import type { AgentDeps } from "./context.ts";
import { type ArtKind, metaOf, putCardsLiveIfDone, tierById } from "./tiers.ts";

/*
 * designer_toad's art (harness-tools.md, task 0045): it draws every accepted card's ASCII art
 * itself, sees it on the real card at a phone's width, and attaches only art it has seen, a batch
 * of cards a call. The width, the character set and how much of it is text are checked here, not
 * asked for; the height is free (ADR-0099, ADR-0109). The art that completes a tier puts its cards
 * live.
 */

/** The widest line a phone shows without wrapping (ADR-0021). */
export const ART_COLUMNS = 40;

/** Cards a call: few calls, each with several screenshots to look at. */
export const ART_BATCH = 10;

/**
 * The style art is drawn in (ADR-0109): art first, its text only labels and a gag's one line. Art
 * attached in an older style is drawn again, live cards' too, after every card still waiting for
 * its first. Style 2 had the rules without the prompt's worked examples, and drew boxes of words;
 * style 3 had them but not the box check, and drew boxes padded with rows of `#`; style 4 passed
 * the box check with words inside round outlines. Style 5 adds high thinking and the owner's
 * picks of ASCII artists' pieces as examples.
 */
export const ART_STYLE = 5;

/** The characters boxes and tables are drawn with. */
const BOX_CHARACTERS = new Set(["+", "|", "=", "-", "#", "[", "]"]);

/**
 * How much of a piece may be text and boxes (ADR-0109): its words, its letters and its box
 * characters, each letters and boxes as a share of every character that isn't a space. The first
 * Rust run's gags had a median of 21 words, half their ink letters; its redraws were boxes, 56% box
 * characters. Art by ASCII artists at asciiart.eu is 3% letters and 19% box characters.
 */
export const ART_LIMITS: Record<ArtKind, { words: number; letters: number; boxes: number }> = {
  gag: { words: 12, letters: 0.3, boxes: 0.4 },
  informative: { words: 20, letters: 0.4, boxes: 0.45 },
};

/** A row of `#` runs standing in for text: alone on its line, or alone between a box's sides. */
const PADDING_ROW = /^[\s|+[\]]*#{3,}(?:\s+#{3,})*[\s|+[\]]*$/;
const PADDED_CELL = /\|\s+#{3,}\s+\|/;

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

/** The art's words: two letters or more, leaving out a run of one letter, which draws (`oo`, `wWw`). */
export function artWords(art: string): string[] {
  const words = art.match(/[A-Za-z][A-Za-z']*[A-Za-z]/g) ?? [];
  return words.filter((word) => new Set(word.toLowerCase().replaceAll("'", "")).size > 1);
}

/** The art's letters as a share of its characters that aren't spaces. */
export function letterShare(art: string): number {
  const ink = art.replace(/\s/g, "");
  if (ink.length === 0) return 0;
  return ink.replace(/[^A-Za-z]/g, "").length / ink.length;
}

/** The art's box characters as a share of its characters that aren't spaces. */
export function boxShare(art: string): number {
  const ink = [...art.replace(/\s/g, "")];
  if (ink.length === 0) return 0;
  const boxes = ink.filter((character) => BOX_CHARACTERS.has(character));
  return boxes.length / ink.length;
}

/** The numbers of the lines that are rows of `#` in place of text. */
export function paddedLines(art: string): number[] {
  const numbers: number[] = [];
  art.split("\n").forEach((line, index) => {
    if (PADDING_ROW.test(line) || PADDED_CELL.test(line)) numbers.push(index + 1);
  });
  return numbers;
}

/** A kind of art as a sentence names it. */
function kindName(kind: ArtKind): string {
  if (kind === "informative") return "an informative drawing";
  return "a gag";
}

/** Every fault of the art, named: too wide, a character outside printable ASCII, or too much text or box for its kind. */
export function artProblems(art: string, kind: ArtKind): string[] {
  const problems: string[] = [];
  const lines = art.split("\n");
  if (art.trim() === "") return ["the art is empty"];
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
  const limits = ART_LIMITS[kind];
  const words = artWords(art).length;
  if (words > limits.words) {
    problems.push(
      `it has ${words} words; ${kindName(kind)} has at most ${limits.words}: labels of 1 to 3 words, no sentences`,
    );
  }
  const letters = letterShare(art);
  if (letters > limits.letters) {
    problems.push(
      `${Math.round(letters * 100)}% of its characters are letters; ${kindName(kind)} has at most ${Math.round(limits.letters * 100)}%: draw more, write less`,
    );
  }
  const boxes = boxShare(art);
  if (boxes > limits.boxes) {
    problems.push(
      `${Math.round(boxes * 100)}% of its characters are box lines (${[...BOX_CHARACTERS].join(" ")}); ${kindName(kind)} has at most ${Math.round(limits.boxes * 100)}%: draw the thing itself, not boxes`,
    );
  }
  const padded = paddedLines(art);
  if (padded.length > 0) {
    problems.push(
      `line ${padded.join(", ")} is a row of # standing in for text: draw something there or leave it out`,
    );
  }
  return problems;
}

/** The limits as render_art's description states them. */
function artLimits() {
  const kinds = Object.entries(ART_LIMITS) as [ArtKind, (typeof ART_LIMITS)[ArtKind]][];
  return kinds.map(([kind, limits]) => ({
    name: kindName(kind),
    words: limits.words,
    letters: Math.round(limits.letters * 100),
    boxes: Math.round(limits.boxes * 100),
  }));
}

/** The kind of art the card asked for; a card listed for art always asked. */
function kindOf(waiting: { card: typeof card.$inferSelect }): ArtKind {
  const request = metaOf(waiting.card).art;
  if (!request) throw new ToolError(`Card ${waiting.card.id} asked for no art.`);
  return request.kind;
}

function topicOfDesigner(context: ToolContext): string {
  if (!context.chat.topicId) throw new ToolError("Only a topic's designer_toad draws its art.");
  return context.chat.topicId;
}

/**
 * The topic's cards waiting for art: accepted cards with none yet, which hold their tier back,
 * first; then cards, live ones too, whose art is an older style (ART_STYLE), to draw again.
 */
function waitingForArt(db: Db, topicId: string) {
  return db
    .select({ card, subtopicTitle: subtopic.title, difficulty: subtopic.difficulty })
    .from(card)
    .innerJoin(subtopic, eq(subtopic.id, card.subtopicId))
    .where(
      and(
        eq(card.topicId, topicId),
        sql`jsonb_typeof(${card.genMeta} -> 'art') = 'object'`,
        or(
          and(
            eq(card.status, "draft"),
            sql`${card.genMeta} ->> 'stage' = 'accepted'`,
            isNull(card.visualKind),
          ),
          and(
            inArray(card.status, ["draft", "active"]),
            eq(card.visualKind, "ascii"),
            sql`(${card.genMeta} ->> 'artStyle') is distinct from ${String(ART_STYLE)}`,
          ),
        ),
      ),
    )
    .orderBy(sql`${card.visualKind} nulls first`, asc(card.createdAt));
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
      // A batch at a time: every waiting card's body at once was more than the next batch needs.
      const cards = waiting.slice(0, ART_BATCH).map((one) => ({
        ...one.card,
        meta: metaOf(one.card),
        subtopicTitle: one.subtopicTitle,
        redraw: one.card.visualKind !== null,
      }));
      const redraws = waiting.filter((one) => one.card.visualKind !== null).length;
      return {
        value: deps.prompts.render("tool-results/art-requests.njk", {
          cards,
          total: waiting.length,
          redraws,
        }),
        dataSeen: [],
        recordsWritten: [],
      };
    },
  };
}

const ArtPiece = Type.Object(
  {
    card: Id,
    art: Type.String({
      minLength: 1,
      description: `The ASCII art: printable ASCII, at most ${ART_COLUMNS} columns`,
    }),
    alt: Type.String({
      minLength: 1,
      maxLength: 240,
      description: "The caption under the drawing: what it shows, and what the joke is",
    }),
  },
  CLOSED,
);

const ArtParameters = Type.Object(
  { art: Type.Array(ArtPiece, { minItems: 1, maxItems: ART_BATCH }) },
  CLOSED,
);

type Piece = { card: string; art: string; alt: string };

/** Each piece's card, which must be one waiting for art, named once in the call. */
async function waitingCards(context: ToolContext, pieces: Piece[]) {
  const waiting = await waitingForArt(context.db, topicOfDesigner(context));
  const byId = new Map(waiting.map((one) => [one.card.id, one]));
  const problems: string[] = [];
  const seen = new Set<string>();
  for (const piece of pieces) {
    if (!byId.has(piece.card)) {
      problems.push(`card ${piece.card} isn't waiting for art: list_art_requests shows the ones that are`);
    }
    if (seen.has(piece.card)) problems.push(`card ${piece.card} is named twice`);
    seen.add(piece.card);
  }
  if (problems.length > 0) throw new ToolError(`Nothing was done:\n- ${problems.join("\n- ")}`);
  return byId;
}

export function renderArtTool(deps: AgentDeps): HarnessTool<typeof ArtParameters> {
  return {
    name: "render_art",
    label: "Render art on cards",
    description: deps.prompts.render("tools/render-art.njk", {
      columns: ART_COLUMNS,
      batch: ART_BATCH,
      limits: artLimits(),
    }),
    parameters: ArtParameters,
    kind: "change",
    async execute(params, context) {
      const byId = await waitingCards(context, params.art);
      const [named] = await context.db
        .select({ name: topic.canonicalName })
        .from(topic)
        .where(eq(topic.id, topicOfDesigner(context)));
      const said: string[] = [];
      const renders: RenderRecord[] = [];
      const images: ToolImage[] = [];
      for (const piece of params.art) {
        const waiting = byId.get(piece.card);
        if (!waiting) continue;
        const art = normalizeArt(piece.art);
        const problems = artProblems(art, kindOf(waiting));
        if (problems.length > 0) {
          said.push(`- card ${piece.card}: not rendered; fix every problem: ${problems.join("; ")}`);
          continue;
        }
        const render = await createRecord(context.db, RenderRecord, {
          kind: "render",
          author: context.author,
          body: { card: piece.card, art },
        });
        const shown = {
          ...waiting.card,
          visualId: render.id,
          visualKind: "ascii" as const,
          visualSlots: { art, alt: piece.alt },
        };
        let png: Buffer;
        try {
          png = await deps.browser.renderCard(
            { card: toCardOut(shown, waiting.subtopicTitle), topicName: named?.name ?? "" },
            context.signal,
          );
        } catch (error) {
          log.warn({ err: error, card: piece.card }, "a card wouldn't render");
          said.push(`- card ${piece.card}: couldn't be rendered just now; render it again in a moment`);
          continue;
        }
        renders.push(render);
        images.push({ data: png.toString("base64"), mimeType: "image/png" });
        said.push(`- card ${piece.card}: screenshot ${images.length}`);
      }
      const stored = await recordsStored(context.db, deps.prompts, renders);
      return {
        ...stored,
        value: `${String(stored.value)}\n${said.join("\n")}\nEach screenshot is the card as a reader sees it on a phone. attach_art the art that reads well; draw the rest again.`,
        images,
      };
    },
  };
}

export function attachArtTool(deps: AgentDeps): HarnessTool<typeof ArtParameters> {
  return {
    name: "attach_art",
    label: "Attach art to cards",
    description: deps.prompts.render("tools/attach-art.njk", { batch: ART_BATCH }),
    parameters: ArtParameters,
    kind: "change",
    async execute(params, context) {
      const byId = await waitingCards(context, params.art);
      const problems: string[] = [];
      const rendersOf = new Map<string, RenderRecord>();
      for (const piece of params.art) {
        const art = normalizeArt(piece.art);
        // Only art seen on the card in this run goes live: the render is the check.
        const [rendered] = await context.db
          .select({ id: harnessRecord.id })
          .from(harnessRecord)
          .where(
            and(
              eq(harnessRecord.kind, "render"),
              sql`${harnessRecord.author} ->> 'runId' = ${context.run.id}`,
              sql`${harnessRecord.body} ->> 'card' = ${piece.card}`,
              sql`${harnessRecord.body} ->> 'art' = ${art}`,
            ),
          )
          .orderBy(desc(harnessRecord.seq))
          .limit(1);
        if (!rendered) {
          problems.push(
            `card ${piece.card}: this run hasn't rendered that exact art on it; render_art it first`,
          );
          continue;
        }
        rendersOf.set(piece.card, await readLatestRecord(context.db, RenderRecord, "render", rendered.id));
      }
      if (problems.length > 0) throw new ToolError(`Nothing was attached:\n- ${problems.join("\n- ")}`);
      const { attached, live } = await context.db.transaction(async (tx) => {
        const records: ArtRecord[] = [];
        const tiers = new Set<string>();
        for (const piece of params.art) {
          const waiting = byId.get(piece.card);
          const render = rendersOf.get(piece.card);
          if (!waiting || !render) continue;
          const art = normalizeArt(piece.art);
          await tx
            .update(card)
            .set({
              visualId: render.id,
              visualKind: "ascii",
              visualSlots: { art, alt: piece.alt.trim() },
              genMeta: sql`${card.genMeta} || ${JSON.stringify({ artStyle: ART_STYLE })}::jsonb`,
            })
            .where(eq(card.id, piece.card));
          records.push(
            await createRecord(tx, ArtRecord, {
              kind: "art",
              author: context.author,
              body: { card: piece.card, render: refOf(render), writer: metaOf(waiting.card).writer },
            }),
          );
          if (waiting.card.subtopicId) tiers.add(waiting.card.subtopicId);
        }
        const wentLive: string[] = [];
        for (const tierId of tiers) {
          const tier = await tierById(tx, tierId);
          if (await putCardsLiveIfDone(tx, tier))
            wentLive.push(`the ${tier.difficulty} tier of "${tier.title}"`);
        }
        return { attached: records, live: wentLive };
      });
      const stored = await recordsStored(context.db, deps.prompts, attached);
      let value = String(stored.value);
      if (live.length > 0) value += `\nThat art completed ${live.join(" and ")}: its cards are live.`;
      return { ...stored, value };
    },
  };
}
