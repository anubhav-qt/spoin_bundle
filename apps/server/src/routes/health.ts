import { createRoute, z } from "@hono/zod-openapi";
import { sql } from "drizzle-orm";
import type { Deps } from "../context.ts";
import { json, router } from "../lib/openapi.ts";

const HealthOut = z
  .object({ status: z.literal("ok"), env: z.string(), release: z.string() })
  .meta({ id: "HealthOut" });

export function healthRoutes(deps: Deps) {
  return router().openapi(
    createRoute({
      method: "get",
      path: "/health",
      tags: ["ops"],
      summary: "Liveness plus a real database round-trip",
      responses: { 200: json(HealthOut) },
    }),
    async (c) => {
      await deps.db.execute(sql`select 1`);
      return c.json({ status: "ok" as const, env: deps.env.NODE_ENV, release: deps.env.RELEASE }, 200);
    },
  );
}
