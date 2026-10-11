import { serve } from "@hono/node-server";
import { makeApp } from "./app.ts";
import { makeDeps } from "./deps.ts";
import { loadEnv } from "./env.ts";
import { log } from "./log.ts";

const env = loadEnv();
if (env.NODE_ENV === "production" && env.CLIENT_IP_HEADER === "none") {
  log.warn("CLIENT_IP_HEADER is not set, so every client shares one rate limit (the proxy's address)");
}
const deps = makeDeps(env);

const server = serve({ fetch: makeApp(deps).fetch, port: env.PORT, hostname: "0.0.0.0" }, (info) =>
  log.info({ port: info.port, release: env.RELEASE, embedder: deps.embedder.modelName }, "api listening"),
);

const stop = () => {
  log.info("shutting down");
  server.close(() => void deps.close().finally(() => process.exit(0)));
  setTimeout(() => process.exit(0), 10_000).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
