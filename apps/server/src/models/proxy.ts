import type { Api, Model, ModelThinkingLevel, ThinkingLevel, ThinkingLevelMap } from "@spoin/pi-ai";
import { z } from "zod";
import type { Env } from "../env.ts";

/**
 * CLIProxyAPI, which serves Gemini from the owner's Antigravity sign-ins (task 0045): what it
 * serves, described by its own model definitions, and the accounts signed in to it. Trotter's
 * `harness/src/proxy.ts` and `models.ts`, with zod for typebox. The keys are never logged or put
 * in an error.
 */

const TIMEOUT_MS = 15_000;

export interface ProxyConfig {
  /** The base address, without a trailing slash. */
  url: string;
  /** The key the model endpoints take. */
  apiKey: string;
  /** The key the management API takes; null when the process never reads it. */
  managementKey: string | null;
}

export class ProxyError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "ProxyError";
  }
}

/** Null when there's no API key: no Gemini in this process. */
export function proxyConfig(env: Env): ProxyConfig | null {
  if (!env.CLIPROXY_API_KEY) return null;
  return {
    url: env.CLIPROXY_URL.trim().replace(/\/+$/, ""),
    apiKey: env.CLIPROXY_API_KEY.trim(),
    managementKey: env.CLIPROXY_MANAGEMENT_KEY?.trim() || null,
  };
}

/** Reads one endpoint and checks its answer. `key` says which of the two keys it takes. */
export async function getFromProxy<Schema extends z.ZodType>(
  config: ProxyConfig,
  path: string,
  key: "api" | "management",
  schema: Schema,
  fetchFn: typeof fetch = fetch,
): Promise<z.infer<Schema>> {
  const token = key === "api" ? config.apiKey : config.managementKey;
  if (!token)
    throw new ProxyError("CLIPROXY_MANAGEMENT_KEY is not set, so the proxy's accounts can't be read.");
  let response: Response;
  try {
    response = await fetchFn(config.url + path, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    // fetch throws only when nothing answers.
    throw new ProxyError(`CLIProxyAPI isn't answering at ${config.url}. Start it: npm run stack`, {
      cause: error,
    });
  }
  if (!response.ok) {
    throw new ProxyError(
      `CLIProxyAPI answered ${response.status} for ${path}. Check the keys in infra/.env.`,
    );
  }
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) throw new ProxyError(`CLIProxyAPI's answer for ${path} isn't what spoin reads.`);
  return parsed.data;
}

const ServedModels = z.object({ data: z.array(z.object({ id: z.string(), owned_by: z.string() })) });
export type ServedModel = z.infer<typeof ServedModels>["data"][number];

const ModelDefinition = z.object({
  id: z.string(),
  display_name: z.string().optional(),
  context_length: z.number().int().positive().optional(),
  max_completion_tokens: z.number().int().positive().optional(),
  supportedInputModalities: z.array(z.string()).optional(),
  supportedOutputModalities: z.array(z.string()).optional(),
  thinking: z
    .object({ zero_allowed: z.boolean().optional(), levels: z.array(z.string()).optional() })
    .optional(),
});
export type ModelDefinition = z.infer<typeof ModelDefinition>;
type Thinking = NonNullable<ModelDefinition["thinking"]>;

const ModelDefinitions = z.object({ models: z.array(ModelDefinition).optional() });

/** The levels above off, weakest first. */
const THINKING_LEVELS: ModelThinkingLevel[] = ["minimal", "low", "medium", "high", "xhigh", "max"];

/** Asks the proxy what it serves, and describes each model a chat can run on. */
export async function loadModels(config: ProxyConfig, fetchFn: typeof fetch = fetch): Promise<Model<Api>[]> {
  const served = await getFromProxy(config, "/v1/models", "api", ServedModels, fetchFn);
  const channels = new Set(served.data.map((model) => model.owned_by));
  const definitions = new Map<string, ModelDefinition[]>();
  for (const channel of channels) {
    const path = `/v8/management/routing/model-definitions/${encodeURIComponent(channel)}`;
    const body = await getFromProxy(config, path, "management", ModelDefinitions, fetchFn);
    definitions.set(channel, body.models ?? []);
  }
  return describeModels(config.url, served.data, definitions);
}

/**
 * pi's model objects for the served models. A model is left out when its definition doesn't
 * give the context window and output limit (compaction needs the window), or when it answers
 * with images instead of the text and tool calls a chat runs on.
 */
export function describeModels(
  proxyUrl: string,
  served: ServedModel[],
  definitions: Map<string, ModelDefinition[]>,
): Model<Api>[] {
  const models: Model<Api>[] = [];
  for (const servedModel of served) {
    const definition = (definitions.get(servedModel.owned_by) ?? []).find((d) => d.id === servedModel.id);
    if (!definition) continue;
    const model = describeModel(proxyUrl, servedModel.owned_by, definition);
    if (model) models.push(model);
  }
  return models;
}

/** The model with this id, or an error naming the ones that are served. */
export function findModel(models: Model<Api>[], id: string): Model<Api> {
  const model = models.find((candidate) => candidate.id === id);
  if (model) return model;
  const ids = models.map((candidate) => candidate.id).join(", ");
  throw new ProxyError(
    `CLIProxyAPI doesn't serve ${id} to the signed-in accounts. It serves: ${ids || "nothing"}.`,
  );
}

/**
 * Gemini 3.8 Flash at medium thinking: toad_sage, the main chats, research, the gate, and on the
 * request path grading and AskAI (task 0045). The proxy names it `-high`, but it takes low, medium
 * and high, and each call says which.
 */
export const GEMINI_ID = "gemini-3.8-flash-high";
export const GEMINI_THINKING: ThinkingLevel = "medium";

/** Looks Gemini up once per process. A failed lookup isn't kept, so the next call asks again. */
export function geminiFrom(config: ProxyConfig, fetchFn: typeof fetch = fetch): () => Promise<Model<Api>> {
  let found: Promise<Model<Api>> | null = null;
  return () => {
    if (!found) {
      found = loadModels(config, fetchFn).then((models) => findModel(models, GEMINI_ID));
      found.catch(() => {
        found = null;
      });
    }
    return found;
  };
}

function describeModel(
  proxyUrl: string,
  channel: string,
  definition: ModelDefinition,
): Model<Api> | undefined {
  const contextWindow = definition.context_length;
  const maxTokens = definition.max_completion_tokens;
  if (contextWindow === undefined || maxTokens === undefined) return undefined;
  if (definition.supportedOutputModalities?.includes("image")) return undefined;
  const { api, path } = apiFor(definition.id, channel);
  const model: Model<Api> = {
    id: definition.id,
    name: definition.display_name ?? definition.id,
    api,
    provider: channel,
    baseUrl: proxyUrl + path,
    input: definition.supportedInputModalities?.includes("image") ? ["text", "image"] : ["text"],
    // The subscriptions are paid for already; no call costs anything extra.
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    reasoning: definition.thinking !== undefined,
    contextWindow,
    maxTokens,
  };
  if (definition.thinking) model.thinkingLevelMap = thinkingLevelMapOf(definition.thinking);
  return model;
}

/** Which API the proxy speaks for a model's family, and where it serves it. */
function apiFor(id: string, channel: string): { api: Api; path: string } {
  const lowerId = id.toLowerCase();
  if (lowerId.startsWith("gemini")) return { api: "google-generative-ai", path: "/v1beta" };
  // The Anthropic SDK adds /v1/messages itself.
  if (lowerId.startsWith("claude")) return { api: "anthropic-messages", path: "" };
  if (channel === "codex" || lowerId.includes("codex") || lowerId.startsWith("gpt-5")) {
    return { api: "openai-responses", path: "/v1" };
  }
  return { api: "openai-completions", path: "/v1" };
}

/**
 * pi's map of the thinking levels a model takes; a level it can't take is null. Gemini names its
 * levels, and they go on the wire as named. The others take a token budget or an effort for each
 * level up to high.
 */
function thinkingLevelMapOf(thinking: Thinking): ThinkingLevelMap {
  const map: ThinkingLevelMap = {};
  if (!thinking.zero_allowed) map.off = null;
  if (thinking.levels) {
    const named = new Set(thinking.levels.map((level) => level.toLowerCase()));
    for (const level of THINKING_LEVELS) map[level] = named.has(level) ? level : null;
    return map;
  }
  map.xhigh = null;
  map.max = null;
  return map;
}

const AuthFiles = z.object({
  files: z.array(
    z.object({
      label: z.string().optional(),
      email: z.string().optional(),
      provider: z.string().optional(),
      status: z.string().optional(),
      status_message: z.string().optional(),
      disabled: z.boolean().optional(),
      unavailable: z.boolean().optional(),
      success: z.number().optional(),
      failed: z.number().optional(),
    }),
  ),
});

export interface ProxyAccount {
  /** The account's email, as the proxy labels it. Shown to the admin only. */
  account: string;
  provider: string;
  status: string;
  statusMessage: string;
  disabled: boolean;
  unavailable: boolean;
  /** Calls since the proxy started. */
  succeeded: number;
  failed: number;
}

/** The accounts signed in to the proxy, from its management API. */
export async function loadAccounts(
  config: ProxyConfig,
  fetchFn: typeof fetch = fetch,
): Promise<ProxyAccount[]> {
  const body = await getFromProxy(config, "/v0/management/auth-files", "management", AuthFiles, fetchFn);
  return body.files.map((file) => ({
    account: file.email ?? file.label ?? "unknown",
    provider: file.provider ?? "unknown",
    status: file.status ?? "unknown",
    statusMessage: file.status_message ?? "",
    disabled: file.disabled ?? false,
    unavailable: file.unavailable ?? false,
    succeeded: file.success ?? 0,
    failed: file.failed ?? 0,
  }));
}
