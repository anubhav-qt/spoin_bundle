import { readFileSync } from "node:fs";
import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { loadEnv } from "../env.ts";
import { log } from "../log.ts";
import { connectMonitor, readChat, readRunPrompt, readState } from "./queries.ts";

/*
 * The run monitor (task 0045): a local page drawing a box per chat of the pipeline, live, with any
 * chat's runs, transcript and records a click away. A development tool, never in an image: it reads
 * the database the stack runs on, and only reads it.
 */

const PORT = 4040;

const env = loadEnv();
const { pool, db } = connectMonitor(env.DATABASE_URL);
const page = readFileSync(new URL("./page.html", import.meta.url), "utf8");
const script = readFileSync(new URL("./page.js", import.meta.url), "utf8");

/** A position in a transcript or the record log; anything else starts from the beginning. */
function positionFrom(value: string | undefined): number {
  const position = Number(value);
  if (!Number.isInteger(position) || position < 0) return 0;
  return position;
}

const app = new Hono();
app.get("/", (c) => c.html(page));
app.get("/page.js", (c) => c.body(script, 200, { "content-type": "text/javascript; charset=utf-8" }));
app.get("/api/state", async (c) => c.json(await readState(db)));
app.get("/api/chats/:id", async (c) => {
  const afterMessage = positionFrom(c.req.query("afterMessage"));
  const afterRecord = positionFrom(c.req.query("afterRecord"));
  const detail = await readChat(db, c.req.param("id"), afterMessage, afterRecord);
  if (!detail) return c.notFound();
  return c.json(detail);
});
app.get("/api/runs/:id/prompt", async (c) => {
  const prompt = await readRunPrompt(db, c.req.param("id"));
  if (prompt === undefined) return c.notFound();
  return c.text(prompt);
});
app.onError((error, c) => {
  // drizzle's error carries the whole query; Postgres's own reason is its cause.
  const reason = String(error.cause ?? error);
  log.error({ reason }, "the monitor couldn't read the run");
  return c.json({ error: reason }, 500);
});

const server = serve({ fetch: app.fetch, port: PORT, hostname: "127.0.0.1" }, (info) =>
  log.info(`the run monitor is on http://localhost:${info.port}`),
);

const stop = () => {
  server.close(() => void pool.end().finally(() => process.exit(0)));
  setTimeout(() => process.exit(0), 5_000).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
