import { cosine, type Embedder, HashEmbedder } from "@spoin/frog/embeddings";
import { normalizeTopicText } from "@spoin/frog/normalize";
import vocabularyFile from "./colors.json" with { type: "json" };

/*
 * ADR-0075: a topic's default accent hue, chosen by embedding similarity. Rank a
 * curated colour vocabulary against the topic, then take the best hue at least
 * ACCENT_HUE_MIN_DISTANCE degrees from every hue the user's other topics use.
 * Which colour is taste, so embeddings pick it; that it is distinct is a constraint,
 * so angle arithmetic decides it.
 *
 * Degrades totally: with the hash stand-in there is no meaning to rank by, so the
 * column stays null and the client renders its positional default.
 */

/** ~14 distinct slots before the wheel is crowded and the positional spread takes over. */
const ACCENT_HUE_MIN_DISTANCE = 25;

/** ADR-0051's opt-out, "no per-topic tint". Never a real hue. Mirrors apps/web/lib/topicColor.ts. */
export const NO_TOPIC_COLOR = -1;

/** ADR-0034's curated ten. Must match `CURATED_DEFAULT_HUES` in apps/web/lib/topicColor.ts. */
const CURATED_DEFAULT_HUES = [12, 48, 84, 120, 156, 192, 228, 264, 300, 336];

type ColorEntry = { name: string; hue: number };

export const vocabulary: ColorEntry[] = (vocabularyFile.colors as { name: unknown; hue: unknown }[]).flatMap(
  (row) => {
    const name = String(row.name ?? "").trim();
    const hue = Number(row.hue);
    return name && Number.isInteger(hue) ? [{ name, hue: ((hue % 360) + 360) % 360 }] : [];
  },
);

/** `hashTopicId` in the web client, byte for byte: the server imputes the hue a null row renders as. */
export function hashTopicHue(topicId: string): number {
  let hash = 0;
  for (let i = 0; i < topicId.length; i++) hash = (hash * 31 + topicId.charCodeAt(i)) | 0;
  return Math.abs(hash) % 360;
}

/** `defaultTopicHue` in the web client: the curated ten by position, then the hash. */
export const angularDistance = (a: number, b: number) => {
  const delta = Math.abs(a - b) % 360;
  return Math.min(delta, 360 - delta);
};

export function defaultHuePositional(topicId: string, subscriptionIndex: number | null): number {
  if (subscriptionIndex !== null && subscriptionIndex < CURATED_DEFAULT_HUES.length)
    return CURATED_DEFAULT_HUES[subscriptionIndex] as number;
  return hashTopicHue(topicId);
}

/** The vocabulary's vectors, computed once per embedder; concurrent callers share the one promise. */
const indexes = new WeakMap<Embedder, Promise<number[][]>>();

/**
 * The hue to store on a fresh subscription, or null without a real embedder.
 * `topicEmbedding` is reused from the topic row when it has one; `usedHues` holds the
 * user's other topics' hues, legacy nulls imputed, opt-outs left out.
 */
export async function assignAccentHue(
  embedder: Embedder,
  opts: {
    topicId: string;
    topicName: string;
    topicEmbedding: number[] | null;
    usedHues: Set<number>;
    subscriptionIndex: number | null;
  },
): Promise<number | null> {
  if (embedder instanceof HashEmbedder) return null;
  if (vocabulary.length === 0) return defaultHuePositional(opts.topicId, opts.subscriptionIndex);

  let index = indexes.get(embedder);
  if (!index) {
    index = embedder.embedPassage(vocabulary.map((e) => normalizeTopicText(e.name)));
    indexes.set(embedder, index);
  }
  const vectors = await index;
  const query =
    opts.topicEmbedding ??
    ((await embedder.embedPassage([normalizeTopicText(opts.topicName)]))[0] as number[]);

  const ranked = vocabulary
    .map((entry, i) => ({ entry, score: cosine(vectors[i] as number[], query) }))
    .sort((a, b) => b.score - a.score);
  for (const { entry } of ranked) {
    if ([...opts.usedHues].every((used) => angularDistance(entry.hue, used) >= ACCENT_HUE_MIN_DISTANCE))
      return entry.hue;
  }
  // The wheel is too crowded for a distinct vocabulary hue; persisted, so later picks dedup against it.
  return defaultHuePositional(opts.topicId, opts.subscriptionIndex);
}
