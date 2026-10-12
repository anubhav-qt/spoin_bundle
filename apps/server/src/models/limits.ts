import { z } from "zod";
import { getFromProxy, type ProxyConfig, postToProxy } from "./proxy.ts";

/**
 * How much Gemini each Antigravity account has left (breader's `shared/src/accounts.ts` and
 * `ai/tools/proxy.ts` on origin/dev, task 0045). Each account has a 5-hour limit and a weekly one,
 * covering all its Gemini models together. Google is asked through the proxy's api-call, which puts
 * the account's own token where $TOKEN$ is, so spoin never holds one. Checked against the owner's
 * two accounts on 2026-10-13.
 */

const QUOTA_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary";
const USER_AGENT = "antigravity/cli/1.0.13 (aidev_client; os_type=linux; arch=amd64)";

const Credentials = z.object({
  files: z
    .array(
      z.object({
        provider: z.string().optional(),
        disabled: z.boolean().optional(),
        auth_index: z.string().optional(),
        project_id: z.string().optional(),
      }),
    )
    .optional(),
});

/** The proxy's api-call answer: Google's status and its body, as text. */
const Called = z.object({ status_code: z.number().optional(), body: z.string().optional() });

const QuotaSummary = z.object({
  groups: z
    .array(
      z.object({
        buckets: z
          .array(
            z.object({
              bucketId: z.string().optional(),
              window: z.string().optional(),
              resetTime: z.string().optional(),
              remainingFraction: z.union([z.number(), z.string()]).optional(),
            }),
          )
          .optional(),
      }),
    )
    .optional(),
});

/** One of an account's Gemini limits. */
export interface GeminiWindow {
  /** "5h" or "weekly". */
  window: string;
  /** 0 to 100, to a tenth. */
  usedPercent: number;
  /** When it's back to full, if Google says. */
  resetsAt: string | null;
}

/** An account's Gemini limits from Google's answer, or null when the answer can't be read. */
export function geminiWindows(text: string): GeminiWindow[] | null {
  let parsed: z.infer<typeof QuotaSummary>;
  try {
    const answer = QuotaSummary.safeParse(JSON.parse(text));
    if (!answer.success) return null;
    parsed = answer.data;
  } catch {
    return null;
  }
  const windows: GeminiWindow[] = [];
  for (const group of parsed.groups ?? []) {
    for (const bucket of group.buckets ?? []) {
      // The other group is Claude and GPT, which spoin doesn't call.
      if (!bucket.bucketId?.startsWith("gemini-")) continue;
      const left = Number(bucket.remainingFraction);
      if (bucket.remainingFraction === undefined || !Number.isFinite(left)) continue;
      const usedPercent = Math.max(0, Math.min(100, Math.round((1 - left) * 1000) / 10));
      windows.push({ window: bucket.window ?? "", usedPercent, resetsAt: bucket.resetTime ?? null });
    }
  }
  return windows.length ? windows : null;
}

/**
 * When an account with these limits can call Gemini again: `now` when none is used up, else when
 * the last of the used-up ones fills; null when one that's used up doesn't say when.
 */
export function opensAt(windows: GeminiWindow[], now: number): number | null {
  let at = now;
  for (const w of windows) {
    if (w.usedPercent < 100) continue;
    if (!w.resetsAt) return null;
    const reset = Date.parse(w.resetsAt);
    if (!Number.isFinite(reset)) return null;
    at = Math.max(at, reset);
  }
  return at;
}

/**
 * When an Antigravity account will have Gemini to give: now if one has some left, the soonest refill
 * if none has, or null when no account's limits could be read. Throws a ProxyError when the proxy
 * itself can't be asked.
 */
export async function geminiOpensAt(
  config: ProxyConfig,
  fetchFn: typeof fetch = fetch,
  now: () => number = Date.now,
): Promise<number | null> {
  const listing = await getFromProxy(
    config,
    "/v8/management/credentials",
    "management",
    Credentials,
    fetchFn,
  );
  let soonest: number | null = null;
  for (const account of listing.files ?? []) {
    if (account.provider !== "antigravity" || account.disabled) continue;
    if (!account.auth_index || !account.project_id) continue;
    const request = {
      auth_index: account.auth_index,
      method: "POST",
      url: QUOTA_URL,
      header: {
        Authorization: "Bearer $TOKEN$",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
      },
      data: JSON.stringify({ project: account.project_id }),
    };
    const answer = await postToProxy(
      config,
      "/v8/management/requests/api-call",
      "management",
      Called,
      request,
      fetchFn,
    );
    if (!answer.body || (answer.status_code ?? 0) >= 300) continue;
    const windows = geminiWindows(answer.body);
    if (!windows) continue;
    const at = opensAt(windows, now());
    if (at === null) continue;
    if (soonest === null || at < soonest) soonest = at;
  }
  return soonest;
}
