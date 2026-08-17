/**
 * ADR-0034: a topic's accent hue, deterministic when the user hasn't picked
 * one. Kept as a single pure function (not duplicated in Card/Feed) so the
 * default is provably the same wherever it's read.
 *
 * `--topic-accent`'s composition (globals.css) derives from
 * `oklch(from var(--accent) l c <hue>)` — it keeps the active palette's own
 * lightness/chroma and only rotates hue, so background contrast is already
 * structurally guaranteed per palette (that's what `--accent` was tuned for
 * in the first place). What hue *choice* actually controls is whether two
 * different topics read as visibly different colors rather than converging
 * on similar-looking hues — that's what the curated set below is for.
 */

/** 10 hues spread evenly around the wheel (36° apart) so the first 10
 *  topics a user follows are maximally distinct from each other, not an
 *  accident of hashing. Order matters: assigned by subscription order
 *  (index into the topics list), not derived from the topic id. */
const CURATED_DEFAULT_HUES = [12, 48, 84, 120, 156, 192, 228, 264, 300, 336];

function hashTopicId(topicId: string): number {
  let hash = 0;
  for (let i = 0; i < topicId.length; i++) {
    hash = (hash * 31 + topicId.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % 360;
}

/** `topicIndex` is this topic's position in the user's followed-topics list
 *  (subscription order) — pass it whenever the caller has that list (Feed,
 *  the topic filter rail). Omit only where no ordered list is available
 *  (e.g. a swatch preview keyed on topicId alone); beyond the 10 curated
 *  slots this also falls back to the same hash-based spread as before. */
export function defaultTopicHue(topicId: string, topicIndex?: number): number {
  if (topicIndex !== undefined && topicIndex < CURATED_DEFAULT_HUES.length) {
    return CURATED_DEFAULT_HUES[topicIndex];
  }
  return hashTopicId(topicId);
}

export function topicHue(
  topicId: string,
  accentHue: number | null | undefined,
  topicIndex?: number,
): number {
  return accentHue ?? defaultTopicHue(topicId, topicIndex);
}
