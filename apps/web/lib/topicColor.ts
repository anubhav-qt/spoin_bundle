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
 *
 * ADR-0075: the server now usually sends a concrete `accent_hue` for a fresh
 * subscription (an embedding-derived, distance-filtered hue picked from a colour
 * vocabulary, materialized at subscribe time) where it used to send `null`.
 * Nothing here changes — a concrete hue was always handled. `defaultTopicHue`
 * below stays as the renderer for any `null` that still arrives: pre-ADR-0075
 * rows, and rows created on a backend with no real embedder (dev/tests).
 *
 * ADR-0051: a topic can also opt OUT of coloring entirely and just render
 * the palette's plain `--accent`, which is a third state distinct from "use
 * the default hue" (`accent_hue: null`) and "use this hue"
 * (`accent_hue: 0-359`). `accent_hue` is stored as a nullable int server-side
 * (no migration for a third column), so opt-out is the sentinel `-1` rather
 * than a new field — `topicHue()` maps it to `null`, meaning "set no
 * `--topic-hue` custom property," and every call site that reads a hue must
 * go through `topicHue()`/`explicitTopicHue()` rather than reading
 * `accent_hue` off the wire directly, or the sentinel renders as a real
 * (red) hue instead of no color.
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

/** ADR-0051: the sentinel stored in `accent_hue` meaning "don't tint this
 *  topic — render the palette's plain `--accent`." Not a real hue; must
 *  never reach `oklch()`. */
export const NO_TOPIC_COLOR = -1;

/** The hue to render for this topic, or `null` if it's opted out
 *  (`accent_hue === NO_TOPIC_COLOR`) — `null` means "set no `--topic-hue`
 *  custom property," letting `--topic-accent` fall back to the plain
 *  palette `--accent` (globals.css) exactly as it already does for
 *  mixed/topicless content. */
export function topicHue(
  topicId: string,
  accentHue: number | null | undefined,
  topicIndex?: number,
): number | null {
  if (accentHue === NO_TOPIC_COLOR) return null;
  return accentHue ?? defaultTopicHue(topicId, topicIndex);
}

/** Like `topicHue`, but for call sites (collection-filter chips in Saved/
 *  Liked/Notes) that only ever want to tint on an *explicitly chosen* hue,
 *  never the computed default — so a topic nobody has colored renders as a
 *  plain chip, and one opted out (or never colored) is indistinguishable
 *  from the other, which is the point. */
export function explicitTopicHue(accentHue: number | null | undefined): number | null {
  if (accentHue === null || accentHue === undefined || accentHue === NO_TOPIC_COLOR) return null;
  return accentHue;
}
