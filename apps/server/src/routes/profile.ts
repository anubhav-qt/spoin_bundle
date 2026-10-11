import { createRoute, z } from "@hono/zod-openapi";
import {
  DailyGoalOut,
  ImportedFontOut,
  PreferencesOut,
  PreferencesUpdateIn,
  ProfileExportOut,
  ProfileStatsOut,
  UserOut,
  UserProfileUpdateIn,
} from "@spoin/shared";
import type { Deps } from "../context.ts";
import { HttpError } from "../lib/errors.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, json, router } from "../lib/openapi.ts";
import {
  addFont,
  deleteFont,
  getPreferences,
  listFonts,
  loadFont,
  updatePreferences,
} from "../profile/preferences.ts";
import * as profile from "../profile/service.ts";
import {
  AVATAR_MAX_BYTES,
  FONT_MAX_BYTES,
  readFilePart,
  sniffFont,
  sniffImage,
  uploadLimit,
} from "../profile/uploads.ts";

const binary = (mediaTypes: string[], description: string) => ({
  description,
  content: Object.fromEntries(
    mediaTypes.map((t) => [t, { schema: { type: "string" as const, format: "binary" } }]),
  ),
});

const upload = (extra: Record<string, unknown> = {}) => ({
  body: {
    required: true,
    content: {
      "multipart/form-data": {
        schema: {
          type: "object" as const,
          properties: { file: { type: "string" as const, format: "binary" }, ...extra },
        },
      },
    },
  },
});

const FontId = z.object({ font_id: z.string() });

const AVATAR_TOO_LARGE = "Image is too large. Maximum size is 5MB.";
const FONT_TOO_LARGE = "Font file is too large. Maximum size is 2MB.";

export function profileRoutes(deps: Deps) {
  const { db } = deps;
  const r = router();

  r.use("/profile/me/avatar", async (c, next) =>
    c.req.method === "POST" ? uploadLimit(AVATAR_MAX_BYTES, AVATAR_TOO_LARGE)(c, next) : next(),
  );
  r.use("/profile/me/fonts", async (c, next) =>
    c.req.method === "POST" ? uploadLimit(FONT_MAX_BYTES, FONT_TOO_LARGE)(c, next) : next(),
  );

  return r
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me",
        tags: ["profile"],
        responses: { 200: json(UserOut), 401: errors[401] },
      }),
      async (c) => c.json(await profile.me(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "patch",
        path: "/profile/me",
        tags: ["profile"],
        request: body(UserProfileUpdateIn),
        responses: { 200: json(UserOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await profile.updateProfile(db, needUser(c).id, c.req.valid("json")), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/profile/me/avatar",
        tags: ["profile"],
        summary: "Upload an avatar; the format is sniffed from the bytes, never the declared type",
        request: upload(),
        responses: { 200: json(UserOut), 400: errors[422], 401: errors[401], 413: errors[422] },
      }),
      async (c) => {
        const caller = needUser(c);
        const { data } = await readFilePart(c, AVATAR_MAX_BYTES, AVATAR_TOO_LARGE);
        const mediaType = sniffImage(data);
        if (!mediaType)
          throw new HttpError(400, "Invalid image format. Only JPEG, PNG, and WebP are supported.");
        return c.json(await profile.setAvatar(db, caller.id, data, mediaType), 200);
      },
    )
    .openapi(
      createRoute({
        method: "delete",
        path: "/profile/me/avatar",
        tags: ["profile"],
        responses: { 200: json(UserOut), 401: errors[401] },
      }),
      async (c) => c.json(await profile.deleteAvatar(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/avatar/image",
        tags: ["profile"],
        responses: {
          200: binary(["image/jpeg", "image/png", "image/webp"], "The avatar, as whatever it actually is"),
          401: errors[401],
          404: errors[404],
        },
      }),
      async (c) => {
        const { data, mediaType } = await profile.loadAvatar(db, needUser(c).id);
        return c.body(new Uint8Array(data), 200, { "Content-Type": mediaType });
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/preferences",
        tags: ["profile"],
        summary: "Palette, saved themes, font and imported-font metadata (ADR-0070)",
        responses: { 200: json(PreferencesOut), 401: errors[401] },
      }),
      async (c) => c.json(await getPreferences(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "put",
        path: "/profile/me/preferences",
        tags: ["profile"],
        request: body(PreferencesUpdateIn),
        responses: { 200: json(PreferencesOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => c.json(await updatePreferences(db, needUser(c).id, c.req.valid("json")), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/fonts",
        tags: ["profile"],
        responses: { 200: json(z.array(ImportedFontOut)), 401: errors[401] },
      }),
      async (c) => c.json(await listFonts(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/profile/me/fonts",
        tags: ["profile"],
        summary: "Import a font; WOFF2, TTF or OTF by magic bytes, at most 2MB",
        request: upload({ name: { type: "string", minLength: 1, maxLength: 80 } }),
        responses: {
          201: json(ImportedFontOut, "Created"),
          400: errors[422],
          401: errors[401],
          413: errors[422],
        },
      }),
      async (c) => {
        const caller = needUser(c);
        const { data, form } = await readFilePart(c, FONT_MAX_BYTES, FONT_TOO_LARGE);
        const name = typeof form.name === "string" ? form.name.trim() : "";
        if (name.length < 1 || name.length > 80) throw new HttpError(422, "name: 1 to 80 characters");
        const format = sniffFont(data);
        if (!format)
          throw new HttpError(400, "Unsupported font file. Only WOFF2, TTF and OTF are supported.");
        return c.json(await addFont(db, caller.id, name, format, data), 201);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/fonts/{font_id}",
        tags: ["profile"],
        request: { params: FontId },
        responses: {
          200: binary(["font/woff2", "font/ttf", "font/otf"], "The font file, for an @font-face src"),
          401: errors[401],
          404: errors[404],
        },
      }),
      async (c) => {
        const { data, mediaType } = await loadFont(db, needUser(c).id, c.req.valid("param").font_id);
        // Immutable by id, so it caches hard.
        return c.body(new Uint8Array(data), 200, {
          "Content-Type": mediaType,
          "Cache-Control": "private, max-age=31536000, immutable",
        });
      },
    )
    .openapi(
      createRoute({
        method: "delete",
        path: "/profile/me/fonts/{font_id}",
        tags: ["profile"],
        request: { params: FontId },
        responses: { 204: { description: "Deleted" }, 401: errors[401], 404: errors[404] },
      }),
      async (c) => {
        await deleteFont(db, needUser(c).id, c.req.valid("param").font_id);
        return c.body(null, 204);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/export",
        tags: ["profile"],
        summary: "The user's own data as JSON (Settings, Data & Privacy)",
        responses: { 200: json(ProfileExportOut), 401: errors[401] },
      }),
      async (c) => c.json(await profile.exportData(db, needUser(c).id), 200),
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/stats",
        tags: ["profile"],
        request: {
          query: z.object({
            year: z.coerce.number().int().min(1970).max(9999),
            month: z.coerce.number().int().min(1).max(12),
          }),
        },
        responses: { 200: json(ProfileStatsOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) => {
        const { year, month } = c.req.valid("query");
        return c.json(await profile.stats(db, needUser(c).id, year, month), 200);
      },
    )
    .openapi(
      createRoute({
        method: "get",
        path: "/profile/me/today",
        tags: ["profile"],
        summary: "Cards read in the caller's local day against the daily goal (ADR-0062)",
        request: {
          query: z.object({ tz_offset_minutes: z.coerce.number().int().min(-840).max(840).default(0) }),
        },
        responses: { 200: json(DailyGoalOut), 401: errors[401], 422: errors[422] },
      }),
      async (c) =>
        c.json(await profile.today(db, needUser(c).id, c.req.valid("query").tz_offset_minutes), 200),
    );
}
