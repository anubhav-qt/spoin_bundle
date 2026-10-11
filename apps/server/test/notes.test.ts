import { randomUUID } from "node:crypto";
import { describe, expect, test } from "vitest";
import { notesFor } from "../src/notes/service.ts";
import { follow, makeTopic } from "./fixtures.ts";
import { client, deps, signedUp, userIdOf } from "./helpers.ts";

async function reader() {
  const c = await signedUp();
  const id = await userIdOf(c);
  const { topic, cards } = await makeTopic();
  await follow(id, topic.id, "Testing");
  return { c, id, cards: cards.map((k) => k.id) };
}

describe("notes", () => {
  test("a second save edits in place, and the edit moves to the front", async () => {
    const { c, cards } = await reader();
    const [first, second] = cards as [string, string];

    expect((await c.put(`/cards/${first}/note`, { body: "written first" })).status).toBe(200);
    await c.put(`/cards/${second}/note`, { body: "written second" });
    const edited = await c.put(`/cards/${first}/note`, { body: "written first, edited last" });
    expect(edited.body).toMatchObject({ card_id: first, body: "written first, edited last" });

    const list = await c.get("/notes");
    expect(list.body.map((n: { note: { card_id: string } }) => n.note.card_id)).toEqual([first, second]);
    expect(list.body[0]).toMatchObject({
      topic_name: "Testing",
      note: { body: "written first, edited last" },
      card: { id: first, note: "written first, edited last", seen: false, subtopic_title: "beginner 0" },
    });
  });

  test("an unknown card is a 404, a malformed id a 422, an empty body a 422", async () => {
    const { c, cards } = await reader();
    expect((await c.put(`/cards/${randomUUID()}/note`, { body: "orphaned" })).status).toBe(404);
    expect((await c.put("/cards/nope/note", { body: "x" })).status).toBe(422);
    const empty = await c.put(`/cards/${cards[0]}/note`, { body: "" });
    expect(empty.status).toBe(422);
    expect(empty.body.detail).toMatch(/^body:/);
  });

  test("delete removes it, and deleting again is still a 204", async () => {
    const { c, cards } = await reader();
    await c.put(`/cards/${cards[0]}/note`, { body: "temporary" });
    expect((await c.delete(`/cards/${cards[0]}/note`)).status).toBe(204);
    expect((await c.delete(`/cards/${cards[0]}/note`)).status).toBe(204);
    expect((await c.get("/notes")).body).toEqual([]);
  });

  test("notes are private to their writer", async () => {
    const { c, id, cards } = await reader();
    const other = await signedUp();
    const otherId = await userIdOf(other);
    await c.put(`/cards/${cards[0]}/note`, { body: "mine" });

    expect((await other.get("/notes")).body).toEqual([]);
    expect(await notesFor(deps.db, otherId, cards)).toEqual(new Map());
    expect(await notesFor(deps.db, id, cards)).toEqual(new Map([[cards[0], "mine"]]));
  });

  test("needs a session", async () => {
    expect((await client().get("/notes")).status).toBe(401);
  });
});
