import { createHash } from "node:crypto";
import { Worker } from "node:worker_threads";
import type { EmbedReply, EmbedRequest, EmbedWorkerData } from "./embed-worker.ts";

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
 * `Qwen3-Embedding-0.6B` as ONNX, on the CPU (ADR-0106), in a worker thread (embed-worker.ts):
 * onnxruntime-node runs an inference synchronously on the thread that asks, and on the main thread
 * eight helpers embedding at once held every fetch, Postgres connection and model stream for
 * seconds a step (the C++ stage 2 run, 2026-10-14: fetches of 10 to 170 seconds, some timing out).
 *
 * Loaded lazily on first use, once per process: the weights are hundreds of
 * megabytes and most processes that import frog never embed anything.
 */
export class Qwen3OnnxEmbedder implements Embedder {
  readonly modelName: string;
  readonly #data: EmbedWorkerData;
  #worker: Worker | null = null;
  #nextId = 0;
  readonly #waiting = new Map<
    number,
    { resolve: (vectors: number[][]) => void; reject: (error: Error) => void }
  >();

  constructor(
    opts: {
      repo?: string;
      dtype?: OnnxDtype;
      batchSize?: number;
      cacheDir?: string;
      transformers?: string;
    } = {},
  ) {
    const dtype = opts.dtype ?? "q8";
    this.#data = {
      transformers: opts.transformers ?? "@huggingface/transformers",
      repo: opts.repo ?? "onnx-community/Qwen3-Embedding-0.6B-ONNX",
      dtype,
      // One text at a time: embedding ten Rust Book chapters peaked at 3.1 GB in batches of 8, 2.3 GB
      // in 2s and 1.8 GB alone, in about the same time, and the 3.1 GB got the worker killed (task 0045).
      batchSize: opts.batchSize ?? 1,
      cacheDir: opts.cacheDir,
    };
    this.modelName = `Qwen/Qwen3-Embedding-0.6B:onnx-${dtype}`;
  }

  async embedPassage(texts: string[]): Promise<number[][]> {
    return this.#encode(texts);
  }

  async embedQuery(texts: string[]): Promise<number[][]> {
    return this.#encode(texts.map((text) => `${QWEN3_QUERY_PREFIX}${text}`));
  }

  #encode(texts: string[]): Promise<number[][]> {
    const worker = this.#started();
    const id = this.#nextId++;
    const vectors = new Promise<number[][]>((resolve, reject) => this.#waiting.set(id, { resolve, reject }));
    // The thread keeps the process alive only while an embed waits on it.
    worker.ref();
    const request: EmbedRequest = { id, texts };
    worker.postMessage(request);
    return vectors;
  }

  #started(): Worker {
    if (this.#worker) return this.#worker;
    const worker = new Worker(new URL("./embed-worker.ts", import.meta.url), { workerData: this.#data });
    worker.on("message", (reply: EmbedReply) => {
      const waiting = this.#waiting.get(reply.id);
      if (!waiting) return;
      this.#waiting.delete(reply.id);
      if (this.#waiting.size === 0) worker.unref();
      if ("error" in reply) waiting.reject(new Error(reply.error));
      else waiting.resolve(reply.vectors);
    });
    // A thread that died (out of memory, say) fails what waited on it, and the next embed starts another.
    const died = (error: Error) => {
      if (this.#worker === worker) this.#worker = null;
      for (const waiting of this.#waiting.values()) waiting.reject(error);
      this.#waiting.clear();
    };
    worker.on("error", died);
    worker.on("exit", (code) => died(new Error(`The embedding thread exited with code ${code}.`)));
    worker.unref();
    this.#worker = worker;
    return worker;
  }
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
