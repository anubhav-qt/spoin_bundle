import type { Context } from "hono";
import type { ContentfulStatusCode } from "hono/utils/http-status";
import { log } from "../log.ts";

/**
 * An error the client can act on. `detail` is shown to the user as written: the web
 * client reads `body.detail` from every non-2xx response.
 */
export class HttpError extends Error {
  readonly status: ContentfulStatusCode;
  constructor(status: ContentfulStatusCode, detail: string) {
    super(detail);
    this.status = status;
  }
}

export const notFound = (what: string) => new HttpError(404, `${what} not found`);

/**
 * The one place unhandled errors are logged. The response is deliberately opaque; the
 * request id is what makes it actionable: the caller quotes it, we grep for it.
 */
export function onError(err: Error, c: Context): Response {
  const requestId = c.get("requestId") as string | undefined;
  if (err instanceof HttpError) return c.json({ detail: err.message }, err.status);
  log.error({ err, method: c.req.method, path: c.req.path, requestId }, "unhandled");
  return c.json({ detail: "Internal server error", request_id: requestId }, 500);
}

/** The Postgres error code behind an error, if any (drizzle wraps driver errors in `cause`). */
export function pgCode(e: unknown): string | undefined {
  const err = e as { code?: string; cause?: { code?: string } };
  return err?.cause?.code ?? err?.code;
}

export const UNIQUE_VIOLATION = "23505";
