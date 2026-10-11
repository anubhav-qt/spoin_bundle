import { type Hook, OpenAPIHono, z } from "@hono/zod-openapi";
import { ErrorOut } from "@spoin/shared";
import type { AppEnv } from "../context.ts";

/**
 * A request that fails its schema answers 422 with one readable `detail` string, the
 * shape every other error has: the web shows `body.detail` as written.
 */
// biome-ignore lint/suspicious/noExplicitAny: the hook is shared by every route, whatever its input.
const validationHook: Hook<any, AppEnv, any, any> = (result, c) => {
  if (!result.success) return c.json({ detail: describe(result.error) }, 422);
};

export function describe(error: z.core.$ZodError): string {
  return error.issues
    .map((i) => (i.path.length ? `${i.path.join(".")}: ${i.message}` : i.message))
    .join("; ");
}

/** Every router is built here so every one validates the same way. */
export const router = () => new OpenAPIHono<AppEnv>({ defaultHook: validationHook });

const errorBody = { content: { "application/json": { schema: ErrorOut } } };

/** The error responses a route documents, by status. */
export const errors = {
  401: { description: "Not signed in", ...errorBody },
  403: { description: "Not allowed", ...errorBody },
  404: { description: "Not found", ...errorBody },
  409: { description: "Conflict", ...errorBody },
  422: { description: "Invalid request", ...errorBody },
  429: { description: "Too many requests", ...errorBody },
  502: { description: "An upstream model failed", ...errorBody },
} as const;

/** A JSON response body, for `createRoute`'s `responses`. */
export const json = <T extends z.ZodType>(schema: T, description = "OK") => ({
  description,
  content: { "application/json": { schema } },
});

/** A JSON request body, for `createRoute`'s `request`. */
export const body = <T extends z.ZodType>(schema: T) => ({
  body: { content: { "application/json": { schema } }, required: true },
});

/** Path parameters that are ids: a malformed one is a 422, never a Postgres cast error. */
export const ids = <K extends string>(...names: K[]) =>
  z.object(Object.fromEntries(names.map((n) => [n, z.uuid()])) as Record<K, z.ZodUUID>);
