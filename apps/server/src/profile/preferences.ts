import type { ImportedFontOut, PreferencesOut, PreferencesUpdateIn } from "@spoin/shared";
import { and, asc, eq } from "drizzle-orm";
import type { z } from "zod";
import type { Db } from "../db/client.ts";
import { userFont, userPreference } from "../db/schema.ts";
import { HttpError, notFound } from "../lib/errors.ts";
import { isUuid } from "../lib/wire.ts";
import type { FontFormat } from "./uploads.ts";

/*
 * Appearance preferences (ADR-0070): the palette, saved themes and imported fonts.
 * Every font query filters by `user_id` in the SQL itself, so a font id belonging to
 * another user is a 404, not a hidden row.
 */

/** Keep in step with the client. A built-in key, or `custom:<id>` / `import:<uuid>`. */
export const DEFAULT_PALETTE = "notebook";
export const DEFAULT_FONT = "literata";

const FONT_MEDIA_TYPE: Record<string, string> = { woff2: "font/woff2", ttf: "font/ttf", otf: "font/otf" };

type CustomPalette = PreferencesOut["custom_palettes"][number];

async function fonts(db: Db, userId: string): Promise<ImportedFontOut[]> {
  const rows = await db
    .select({ id: userFont.id, name: userFont.name, format: userFont.format, byte_size: userFont.byteSize })
    .from(userFont)
    .where(eq(userFont.userId, userId))
    .orderBy(asc(userFont.createdAt));
  return rows;
}

/** The user's preferences, or the built-in defaults when they have never written one. Font metadata only. */
export async function getPreferences(db: Db, userId: string): Promise<PreferencesOut> {
  const [row] = await db.select().from(userPreference).where(eq(userPreference.userId, userId));
  return {
    palette: row?.palette ?? DEFAULT_PALETTE,
    custom_palettes: (row?.customPalettes ?? []) as CustomPalette[],
    font: row?.font ?? DEFAULT_FONT,
    imported_fonts: await fonts(db, userId),
  };
}

/**
 * Whole-object replace. References that must resolve are checked here, not trusted
 * from the client: a `custom:<id>` palette must be a theme in this same write, and an
 * `import:<id>` font must be one this user owns.
 */
export async function updatePreferences(
  db: Db,
  userId: string,
  input: z.infer<typeof PreferencesUpdateIn>,
): Promise<PreferencesOut> {
  const saved = new Set(input.custom_palettes.map((p) => p.id));
  if (input.palette.startsWith("custom:") && !saved.has(input.palette.slice("custom:".length))) {
    throw new HttpError(422, "palette points at a saved theme that is not in custom_palettes.");
  }
  if (input.font.startsWith("import:")) {
    const fontId = input.font.slice("import:".length);
    if (!isUuid(fontId)) throw new HttpError(422, "font id is malformed.");
    const [owned] = await db
      .select({ id: userFont.id })
      .from(userFont)
      .where(and(eq(userFont.userId, userId), eq(userFont.id, fontId)));
    if (!owned) throw new HttpError(422, "font points at an imported font that does not exist.");
  }
  const values = { palette: input.palette, customPalettes: input.custom_palettes, font: input.font };
  await db
    .insert(userPreference)
    .values({ userId, ...values })
    .onConflictDoUpdate({ target: userPreference.userId, set: { ...values, updatedAt: new Date() } });
  return getPreferences(db, userId);
}

export async function listFonts(db: Db, userId: string): Promise<ImportedFontOut[]> {
  return fonts(db, userId);
}

export async function addFont(
  db: Db,
  userId: string,
  name: string,
  format: FontFormat,
  data: Buffer,
): Promise<ImportedFontOut> {
  const [row] = await db
    .insert(userFont)
    .values({ userId, name, format, data, byteSize: data.length })
    .returning({
      id: userFont.id,
      name: userFont.name,
      format: userFont.format,
      byte_size: userFont.byteSize,
    });
  if (!row) throw new Error("font insert returned nothing");
  return row;
}

/** The bytes, scoped to the caller: a stranger's id is the same 404 as a missing one. */
export async function loadFont(
  db: Db,
  userId: string,
  fontId: string,
): Promise<{ data: Buffer; mediaType: string }> {
  if (!isUuid(fontId)) throw notFound("Font");
  const [row] = await db
    .select({ data: userFont.data, format: userFont.format })
    .from(userFont)
    .where(and(eq(userFont.userId, userId), eq(userFont.id, fontId)));
  if (!row) throw notFound("Font");
  return { data: row.data, mediaType: FONT_MEDIA_TYPE[row.format] ?? "application/octet-stream" };
}

/** Removes a font; if it was the active one, the choice resets to the default in the same transaction. */
export async function deleteFont(db: Db, userId: string, fontId: string): Promise<void> {
  if (!isUuid(fontId)) throw notFound("Font");
  await db.transaction(async (tx) => {
    const gone = await tx
      .delete(userFont)
      .where(and(eq(userFont.userId, userId), eq(userFont.id, fontId)))
      .returning({ id: userFont.id });
    if (gone.length === 0) throw notFound("Font");
    await tx
      .update(userPreference)
      .set({ font: DEFAULT_FONT, updatedAt: new Date() })
      .where(and(eq(userPreference.userId, userId), eq(userPreference.font, `import:${fontId}`)));
  });
}
