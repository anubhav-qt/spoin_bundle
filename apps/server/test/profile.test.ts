import { randomUUID } from "node:crypto";
import { describe, expect, test } from "vitest";
import { follow, makeTopic, read } from "./fixtures.ts";
import { type Client, client, guest, signedUp } from "./helpers.ts";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Array(64).fill(0)]);
const WOFF2 = new Uint8Array([..."wOF2"].map((ch) => ch.charCodeAt(0)).concat(new Array(64).fill(0)));
const HTML = new TextEncoder().encode("<html><script>alert(1)</script></html>");
const MB = 1024 * 1024;

const THEME = {
  id: "sunset",
  name: "Sunset Desk",
  bg: "#2b1d16",
  fg: "#f2ede6",
  accent: "#e08a3c",
  accent2: "#c65b3f",
};

/** The declared type is always a lie here: the server must go by the bytes. */
function form(data: Uint8Array, fields: Record<string, string> = {}) {
  const f = new FormData();
  f.set("file", new File([data], "upload.bin", { type: "application/octet-stream" }));
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

const userId = async (c: Client): Promise<string> => (await c.get("/auth/me")).body.id;

const prefs = (font: string, palette = "notebook", custom_palettes: unknown[] = []) => ({
  palette,
  custom_palettes,
  font,
});

describe("profile", () => {
  test("needs a session", async () => {
    const c = await guest();
    expect((await client().get("/profile/me")).status).toBe(401);
    expect((await c.get("/profile/me")).status).toBe(200);
  });

  test("a patch writes only the fields sent, within the bounds", async () => {
    const c = await signedUp();
    const r = await c.patch("/profile/me", { display_name: "Ada", daily_card_goal: 25 });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ display_name: "Ada", daily_card_goal: 25, age: null });

    const again = await c.patch("/profile/me", { age: 30, display_name: null });
    expect(again.body).toMatchObject({ display_name: "Ada", age: 30, daily_card_goal: 25 });

    const bad = await c.patch("/profile/me", { daily_card_goal: 0 });
    expect(bad.status).toBe(422);
    expect(bad.body.detail).toMatch(/daily_card_goal/);
  });
});

describe("preferences", () => {
  test("defaults ride along on /auth/me before anything is written", async () => {
    const c = await guest();
    const me = await c.get("/auth/me");
    expect(me.body.preferences).toEqual({
      palette: "notebook",
      custom_palettes: [],
      font: "literata",
      imported_fonts: [],
    });
  });

  test("a whole-object write round-trips the saved themes", async () => {
    const c = await signedUp();
    const r = await c.put("/profile/me/preferences", prefs("inter", "custom:sunset", [THEME]));
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ palette: "custom:sunset", font: "inter", custom_palettes: [THEME] });
    expect((await c.get("/profile/me/preferences")).body.custom_palettes[0].name).toBe("Sunset Desk");
  });

  test("a palette pointer with no matching theme is refused", async () => {
    const c = await signedUp();
    const r = await c.put("/profile/me/preferences", prefs("inter", "custom:ghost"));
    expect(r.status).toBe(422);
    expect(r.body.detail).toMatch(/saved theme/);
  });

  test("a font pointer must be an import this user owns", async () => {
    const c = await signedUp();
    expect((await c.put("/profile/me/preferences", prefs(`import:${randomUUID()}`))).status).toBe(422);
    const malformed = await c.put("/profile/me/preferences", prefs("import:nope"));
    expect(malformed.status).toBe(422);
    expect(malformed.body.detail).toBe("font id is malformed.");
  });

  test("more than fifty saved themes is a readable 422", async () => {
    const c = await signedUp();
    const many = Array.from({ length: 51 }, (_, i) => ({ ...THEME, id: `t${i}` }));
    const r = await c.put("/profile/me/preferences", prefs("inter", "notebook", many));
    expect(r.status).toBe(422);
    expect(r.body.detail).toMatch(/At most 50 saved themes/);
  });
});

describe("imported fonts", () => {
  test("upload, list and serve; the format comes from the bytes", async () => {
    const c = await signedUp();
    const r = await c.upload("/profile/me/fonts", form(WOFF2, { name: "My Face" }));
    expect(r.status).toBe(201);
    expect(r.body).toMatchObject({ name: "My Face", format: "woff2", byte_size: WOFF2.length });

    expect((await c.get("/profile/me/fonts")).body.map((f: { id: string }) => f.id)).toEqual([r.body.id]);

    const file = await c.raw("GET", `/profile/me/fonts/${r.body.id}`);
    expect(file.status).toBe(200);
    expect(file.headers.get("content-type")).toBe("font/woff2");
    expect(file.headers.get("cache-control")).toContain("immutable");
    expect(new Uint8Array(await file.arrayBuffer())).toEqual(WOFF2);
  });

  test("a non-font, a missing name and an oversized file are refused", async () => {
    const c = await signedUp();
    const html = await c.upload("/profile/me/fonts", form(HTML, { name: "Sneaky" }));
    expect(html.status).toBe(400);
    expect(html.body.detail).toMatch(/Unsupported font file/);

    expect((await c.upload("/profile/me/fonts", form(WOFF2))).status).toBe(422);

    const big = new Uint8Array(2 * MB + 1);
    big.set(WOFF2);
    const huge = await c.upload("/profile/me/fonts", form(big, { name: "Big" }));
    expect(huge.status).toBe(413);
    expect(huge.body.detail).toBe("Font file is too large. Maximum size is 2MB.");
  });

  test("a stranger's font is a 404, to read and to delete", async () => {
    const owner = await signedUp();
    const stranger = await signedUp();
    const { body: font } = await owner.upload("/profile/me/fonts", form(WOFF2, { name: "Private" }));

    expect((await stranger.raw("GET", `/profile/me/fonts/${font.id}`)).status).toBe(404);
    expect((await stranger.delete(`/profile/me/fonts/${font.id}`)).status).toBe(404);
    expect((await stranger.get("/profile/me/fonts")).body).toEqual([]);
    expect((await owner.get("/profile/me/fonts")).body).toHaveLength(1);
    expect((await owner.raw("GET", "/profile/me/fonts/not-a-uuid")).status).toBe(404);
  });

  test("deleting the active font resets the choice", async () => {
    const c = await signedUp();
    const { body: font } = await c.upload("/profile/me/fonts", form(WOFF2, { name: "Temp" }));
    expect((await c.put("/profile/me/preferences", prefs(`import:${font.id}`))).body.font).toBe(
      `import:${font.id}`,
    );

    expect((await c.delete(`/profile/me/fonts/${font.id}`)).status).toBe(204);
    const after = await c.get("/profile/me/preferences");
    expect(after.body.font).toBe("literata");
    expect(after.body.imported_fonts).toEqual([]);
  });
});

describe("avatar", () => {
  test("upload sets the flag and serves the bytes as what they are", async () => {
    const c = await signedUp();
    const r = await c.upload("/profile/me/avatar", form(PNG));
    expect(r.status).toBe(200);
    expect(r.body.has_avatar_image).toBe(true);

    const img = await c.raw("GET", "/profile/me/avatar/image");
    expect(img.headers.get("content-type")).toBe("image/png");
    expect(new Uint8Array(await img.arrayBuffer())).toEqual(PNG);

    expect((await c.delete("/profile/me/avatar")).body.has_avatar_image).toBe(false);
    expect((await c.raw("GET", "/profile/me/avatar/image")).status).toBe(404);
  });

  test("a disguised non-image and an empty file are refused", async () => {
    const c = await signedUp();
    const html = await c.upload("/profile/me/avatar", form(HTML));
    expect(html.status).toBe(400);
    expect(html.body.detail).toMatch(/Invalid image format/);
    expect((await c.upload("/profile/me/avatar", form(new Uint8Array()))).status).toBe(400);
    expect((await c.get("/profile/me")).body.has_avatar_image).toBe(false);
  });

  test("the limit is exact, and a far larger body is abandoned early", async () => {
    const c = await signedUp();
    const atLimit = new Uint8Array(5 * MB);
    atLimit.set(PNG);
    expect((await c.upload("/profile/me/avatar", form(atLimit))).status).toBe(200);

    const over = new Uint8Array(5 * MB + 1);
    over.set(PNG);
    const r = await c.upload("/profile/me/avatar", form(over));
    expect(r.status).toBe(413);
    expect(r.body.detail).toBe("Image is too large. Maximum size is 5MB.");

    const far = new Uint8Array(8 * MB);
    far.set(PNG);
    expect((await c.upload("/profile/me/avatar", form(far))).status).toBe(413);
  });
});

const DAY = 86_400_000;
const daysAgo = (n: number) => new Date(Date.now() - n * DAY);

describe("stats", () => {
  test("totals count distinct cards, streaks are runs of UTC days, the month is a heatmap", async () => {
    const c = await signedUp();
    const id = await userId(c);
    const { cards } = await makeTopic();
    const [a, b, d] = cards as [(typeof cards)[0], (typeof cards)[0], (typeof cards)[0]];

    // An older run of two days, in a month of its own.
    await read(id, a, new Date("2025-03-10T09:00:00Z"));
    await read(id, b, new Date("2025-03-10T10:00:00Z"));
    await read(id, b, new Date("2025-03-11T10:00:00Z"));
    // And a live run of three, ending today; the same card twice in one day is one read.
    await read(id, a, daysAgo(2));
    await read(id, d, daysAgo(1));
    await read(id, d, new Date(), "dwell_complete");
    await read(id, d, new Date());

    const r = await c.get("/profile/me/stats?year=2025&month=3");
    expect(r.status).toBe(200);
    expect(r.body).toEqual({
      current_streak: 3,
      longest_streak: 3,
      total_cards_read: 3,
      total_topics: 1,
      monthly_activity: [
        { date: "2025-03-10", cards_read: 2 },
        { date: "2025-03-11", cards_read: 1 },
      ],
    });
  });

  test("a run that ended before yesterday is not current", async () => {
    const c = await signedUp();
    const id = await userId(c);
    const { cards } = await makeTopic();
    await read(id, cards[0] as (typeof cards)[0], daysAgo(3));
    const r = await c.get("/profile/me/stats?year=2025&month=1");
    expect(r.body).toMatchObject({ current_streak: 0, longest_streak: 1, monthly_activity: [] });
  });

  test("the month is validated", async () => {
    const c = await signedUp();
    expect((await c.get("/profile/me/stats?year=2025&month=13")).status).toBe(422);
    expect((await c.get("/profile/me/stats?year=2025")).status).toBe(422);
  });
});

/** Local midnight for an offset, as UTC: the same arithmetic the server does. */
function localDayStart(offsetMinutes: number) {
  const offset = offsetMinutes * 60_000;
  const local = new Date(Date.now() + offset);
  return Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - offset;
}

describe("today", () => {
  test("two completions on one card count once, and the goal rides along", async () => {
    const c = await signedUp();
    await c.patch("/profile/me", { daily_card_goal: 25 });
    const id = await userId(c);
    const { cards } = await makeTopic();
    const card = cards[0] as (typeof cards)[0];
    await read(id, card, new Date(), "dwell_complete");
    await read(id, card, new Date());
    expect((await c.get("/profile/me/today")).body).toEqual({ cards_read: 1, goal: 25 });
  });

  test("the day boundary moves with the caller's offset", async () => {
    const c = await signedUp();
    const id = await userId(c);
    const { cards } = await makeTopic();
    const ist = 5 * 60 + 30;
    // One minute before the later of the two midnights: today under exactly one offset.
    const probe = Math.max(localDayStart(0), localDayStart(ist)) - 60_000;
    await read(id, cards[0] as (typeof cards)[0], new Date(probe));

    const utc = (await c.get("/profile/me/today?tz_offset_minutes=0")).body.cards_read;
    const india = (await c.get(`/profile/me/today?tz_offset_minutes=${ist}`)).body.cards_read;
    expect(new Set([utc, india])).toEqual(new Set([0, 1]));
    expect((await c.get("/profile/me/today?tz_offset_minutes=900")).status).toBe(422);
  });
});

describe("export", () => {
  test("the user's own relationship to the corpus, no card bodies", async () => {
    const c = await signedUp();
    const id = await userId(c);
    const { topic, cards } = await makeTopic();
    await follow(id, topic.id, "Mine");
    await read(id, cards[0] as (typeof cards)[0], new Date("2025-06-01T12:00:00Z"));

    const r = await c.get("/profile/me/export");
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({
      schema_version: 1,
      profile: { id },
      topics: [{ topic_id: topic.id, name: "Mine", is_custom: false }],
      notes: [],
      liked_cards: [],
      saved_cards: [],
      daily_activity: [{ date: "2025-06-01", cards_read: 1 }],
    });
    expect(JSON.stringify(r.body)).not.toContain("The body of");
  });
});
