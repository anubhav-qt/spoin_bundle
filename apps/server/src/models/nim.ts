import type { Model, SamplingParams } from "@spoin/pi-ai";

/**
 * NVIDIA's free API (build.nvidia.com) on pi's OpenAI chat API, with breader's ladder
 * (`ai/tools/kimi.ts` on breader's origin/dev at `e3a3bce`, 2026-10-11): Kimi K3 at high reasoning
 * as the primary, Nemotron 3 Ultra only while it is down. The key is shared with breader.
 */

const NIM_URL = "https://integrate.api.nvidia.com/v1";

export interface Rung {
  model: Model<"openai-completions">;
  /** Calls at once. */
  maxInFlight: number;
  /** One of the top models, sharing the calls with the others as an equal. */
  primary?: boolean;
}

/**
 * maxTokens: every model answers in at most 130,000 tokens. NVIDIA caps Kimi K3 at 131,072 since
 * 2026-10-11 (it took 1,048,576 the day before), and Kimi counts the prompt in a limit of its own;
 * a call refused for asking too much is asked again for what the refusal allows (balancer.ts), so
 * a cap NVIDIA moves again costs one refused call, not the call. contextWindow: both models' cards
 * on build.nvidia.com give 1,048,576.
 */
function nim(id: string, name: string, samplingParams?: SamplingParams): Model<"openai-completions"> {
  return {
    id,
    name,
    api: "openai-completions",
    provider: "nvidia",
    baseUrl: NIM_URL,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    // pi sends no reasoning effort to NVIDIA, so Kimi's goes in the body as breader sends it.
    reasoning: samplingParams !== undefined,
    contextWindow: 1_048_576,
    maxTokens: 130_000,
    ...(samplingParams ? { samplingParams } : {}),
  };
}

export const NIM_LADDER: Rung[] = [
  {
    model: nim("moonshotai/kimi-k3", "Kimi K3", { reasoning_effort: "high" }),
    maxInFlight: 24,
    primary: true,
  },
  { model: nim("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra"), maxInFlight: 24 },
];
