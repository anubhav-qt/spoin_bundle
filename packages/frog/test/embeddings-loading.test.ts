import { describe, expect, it, vi } from "vitest";

// The weights come from Hugging Face on first use; here a stand-in whose first download fails.
const downloads = vi.hoisted(() => ({ failNext: true }));

vi.mock("@huggingface/transformers", () => {
  const tokenizer = (texts: string[]) => ({
    attention_mask: { tolist: () => texts.map(() => [1]) },
  });
  const model = async (inputs: { attention_mask: { tolist: () => number[][] } }) => {
    const rows = inputs.attention_mask.tolist().length;
    return { last_hidden_state: { dims: [rows, 1, 2], data: new Float32Array(rows * 2).fill(1) } };
  };
  return {
    env: {},
    AutoTokenizer: { from_pretrained: async () => tokenizer },
    AutoModel: {
      from_pretrained: async () => {
        if (downloads.failNext) {
          downloads.failNext = false;
          throw new Error("Unable to get model file path or buffer.");
        }
        return model;
      },
    },
  };
});

const { Qwen3OnnxEmbedder } = await import("../src/embeddings.ts");

describe("Qwen3OnnxEmbedder", () => {
  it("tries the download again after one fails, rather than failing every embed after it", async () => {
    const embedder = new Qwen3OnnxEmbedder();
    await expect(embedder.embedPassage(["raft"])).rejects.toThrow("Unable to get model file");
    const [vector] = await embedder.embedPassage(["raft"]);
    expect(vector).toHaveLength(2);
  });
});
