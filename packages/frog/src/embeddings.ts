import { createHash } from "node:crypto";

/**
 * Local embeddings. Hard rule 5: these never run against a paid or quota'd API.
 *
 * ONE embedder for cards, topics, questions, scenes, AskAI's gate and corpus retrieval
 * alike (ADR-0097), and the dimension is this constant, not a setting: the vector
 * columns were created with it, so a configurable that disagreed could only produce
 * vectors the database refuses.
 */
export const EMBEDDING_DIM = 1024;

/**
 * Asymmetric by design (ADR-0092). Retrieval models encode a *query* and a *passage*
 * differently; Qwen3-Embedding wraps a query in an instruction and leaves passages
 * bare. Getting this wrong is a silent recall loss, so callers must say which side
 * they are on.
 */
export interface Embedder {
  /**
   * What produced these vectors, stamped on every embedded row (task 0039). A vector
   * that cannot name its model is a vector nobody can safely trust later.
   */
  readonly modelName: string;
  /** Corpus-side text: chunks, card bodies, topic descriptions, image descriptions. */
  embedPassage(texts: string[]): Promise<number[][]>;
  /** Search-side text: a retrieval query, an AskAI turn. */
  embedQuery(texts: string[]): Promise<number[][]>;
}

/**
 * A dependency-free deterministic stand-in so the stack boots and tests run with no
 * model weights. **Not semantically meaningful**: any threshold measured against it
 * means nothing, and a row stamped `hash` should be greppable rather than plausible.
 */
export class HashEmbedder implements Embedder {
  readonly modelName = "hash";
  readonly #dim: number;

  constructor(dim: number = EMBEDDING_DIM) {
    this.#dim = dim;
  }

  async embedPassage(texts: string[]): Promise<number[][]> {
    return texts.map((text) => this.#one(text));
  }

  /** Identical to `embedPassage`: a token hash has no query/passage asymmetry. */
  async embedQuery(texts: string[]): Promise<number[][]> {
    return this.embedPassage(texts);
  }

  #one(text: string): number[] {
    const vector = new Array<number>(this.#dim).fill(0);
    for (const token of text.toLowerCase().split(/\s+/u).filter(Boolean)) {
      const digest = createHash("sha256").update(token).digest();
      for (let offset = 0; offset < 32; offset += 4) {
        const index = digest.readUInt16BE(offset) % this.#dim;
        vector[index] = (vector[index] ?? 0) + 1;
      }
    }
    return l2Normalize(vector);
  }
}

/** The instruction sentence-transformers ships as Qwen3-Embedding's `query` prompt. */
const QWEN3_QUERY_PREFIX =
  "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:";

/** Precision of the ONNX weights. Part of the model stamp: q8 and fp32 vectors are not one space. */
export type OnnxDtype = "fp32" | "fp16" | "q8";

/**
 * `Qwen3-Embedding-0.6B` as ONNX, on the CPU (ADR-0106). Last-token pooling and L2
 * normalization, as the model card specifies. The last token is found from the
 * attention mask, so the result is right whichever side the tokenizer pads.
 *
 * Loaded lazily on first use, once per process: the weights are hundreds of
 * megabytes and most processes that import frog never embed anything.
 */
export class Qwen3OnnxEmbedder implements Embedder {
  readonly modelName: string;
  readonly #repo: string;
  readonly #dtype: OnnxDtype;
  readonly #batchSize: number;
  #loading: Promise<Loaded> | null = null;

  constructor(opts: { repo?: string; dtype?: OnnxDtype; batchSize?: number; cacheDir?: string } = {}) {
    this.#repo = opts.repo ?? "onnx-community/Qwen3-Embedding-0.6B-ONNX";
    this.#dtype = opts.dtype ?? "q8";
    this.#batchSize = opts.batchSize ?? 8;
    this.modelName = `Qwen/Qwen3-Embedding-0.6B:onnx-${this.#dtype}`;
    if (opts.cacheDir) this.#cacheDir = opts.cacheDir;
  }

  #cacheDir: string | undefined;

  async embedPassage(texts: string[]): Promise<number[][]> {
    return this.#encode(texts);
  }

  async embedQuery(texts: string[]): Promise<number[][]> {
    return this.#encode(texts.map((text) => `${QWEN3_QUERY_PREFIX}${text}`));
  }

  async #encode(texts: string[]): Promise<number[][]> {
    const { tokenizer, model } = await this.#load();
    const out: number[][] = [];
    for (let start = 0; start < texts.length; start += this.#batchSize) {
      const batch = texts.slice(start, start + this.#batchSize);
      const inputs = tokenizer(batch, { padding: true, truncation: true, max_length: 2048 });
      const { last_hidden_state: hidden } = await model(inputs);
      const [rows, seq, dim] = hidden.dims as [number, number, number];
      const data = hidden.data as Float32Array;
      const mask = inputs.attention_mask.tolist() as number[][];
      for (let row = 0; row < rows; row++) {
        const last = lastAttended(mask[row] ?? [], seq);
        const from = (row * seq + last) * dim;
        out.push(l2Normalize(Array.from(data.subarray(from, from + dim))));
      }
    }
    return out;
  }

  #load(): Promise<Loaded> {
    this.#loading ??= (async () => {
      const { AutoModel, AutoTokenizer, env } = await import("@huggingface/transformers");
      if (this.#cacheDir) env.cacheDir = this.#cacheDir;
      const tokenizer = await AutoTokenizer.from_pretrained(this.#repo);
      const model = await AutoModel.from_pretrained(this.#repo, { dtype: this.#dtype, device: "cpu" });
      return { tokenizer, model } as unknown as Loaded;
    })();
    return this.#loading;
  }
}

interface Tensor {
  dims: number[];
  data: Float32Array | number[];
  tolist(): unknown;
}

interface Loaded {
  tokenizer: (texts: string[], opts: object) => { attention_mask: Tensor } & Record<string, Tensor>;
  model: (inputs: object) => Promise<{ last_hidden_state: Tensor }>;
}

function lastAttended(mask: number[], seq: number): number {
  for (let i = seq - 1; i >= 0; i--) {
    if (mask[i] === 1) return i;
  }
  return seq - 1;
}

export function l2Normalize(vector: number[]): number[] {
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  return norm ? vector.map((value) => value / norm) : vector;
}

export function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    dot += x * y;
    na += x * x;
    nb += y * y;
  }
  return na && nb ? dot / Math.sqrt(na * nb) : 0;
}
