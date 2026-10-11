import { type Embedder, HashEmbedder } from "@spoin/frog/embeddings";
import { normalizeTopicText } from "@spoin/frog/normalize";
import { describe, expect, test } from "vitest";
import {
  angularDistance,
  assignAccentHue,
  defaultHuePositional,
  hashTopicHue,
  vocabulary,
} from "../src/topics/accent.ts";

/** Named texts get the given vectors; everything else is orthogonal to all of them. */
function fakeEmbedder(table: Record<string, number[]>): Embedder & { calls: string[][] } {
  const calls: string[][] = [];
  const embed = async (texts: string[]) => {
    calls.push(texts);
    return texts.map((t) => table[t] ?? [0, 0, 1]);
  };
  return { modelName: "fake", embedPassage: embed, embedQuery: embed, calls };
}

const opts = (over: Partial<Parameters<typeof assignAccentHue>[1]> = {}) => ({
  topicId: "11111111-1111-1111-1111-111111111111",
  topicName: "Marine biology",
  topicEmbedding: [1, 0, 0],
  usedHues: new Set<number>(),
  subscriptionIndex: 0,
  ...over,
});

const [best] = vocabulary as [(typeof vocabulary)[number]];
const second = vocabulary.find((e) => angularDistance(e.hue, best.hue) >= 25) as (typeof vocabulary)[number];

describe("accent hue (ADR-0075)", () => {
  test("angles wrap around the wheel", () => {
    expect(angularDistance(10, 20)).toBe(10);
    expect(angularDistance(350, 10)).toBe(20);
    expect(angularDistance(0, 359)).toBe(1);
    expect(angularDistance(0, 180)).toBe(180);
  });

  test("the hash matches the web client's", () => {
    expect(hashTopicHue("a")).toBe(97);
    expect(hashTopicHue("abc")).toBe(96354 % 360);
    expect(hashTopicHue("11111111-1111-1111-1111-111111111111")).toBeLessThan(360);
  });

  test("the positional default is the curated ten, then the hash", () => {
    expect(defaultHuePositional("x", 0)).toBe(12);
    expect(defaultHuePositional("x", 9)).toBe(336);
    expect(defaultHuePositional("abc", 10)).toBe(hashTopicHue("abc"));
    expect(defaultHuePositional("abc", null)).toBe(hashTopicHue("abc"));
  });

  test("the shipped vocabulary is well formed", () => {
    expect(vocabulary.length).toBeGreaterThan(100);
    for (const e of vocabulary) {
      expect(e.name).not.toBe("");
      expect(e.hue).toBeGreaterThanOrEqual(0);
      expect(e.hue).toBeLessThan(360);
    }
  });

  test("the hash stand-in yields no hue: the client default applies", async () => {
    expect(await assignAccentHue(new HashEmbedder(), opts())).toBeNull();
  });

  test("picks the nearest vocabulary hue", async () => {
    const e = fakeEmbedder({ [normalizeTopicText(best.name)]: [1, 0, 0] });
    expect(await assignAccentHue(e, opts())).toBe(best.hue);
  });

  test("skips a hue too close to one the user already has", async () => {
    const e = fakeEmbedder({
      [normalizeTopicText(best.name)]: [1, 0, 0],
      [normalizeTopicText(second.name)]: [0.9, 0.1, 0],
    });
    expect(await assignAccentHue(e, opts({ usedHues: new Set([best.hue]) }))).toBe(second.hue);
  });

  test("embeds the name when the topic has no embedding of its own", async () => {
    const name = normalizeTopicText("Marine biology");
    const e = fakeEmbedder({ [normalizeTopicText(best.name)]: [1, 0, 0], [name]: [1, 0, 0] });
    expect(await assignAccentHue(e, opts({ topicEmbedding: null }))).toBe(best.hue);
    expect(e.calls.at(-1)).toEqual([name]);
  });

  test("a crowded wheel falls back to the positional spread", async () => {
    const e = fakeEmbedder({});
    const everywhere = new Set(Array.from({ length: 36 }, (_, i) => i * 10));
    expect(await assignAccentHue(e, opts({ usedHues: everywhere, subscriptionIndex: 2 }))).toBe(84);
  });
});
