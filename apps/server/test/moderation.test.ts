import { randomUUID } from "node:crypto";
import { eq } from "drizzle-orm";
import { describe, expect, test } from "vitest";
import { ASCII_MAX_WIDTH, loadLibrary } from "../src/content/ascii-library.ts";
import { card, cardRepair, cardReport, generationJob } from "../src/db/schema.ts";
import { markCardReportsResolved } from "../src/moderation/service.ts";
import { makeTopic } from "./fixtures.ts";
import { admin, type Client, client, deps, guest, signedUp, userIdOf } from "./helpers.ts";

/*
 * ADR-0076: report a card, and the operator's triage. The repair itself is the frog's
 * (Phase 9), so a landed repair is written here the way it will write one.
 */

const { db } = deps;
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x30]);

async function liveCard() {
  const made = await makeTopic({ subtopicsPerTier: 1, cardsPerSubtopic: 1 });
  return made.cards[0] as typeof card.$inferSelect;
}

const statusOf = async (id: string) => (await db.select().from(card).where(eq(card.id, id)))[0]?.status;

function form(fields: Record<string, string>, file?: Uint8Array | string) {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  if (file !== undefined) f.set("file", new File([file], "card.png", { type: "image/png" }));
  return f;
}

/** A repair landed the way the frog lands one: a new version in the family, the old one superseded. */
async function landRepair(before: typeof card.$inferSelect) {
  await db.update(card).set({ status: "superseded" }).where(eq(card.id, before.id));
  const { id: _, createdAt: __, ...rest } = before;
  const [after] = await db
    .insert(card)
    .values({ ...rest, version: before.version + 1, status: "active", body: `${before.body} Repaired.` })
    .returning();
  if (!after) throw new Error("card insert returned nothing");
  await db
    .insert(cardRepair)
    .values({ cardId: before.id, mode: "fix", status: "done", resultCardId: after.id });
  await markCardReportsResolved(db, before.id);
  return after;
}

describe("reporting a card", () => {
  test("is idempotent per reader and card, and reopens a resolved report", async () => {
    const c = await liveCard();
    const reader = await signedUp();
    const userId = await userIdOf(reader);

    expect(
      (await reader.post(`/cards/${c.id}/report`, { reason: "art", note: "art is broken" })).status,
    ).toBe(204);
    await markCardReportsResolved(db, c.id);
    expect((await reader.post(`/cards/${c.id}/report`, { reason: "formatting" })).status).toBe(204);

    const rows = await db.select().from(cardReport).where(eq(cardReport.cardId, c.id));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ userId, reason: "formatting", note: null, resolvedAt: null });
  });

  test("guests may report; a card that isn't live may not be reported", async () => {
    const c = await liveCard();
    const g = await guest();
    expect((await g.post(`/cards/${c.id}/report`, { reason: "diagram" })).status).toBe(204);

    await db.update(card).set({ status: "retired" }).where(eq(card.id, c.id));
    const r = await g.post(`/cards/${c.id}/report`, { reason: "diagram" });
    expect([r.status, r.body.detail]).toEqual([404, "No such card"]);
    expect((await g.post(`/cards/${randomUUID()}/report`, { reason: "other" })).status).toBe(404);
    expect((await client().post(`/cards/${c.id}/report`, { reason: "other" })).status).toBe(401);
  });
});

describe("the repair queue", () => {
  test("is for admins only", async () => {
    expect((await client().get("/admin/repairs")).status).toBe(401);
    const r = await (await signedUp()).get("/admin/repairs");
    expect([r.status, r.body.detail]).toEqual([403, "Admins only"]);
  });

  test("lists a reported card, and delete retires it and resolves its reports", async () => {
    const op = await admin();
    const c = await liveCard();
    await (await signedUp()).post(`/cards/${c.id}/report`, { reason: "diagram", note: "mangled" });

    const queue = (await op.get("/admin/repairs")).body;
    const item = queue.find((q: { card_id: string }) => q.card_id === c.id);
    expect(item).toMatchObject({
      state: "open",
      report_count: 1,
      reports: [{ reason: "diagram", note: "mangled" }],
      before: { card_id: c.id, version: 1 },
      after: null,
      latest_repair: null,
    });

    expect((await op.post(`/admin/repairs/${c.id}/delete`)).body).toEqual({
      card_id: c.id,
      action: "deleted",
      job_id: null,
    });
    expect(await statusOf(c.id)).toBe("retired");
    const reports = await db.select().from(cardReport).where(eq(cardReport.cardId, c.id));
    expect(reports.every((r) => r.resolvedAt !== null)).toBe(true);
    const after = (await op.get("/admin/repairs")).body;
    expect(after.some((q: { card_id: string }) => q.card_id === c.id)).toBe(false);
    expect((await op.post(`/admin/repairs/${c.id}/delete`)).status).toBe(404);
  });

  test("a second repair while one is queued is a 409", async () => {
    const op = await admin();
    const c = await liveCard();

    const fix = await op.upload(`/admin/repairs/${c.id}/fix`, form({ guidance: "  keep the words  " }, PNG));
    expect(fix.status).toBe(200);
    expect(fix.body).toMatchObject({ card_id: c.id, action: "fix_enqueued" });
    const [job] = await db.select().from(generationJob).where(eq(generationJob.cardId, c.id));
    expect(job).toMatchObject({ id: fix.body.job_id, kind: "repair", status: "pending", priority: -10 });
    const [repair] = await db.select().from(cardRepair).where(eq(cardRepair.cardId, c.id));
    expect(repair).toMatchObject({
      jobId: job?.id,
      mode: "fix",
      guidance: "keep the words",
      status: "pending",
    });
    expect(new Uint8Array(repair?.sourceImage as Buffer)).toEqual(PNG);

    const again = await op.upload(`/admin/repairs/${c.id}/fix`, form({}, PNG));
    expect([again.status, again.body.detail]).toEqual([409, "A repair is already queued for this card"]);
    const remake = await op.upload(`/admin/repairs/${c.id}/remake`, form({ instructions: "Start over." }));
    expect(remake.status).toBe(409);
    expect(await db.select().from(generationJob).where(eq(generationJob.cardId, c.id))).toHaveLength(1);
  });

  test("a fix needs a real image, a remake needs instructions but no image", async () => {
    const op = await admin();
    const c = await liveCard();
    const fix = (f: FormData) => op.upload(`/admin/repairs/${c.id}/fix`, f);
    expect((await fix(form({}))).status).toBe(422);
    expect((await fix(form({}, "not an image"))).status).toBe(400);

    const remake = (f: FormData) => op.upload(`/admin/repairs/${c.id}/remake`, f);
    expect((await remake(form({ instructions: "   " }))).status).toBe(422);
    expect((await remake(form({ instructions: "x".repeat(4001) }))).status).toBe(422);
    const ok = await remake(form({ instructions: " Explain it with a river. " }));
    expect(ok.body).toMatchObject({ action: "remake_enqueued" });
    const [repair] = await db.select().from(cardRepair).where(eq(cardRepair.cardId, c.id));
    expect(repair).toMatchObject({ mode: "remake", guidance: "Explain it with a river.", sourceImage: null });
  });

  test("a landed repair shows before and after until dismissed", async () => {
    const op = await admin();
    const c = await liveCard();
    await (await signedUp()).post(`/cards/${c.id}/report`, { reason: "formatting" });
    const fixed = await landRepair(c);

    const item = (await op.get("/admin/repairs")).body.find((q: { card_id: string }) => q.card_id === c.id);
    expect(item).toMatchObject({
      state: "resolved",
      report_count: 0,
      before: { version: 1 },
      after: { card_id: fixed.id, version: 2 },
      latest_repair: { mode: "fix", status: "done" },
    });

    expect((await op.post(`/admin/repairs/${c.id}/dismiss`)).body.action).toBe("dismissed");
    const queue = (await op.get("/admin/repairs")).body;
    expect(queue.some((q: { card_id: string }) => q.card_id === c.id)).toBe(false);
    expect(await statusOf(fixed.id)).toBe("active");
  });

  test("revert puts the original back and supersedes the repaired version", async () => {
    const op = await admin();
    const c = await liveCard();
    expect((await op.post(`/admin/repairs/${c.id}/revert`)).body.detail).toBe(
      "No landed repair to revert for this card",
    );
    const fixed = await landRepair(c);

    expect((await op.post(`/admin/repairs/${c.id}/revert`)).body.action).toBe("reverted");
    expect([await statusOf(c.id), await statusOf(fixed.id)]).toEqual(["active", "superseded"]);
    const [repair] = await db.select().from(cardRepair).where(eq(cardRepair.cardId, c.id));
    expect(repair?.error).toBe("reverted by operator");
    const queue = (await op.get("/admin/repairs")).body;
    expect(queue.some((q: { card_id: string }) => q.card_id === c.id)).toBe(false);
  });
});

describe("ASCII review", () => {
  async function scenes() {
    const made = await makeTopic({ subtopicsPerTier: 1, cardsPerSubtopic: 2 });
    const [fromLibrary, edited, prose] = made.cards as [
      typeof card.$inferSelect,
      typeof card.$inferSelect,
      typeof card.$inferSelect,
    ];
    const entry = [...loadLibrary().values()][0];
    if (!entry) throw new Error("the library is empty");
    const ascii = (slots: Record<string, string>) => ({
      visualId: "ascii",
      visualKind: "ascii" as const,
      visualSlots: slots,
    });
    await db
      .update(card)
      // Earlier than the rest, which were written in one statement and share a timestamp.
      .set({
        ...ascii({ art: entry.art, alt: "A scene.", src_id: entry.id }),
        createdAt: new Date(Date.now() - 60_000),
      })
      .where(eq(card.id, fromLibrary.id));
    await db
      .update(card)
      .set(ascii({ art: `short\n${"w".repeat(ASCII_MAX_WIDTH + 2)}`, alt: "" }))
      .where(eq(card.id, edited.id));
    return { slug: made.topic.slug, entry, fromLibrary, edited, prose };
  }

  test("lists a topic's scenes oldest first, beside the library entry they came from", async () => {
    const op = await admin();
    const { slug, entry, fromLibrary, edited } = await scenes();

    const r = await op.get(`/admin/ascii/${slug}`);
    expect(r.status).toBe(200);
    expect(r.body.map((s: { card_id: string }) => s.card_id)).toEqual([fromLibrary.id, edited.id]);
    expect(r.body[0]).toMatchObject({
      src_id: entry.id,
      library_title: entry.title,
      library_art: entry.art,
      subtopic_title: "beginner 0",
      max_width: ASCII_MAX_WIDTH,
    });
    expect(r.body[1]).toMatchObject({ src_id: null, library_title: null, widest_line: ASCII_MAX_WIDTH + 2 });

    const missing = await op.get("/admin/ascii/no-such-topic");
    expect([missing.status, missing.body.detail]).toEqual([404, "No topic 'no-such-topic'"]);
  });

  test("keep writes the edit verbatim; reject files an art report into the repair queue", async () => {
    const op = await admin();
    const opId = await userIdOf(op);
    const { fromLibrary, prose } = await scenes();
    const wide = "x".repeat(ASCII_MAX_WIDTH + 5);

    const kept = await op.post(`/admin/ascii/scene/${fromLibrary.id}/keep`, { art: wide, alt: "Wide." });
    expect(kept.body).toEqual({ card_id: fromLibrary.id, action: "kept" });
    const [row] = await db.select().from(card).where(eq(card.id, fromLibrary.id));
    expect(row?.visualSlots).toMatchObject({ art: wide, alt: "Wide.", edited_by_operator: "true" });

    const notAscii = await op.post(`/admin/ascii/scene/${prose.id}/keep`, { art: "x", alt: "" });
    expect([notAscii.status, notAscii.body.detail]).toEqual([400, "That card carries no ASCII scene"]);

    expect((await op.post(`/admin/ascii/scene/${fromLibrary.id}/reject`, {})).body.action).toBe(
      "sent_to_repairs",
    );
    const [report] = await db.select().from(cardReport).where(eq(cardReport.cardId, fromLibrary.id));
    expect(report).toMatchObject({ userId: opId, reason: "art", note: "Scene rejected in ASCII review" });
    const queue = (await op.get("/admin/repairs")).body;
    expect(queue.some((q: { card_id: string }) => q.card_id === fromLibrary.id)).toBe(true);
  });

  test("is for admins only", async () => {
    const reader: Client = await signedUp();
    expect((await reader.get("/admin/ascii/anything")).status).toBe(403);
  });
});

describe("the ASCII library", () => {
  test("loads the curated gags, each titled, drawn and inside the column budget", () => {
    const library = [...loadLibrary().values()];
    expect(library.length).toBeGreaterThan(200);
    for (const e of library) {
      expect(e.title.trim()).not.toBe("");
      expect(e.art.trim()).not.toBe("");
    }
    const over = library.flatMap((e) =>
      e.art
        .split("\n")
        .filter((line) => [...line].length > ASCII_MAX_WIDTH)
        .map((line) => [e.id, line]),
    );
    expect(over).toEqual([]);
    expect(loadLibrary()).toBe(loadLibrary());
  });
});
