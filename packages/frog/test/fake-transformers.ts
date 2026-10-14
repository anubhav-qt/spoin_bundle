/*
 * A stand-in for @huggingface/transformers, which embed-worker.ts loads in the embedder's tests: a
 * vi.mock can't reach the worker's thread. The repo "fails-once" fails its first download, and a
 * text "block" holds the thread for 300 ms, as onnxruntime-node's inference does.
 */

const failed = new Set<string>();

interface Inputs {
  attention_mask: { tolist: () => number[][] };
  texts: string[];
}

function tokenizer(texts: string[]): Inputs {
  return { attention_mask: { tolist: () => texts.map(() => [1]) }, texts };
}

async function model(inputs: Inputs) {
  if (inputs.texts.includes("block")) {
    const until = Date.now() + 300;
    while (Date.now() < until) {
      // Busy, as a synchronous inference is.
    }
  }
  const rows = inputs.texts.length;
  return { last_hidden_state: { dims: [rows, 1, 2], data: new Float32Array(rows * 2).fill(1) } };
}

export const env = {};

export const AutoTokenizer = { from_pretrained: async () => tokenizer };

export const AutoModel = {
  from_pretrained: async (repo: string) => {
    if (repo === "fails-once" && !failed.has(repo)) {
      failed.add(repo);
      throw new Error("Unable to get model file path or buffer.");
    }
    return model;
  },
};
