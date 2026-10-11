/**
 * The normalization applied before embedding a topic string, and to every corpus
 * tag and category (ADR-0093).
 *
 * **This must stay identical between calibration and production.** It is what keeps
 * corpus tags and canonical topic names one vocabulary: `chunk.topic_tags`,
 * `document.category` and `document.sub_category` are all produced by it, so a
 * change here re-tags the whole corpus or silently stops matching it.
 *
 * Python's `str.isalnum()` is letters (`\p{L}`) or numbers (`\p{N}`); everything
 * else that is not whitespace becomes a space, then whitespace runs collapse.
 */
export function normalizeTopicText(raw: string): string {
  const lowered = raw.trim().toLowerCase();
  const kept = lowered.replace(/[^\p{L}\p{N}\s]/gu, " ");
  return kept.split(/\s+/u).filter(Boolean).join(" ");
}
