import type { ModelAccountsOut, ModelCallFailure } from "@spoin/shared";
import { and, desc, eq, gte, sql } from "drizzle-orm";
import { z } from "zod";
import type { Db } from "../db/client.ts";
import { modelCall } from "../db/schema.ts";
import type { Env } from "../env.ts";
import { isoOrNull } from "../lib/wire.ts";
import { getFromProxy, loadAccounts, type ProxyAccount, ProxyError, proxyConfig } from "./proxy.ts";

/*
 * The model accounts page (task 0045): CLIProxyAPI's signed-in accounts and the models it serves,
 * read live from its management API, and per model from `model_call` over the last 24 hours.
 */

const WINDOW_HOURS = 24;

const Served = z.object({ data: z.array(z.object({ id: z.string() })) });

async function readProxy(
  env: Env,
): Promise<{ error: string | null; accounts: ProxyAccount[]; served: string[] }> {
  const config = proxyConfig(env);
  if (!config) return { error: "CLIPROXY_API_KEY is not set.", accounts: [], served: [] };
  try {
    const [accounts, served] = await Promise.all([
      loadAccounts(config),
      getFromProxy(config, "/v1/models", "api", Served),
    ]);
    return { error: null, accounts, served: served.data.map((m) => m.id).sort() };
  } catch (error) {
    if (error instanceof ProxyError) return { error: error.message, accounts: [], served: [] };
    throw error;
  }
}

export async function modelAccounts(db: Db, env: Env): Promise<ModelAccountsOut> {
  const since = sql`now() - make_interval(hours => ${WINDOW_HOURS})`;
  const inWindow = gte(modelCall.startedAt, since);

  const [proxy, totals, failures, lastFailures] = await Promise.all([
    readProxy(env),
    db
      .select({
        provider: modelCall.provider,
        model: modelCall.model,
        calls: sql<number>`count(*)::int`,
        ok: sql<number>`(count(*) filter (where ${modelCall.ok}))::int`,
        lastOkAt: sql<Date | null>`max(${modelCall.startedAt}) filter (where ${modelCall.ok})`,
        lastFailureAt: sql<Date | null>`max(${modelCall.startedAt}) filter (where not ${modelCall.ok})`,
        medianFirstTokenMs: sql<
          number | null
        >`(percentile_cont(0.5) within group (order by ${modelCall.firstTokenMs}) filter (where ${modelCall.ok}))::int`,
        promptTokens: sql<number>`coalesce(sum(${modelCall.promptTokens}), 0)::int`,
        outputTokens: sql<number>`coalesce(sum(${modelCall.outputTokens}), 0)::int`,
      })
      .from(modelCall)
      .where(inWindow)
      .groupBy(modelCall.provider, modelCall.model)
      .orderBy(modelCall.provider, modelCall.model),
    db
      .select({ model: modelCall.model, kind: modelCall.failure, count: sql<number>`count(*)::int` })
      .from(modelCall)
      .where(and(inWindow, eq(modelCall.ok, false)))
      .groupBy(modelCall.model, modelCall.failure),
    db
      .selectDistinctOn([modelCall.model], {
        model: modelCall.model,
        kind: modelCall.failure,
        reason: modelCall.reason,
      })
      .from(modelCall)
      .where(and(inWindow, eq(modelCall.ok, false)))
      .orderBy(modelCall.model, desc(modelCall.startedAt)),
  ]);

  return {
    proxy_error: proxy.error,
    accounts: proxy.accounts.map((a) => ({
      account: a.account,
      provider: a.provider,
      status: a.status,
      status_message: a.statusMessage,
      disabled: a.disabled,
      unavailable: a.unavailable,
      succeeded: a.succeeded,
      failed: a.failed,
    })),
    served: proxy.served,
    nim_configured: Boolean(env.NVIDIA_NIM_API_KEY),
    window_hours: WINDOW_HOURS,
    stats: totals.map((t) => {
      const last = lastFailures.find((f) => f.model === t.model);
      return {
        provider: t.provider,
        model: t.model,
        calls: t.calls,
        ok: t.ok,
        failures: failures
          .filter((f) => f.model === t.model && f.kind !== null)
          .map((f) => ({ kind: f.kind as ModelCallFailure, count: f.count }))
          .sort((a, b) => b.count - a.count),
        last_ok_at: isoOrNull(t.lastOkAt === null ? null : new Date(t.lastOkAt)),
        last_failure_at: isoOrNull(t.lastFailureAt === null ? null : new Date(t.lastFailureAt)),
        last_failure: last?.kind ? { kind: last.kind, reason: last.reason } : null,
        median_first_token_ms: t.medianFirstTokenMs,
        prompt_tokens: t.promptTokens,
        output_tokens: t.outputTokens,
      };
    }),
  };
}
