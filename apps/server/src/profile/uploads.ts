import type { Context } from "hono";
import { bodyLimit } from "hono/body-limit";
import { HttpError } from "../lib/errors.ts";

/*
 * Upload validation for avatars and imported fonts. The multipart part's declared
 * type is whatever the client put there, so the format is sniffed from the file's own
 * leading bytes; and the body is abandoned as soon as it crosses the limit
 * (`uploadLimit`), never buffered whole first.
 *
 * Not a full decode. A malformed but correctly-magicked file is stored and served
 * back with an explicit Content-Type to the user who uploaded it; the browser rejects
 * it and they see the fallback. Magic bytes plus a byte cap close the realistic gap.
 */

export const AVATAR_MAX_BYTES = 5 * 1024 * 1024;
export const FONT_MAX_BYTES = 2 * 1024 * 1024;
/** Multipart framing around the file: boundaries, part headers, a name field. */
const FRAMING = 64 * 1024;

const startsWith = (data: Uint8Array, magic: number[], at = 0) => magic.every((b, i) => data[at + i] === b);
const ascii = (s: string) => [...s].map((ch) => ch.charCodeAt(0));

export function sniffImage(data: Uint8Array): string | null {
  if (startsWith(data, [0xff, 0xd8, 0xff])) return "image/jpeg";
  if (startsWith(data, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return "image/png";
  // RIFF....WEBP: the size field sits between the two markers.
  if (startsWith(data, ascii("RIFF")) && startsWith(data, ascii("WEBP"), 8)) return "image/webp";
  return null;
}

export type FontFormat = "woff2" | "ttf" | "otf";

export function sniffFont(data: Uint8Array): FontFormat | null {
  if (startsWith(data, ascii("wOF2"))) return "woff2";
  if (startsWith(data, ascii("OTTO"))) return "otf";
  // TrueType outlines: the version tag 0x00010000, plus the legacy `true` and `ttcf` (collection) markers.
  if (startsWith(data, [0, 1, 0, 0]) || startsWith(data, ascii("true")) || startsWith(data, ascii("ttcf")))
    return "ttf";
  return null;
}

/** Stops reading the request at the limit, before the multipart parser buffers it. */
export function uploadLimit(maxBytes: number, detail: string) {
  return bodyLimit({
    maxSize: maxBytes + FRAMING,
    onError: () => {
      throw new HttpError(413, detail);
    },
  });
}

/** The multipart `file` part's bytes, size-checked; the sniff is the caller's. */
export async function readFilePart(
  c: Context,
  maxBytes: number,
  tooLarge: string,
): Promise<{ data: Buffer; form: Record<string, unknown> }> {
  const form = await c.req.parseBody();
  const file = form.file;
  if (!(file instanceof File)) throw new HttpError(422, "file: a file upload is required");
  if (file.size > maxBytes) throw new HttpError(413, tooLarge);
  const data = Buffer.from(await file.arrayBuffer());
  if (data.length === 0) throw new HttpError(400, "Empty upload");
  return { data, form };
}
