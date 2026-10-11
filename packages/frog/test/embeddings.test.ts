import { describe, expect, it } from "vitest";
import { cosine, HashEmbedder } from "../src/embeddings.ts";

// HashEmbedder's contract, which several thresholds quietly depend on.
describe("HashEmbedder", () => {
  it("takes a collection and returns one vector per text, in order (ADR-0005)", async () => {
    const vectors = await new HashEmbedder(384).embedPassage(["postgres", "kubernetes", "raft consensus"]);
    expect(vectors).toHaveLength(3);
    for (const v of vectors) expect(v).toHaveLength(384);
  });

  it("returns unit vectors, the one convention both databases assume", async () => {
    const [v] = await new HashEmbedder(384).embedPassage(["distributed systems"]);
    expect(Math.hypot(...(v as number[]))).toBeCloseTo(1, 9);
  });

  it("does not divide by zero on text that is all whitespace", async () => {
    // Reachable from real input: a chunk that is entirely punctuation normalizes to nothing.
    expect(await new HashEmbedder(8).embedPassage(["   "])).toEqual([new Array(8).fill(0)]);
  });

  it("is deterministic, the whole point of the stand-in", async () => {
    const a = await new HashEmbedder(64).embedPassage(["raft consensus"]);
    const b = await new HashEmbedder(64).embedPassage(["raft consensus"]);
    expect(a).toEqual(b);
  });

  it("embeds a query exactly as a passage", async () => {
    const e = new HashEmbedder(32);
    expect(await e.embedQuery(["btree", "wal"])).toEqual(await e.embedPassage(["btree", "wal"]));
  });

  it("scores shared tokens above disjoint ones", async () => {
    const [a, b, c] = await new HashEmbedder().embedPassage([
      "raft consensus",
      "raft log",
      "sourdough bread",
    ]);
    expect(cosine(a as number[], b as number[])).toBeGreaterThan(cosine(a as number[], c as number[]));
  });
});
