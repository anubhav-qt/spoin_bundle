import { describe, expect, it } from "vitest";
import { Qwen3OnnxEmbedder } from "../src/embeddings.ts";

// The model runs in a thread of its own, which loads this stand-in in place of the real weights.
const transformers = new URL("./fake-transformers.ts", import.meta.url).href;

describe("Qwen3OnnxEmbedder", () => {
  it("tries the download again after one fails, rather than failing every embed after it", async () => {
    const embedder = new Qwen3OnnxEmbedder({ repo: "fails-once", transformers });
    await expect(embedder.embedPassage(["raft"])).rejects.toThrow("Unable to get model file");
    const [vector] = await embedder.embedPassage(["raft"]);
    expect(vector).toHaveLength(2);
    expect(vector?.[0]).toBeCloseTo(Math.SQRT1_2);
  });

  it("embeds off the main thread, so a slow inference never holds the process", async () => {
    // On the main thread, eight helpers embedding at once held every fetch for seconds a step.
    const embedder = new Qwen3OnnxEmbedder({ repo: "ok", transformers });
    await embedder.embedPassage(["warm"]);
    let last = Date.now();
    let longest = 0;
    const ticks = setInterval(() => {
      longest = Math.max(longest, Date.now() - last);
      last = Date.now();
    }, 10);
    const vectors = await embedder.embedPassage(["block", "block", "block"]);
    clearInterval(ticks);
    expect(vectors).toHaveLength(3);
    expect(longest).toBeLessThan(150);
  });
});
