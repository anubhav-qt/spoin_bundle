import { parentPort, workerData } from "node:worker_threads";

/*
 * Qwen3OnnxEmbedder's model, in a worker thread of its own (embeddings.ts). onnxruntime-node runs
 * an inference synchronously on the thread that asks for it, so on the main thread every embed held
 * the process's fetches, Postgres connections and model streams. This file imports nothing of
 * frog's: the server's build copies it beside the bundle, and Node strips its types.
 */

/** What the embedder sends: the model to load, from the main thread's constructor options. */
export interface EmbedWorkerData {
  /** The module to load the model with: @huggingface/transformers, or a test's stand-in. */
  transformers: string;
  repo: string;
  dtype: string;
  batchSize: number;
  cacheDir: string | undefined;
}

export interface EmbedRequest {
  id: number;
  texts: string[];
}

export type EmbedReply = { id: number; vectors: number[][] } | { id: number; error: string };

interface Tensor {
  dims: number[];
  data: Float32Array | number[];
  tolist(): unknown;
}

interface Loaded {
  tokenizer: (texts: string[], opts: object) => { attention_mask: Tensor } & Record<string, Tensor>;
  model: (inputs: object) => Promise<{ last_hidden_state: Tensor }>;
}

const options = workerData as EmbedWorkerData;
let loading: Promise<Loaded> | null = null;

function load(): Promise<Loaded> {
  loading ??= (async () => {
    const { AutoModel, AutoTokenizer, env } = await import(options.transformers);
    if (options.cacheDir) env.cacheDir = options.cacheDir;
    const tokenizer = await AutoTokenizer.from_pretrained(options.repo);
    const model = await AutoModel.from_pretrained(options.repo, { dtype: options.dtype, device: "cpu" });
    return { tokenizer, model } as Loaded;
  })().catch((error: unknown) => {
    // A download that failed once (the first one in a fresh volume did) is tried again on the
    // next call; kept, it would fail every embed until the process restarts.
    loading = null;
    throw error;
  });
  return loading;
}

/** Last-token pooling and L2 normalization, as the model card specifies. */
async function encode(texts: string[]): Promise<number[][]> {
  const { tokenizer, model } = await load();
  const out: number[][] = [];
  for (let start = 0; start < texts.length; start += options.batchSize) {
    const batch = texts.slice(start, start + options.batchSize);
    const inputs = tokenizer(batch, { padding: true, truncation: true, max_length: 2048 });
    const { last_hidden_state: hidden } = await model(inputs);
    const [rows, seq, dim] = hidden.dims as [number, number, number];
    const data = hidden.data as Float32Array;
    const mask = inputs.attention_mask.tolist() as number[][];
    for (let row = 0; row < rows; row++) {
      const last = lastAttended(mask[row] ?? [], seq);
      const from = (row * seq + last) * dim;
      out.push(normalized(Array.from(data.subarray(from, from + dim))));
    }
  }
  return out;
}

/** The last token the mask attends to, so the result is right whichever side the tokenizer pads. */
function lastAttended(mask: number[], seq: number): number {
  for (let i = seq - 1; i >= 0; i--) {
    if (mask[i] === 1) return i;
  }
  return seq - 1;
}

/** embeddings.ts's l2Normalize, here again since this file imports nothing of frog's. */
function normalized(vector: number[]): number[] {
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (!norm) return vector;
  return vector.map((value) => value / norm);
}

// One request at a time: two at once would hold two inputs' activations in memory for no speed,
// since one inference already uses every core.
let queue: Promise<void> = Promise.resolve();
parentPort?.on("message", (request: EmbedRequest) => {
  queue = queue.then(async () => {
    let reply: EmbedReply;
    try {
      reply = { id: request.id, vectors: await encode(request.texts) };
    } catch (error) {
      let message = String(error);
      if (error instanceof Error) message = error.message;
      reply = { id: request.id, error: message };
    }
    parentPort?.postMessage(reply);
  });
});
