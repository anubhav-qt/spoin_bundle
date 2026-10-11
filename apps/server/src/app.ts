import { swaggerUI } from "@hono/swagger-ui";
import { cors } from "hono/cors";
import type { Deps } from "./context.ts";
import { onError } from "./lib/errors.ts";
import { REQUEST_ID_HEADER, requestContext, resolveCaller } from "./lib/http.ts";
import { router } from "./lib/openapi.ts";
import { authRoutes } from "./routes/auth.ts";
import { engagementRoutes } from "./routes/engagement.ts";
import { feedRoutes } from "./routes/feed.ts";
import { healthRoutes } from "./routes/health.ts";
import { notesRoutes } from "./routes/notes.ts";
import { profileRoutes } from "./routes/profile.ts";
import { quizRoutes } from "./routes/quiz.ts";
import { topicsRoutes } from "./routes/topics.ts";

/** Any device on the owner's network, so the phone can reach a dev server on the laptop. */
const LOCAL_NETWORK =
  /^https?:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$/;

/**
 * The HTTP surface. The single source of truth for every client: the web app today,
 * the mobile app later, both over HTTP with no privileged access. If the web client can
 * do something the mobile client can't, that is a bug.
 */
export function makeApp(deps: Deps) {
  const { env } = deps;
  const allowed = new Set(env.ALLOWED_ORIGINS);
  const app = router();

  app.use("*", requestContext(env));
  app.use(
    "*",
    cors({
      origin: (origin) =>
        allowed.has(origin) || (env.NODE_ENV !== "production" && LOCAL_NETWORK.test(origin)) ? origin : null,
      allowMethods: ["GET", "POST", "PUT", "PATCH", "DELETE"],
      allowHeaders: ["Content-Type", "Authorization", REQUEST_ID_HEADER],
      // Better Auth's bearer plugin hands the session token back in this header.
      exposeHeaders: ["set-auth-token", REQUEST_ID_HEADER],
      maxAge: 600,
    }),
  );
  app.use("*", resolveCaller(deps));

  app.route("/", healthRoutes(deps));
  // Before Better Auth's catch-all, so these paths are answered by our own routes.
  app.route("/", authRoutes(deps));
  app.on(["GET", "POST"], "/auth/*", (c) => deps.auth.handler(c.req.raw));

  app.route("/", profileRoutes(deps));
  app.route("/", notesRoutes(deps));
  app.route("/", topicsRoutes(deps));
  app.route("/", engagementRoutes(deps));
  app.route("/", feedRoutes(deps));
  app.route("/", quizRoutes(deps));

  // The contract for clients that aren't TypeScript (the mobile app's codegen).
  app.doc31("/openapi.json", {
    openapi: "3.1.0",
    info: {
      title: "Spoin API",
      version: env.RELEASE,
      description:
        "The feed read path never touches an LLM. The tadpoles fill a shared corpus offline; this service selects, filters and ranks over it.",
    },
  });
  if (env.NODE_ENV !== "production" || env.DEV_ROUTES) app.get("/docs", swaggerUI({ url: "/openapi.json" }));

  app.notFound((c) => c.json({ detail: "Not Found" }, 404));
  app.onError(onError);
  return app;
}

export type App = ReturnType<typeof makeApp>;
