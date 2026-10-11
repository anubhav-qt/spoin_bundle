import { randomUUID } from "node:crypto";
import { getConnInfo } from "@hono/node-server/conninfo";
import type { Context, MiddlewareHandler } from "hono";
import type { AppEnv, Caller, Deps } from "../context.ts";
import type { Env } from "../env.ts";
import { log } from "../log.ts";
import { HttpError } from "./errors.ts";

export const REQUEST_ID_HEADER = "X-Request-ID";

/** Health is polled continuously; logging every hit would drown everything else. */
const QUIET_PATHS = new Set(["/health"]);

/**
 * The client's address, read only from the header the proxy in front writes itself
 * (CLIENT_IP_HEADER). A client can send any header it likes, so trusting another one
 * would let a script walk past the rate limits.
 */
export function clientIp(c: Context, from: Env["CLIENT_IP_HEADER"]): string {
  if (from === "cf-connecting-ip") {
    const ip = c.req.header("cf-connecting-ip")?.trim();
    if (ip) return ip;
  } else if (from === "x-forwarded-for") {
    // The proxy appends the address it saw, so the last entry is the real one.
    const hops = (c.req.header("x-forwarded-for") ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const last = hops.at(-1);
    if (last) return last;
  }
  try {
    return getConnInfo(c).remote.address ?? "unknown";
  } catch {
    return "unknown";
  }
}

/**
 * Assigns the request id (honouring one the edge already set, so one trace stays one
 * trace), the client address, and logs the outcome. 5xx at error so alerting can key
 * off level alone; a 4xx is usually the API working correctly.
 */
export function requestContext(env: Env): MiddlewareHandler<AppEnv> {
  return async (c, next) => {
    // Bounded and printable: it reaches a log line and a response header, and the client sent it.
    const incoming = (c.req.header(REQUEST_ID_HEADER) ?? "").trim().slice(0, 64);
    const requestId = /^[\x20-\x7e]+$/.test(incoming)
      ? incoming
      : randomUUID().replaceAll("-", "").slice(0, 16);
    c.set("requestId", requestId);
    c.set("ip", clientIp(c, env.CLIENT_IP_HEADER));
    c.set("caller", null);
    const start = performance.now();
    await next();
    c.header(REQUEST_ID_HEADER, requestId);
    const ms = Math.round(performance.now() - start);
    const status = c.res.status;
    let level: "error" | "trace" | "info" = "info";
    if (status >= 500) level = "error";
    else if (QUIET_PATHS.has(c.req.path)) level = "trace";
    log[level](
      { requestId, userId: c.var.caller?.id, method: c.req.method, path: c.req.path, status, ms },
      "request",
    );
  };
}

/**
 * Resolves the session behind `Authorization: Bearer` (Better Auth's bearer plugin)
 * into `caller`. Never rejects: routes that need a user say so with `needUser`.
 */
export function resolveCaller(deps: Deps): MiddlewareHandler<AppEnv> {
  return async (c, next) => {
    if (c.req.header("authorization")) {
      const session = await deps.auth.api.getSession({ headers: c.req.raw.headers });
      if (session) {
        const user = session.user as typeof session.user & {
          isAnonymous?: boolean | null;
          role?: string | null;
        };
        c.set("caller", { id: user.id, isGuest: Boolean(user.isAnonymous), isAdmin: user.role === "admin" });
      }
    }
    await next();
  };
}

/** The caller, or a 401 the client answers by signing in again. */
export function needUser(c: Context<AppEnv>): Caller {
  const caller = c.var.caller;
  if (!caller) throw new HttpError(401, "Not authenticated");
  return caller;
}

/** Admin pages and endpoints (ADR-0106; closes task 0035's missing role gate). */
export function needAdmin(c: Context<AppEnv>): Caller {
  const caller = needUser(c);
  if (!caller.isAdmin) throw new HttpError(403, "Admins only");
  return caller;
}

/** A fixed-window limit per address, in memory. Each process counts on its own. */
export function rateLimit(opts: { max: number; windowMs: number }): MiddlewareHandler<AppEnv> {
  const hits = new Map<string, { count: number; resetAt: number }>();
  return async (c, next) => {
    const now = Date.now();
    if (hits.size > 10_000) for (const [k, v] of hits) if (v.resetAt <= now) hits.delete(k);
    const key = c.var.ip;
    let h = hits.get(key);
    if (!h || h.resetAt <= now) {
      h = { count: 0, resetAt: now + opts.windowMs };
      hits.set(key, h);
    }
    h.count += 1;
    if (h.count > opts.max) {
      c.header("Retry-After", String(Math.ceil((h.resetAt - now) / 1000)));
      throw new HttpError(429, "Too many requests. Wait a minute and try again.");
    }
    await next();
  };
}
