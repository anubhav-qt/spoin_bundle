/*
 * A web page's readable text from its HTML (task 0045), without a DOM: what isn't text is dropped,
 * blocks become lines and headings keep a `##`, so passages cut at paragraph breaks and a chat
 * sees where a section starts. Good enough for documentation and articles; a page that draws its
 * text with scripts is read in the browser instead.
 */

/** Elements whose content is never the page's text. */
const DROPPED = /<(script|style|noscript|svg|template|iframe|canvas|nav|footer|form)\b[\s\S]*?<\/\1\s*>/gi;
const COMMENTS = /<!--[\s\S]*?-->/g;
const HEADINGS = /<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1\s*>/gi;
const BLOCKS =
  /<\/?(p|div|section|article|main|header|aside|ul|ol|li|dl|dt|dd|table|tr|blockquote|pre|figure|figcaption|br|hr)\b[^>]*>/gi;
const CELLS = /<\/?(td|th)\b[^>]*>/gi;
const TAGS = /<[^>]+>/g;
const TITLE = /<title\b[^>]*>([\s\S]*?)<\/title\s*>/i;

const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  ndash: "-",
  mdash: "-",
  hellip: "...",
  rsquo: "'",
  lsquo: "'",
  rdquo: '"',
  ldquo: '"',
  copy: "(c)",
};

export function htmlText(html: string): { title: string; text: string } {
  const titleMatch = TITLE.exec(html);
  const title = decode(stripTags(titleMatch?.[1] ?? "")).trim();
  const bodyStart = html.search(/<body\b/i);
  let text = bodyStart >= 0 ? html.slice(bodyStart) : html;
  text = text.replace(COMMENTS, "").replace(DROPPED, "\n");
  text = text.replace(
    HEADINGS,
    (_match, _level: string, inner: string) => `\n\n## ${stripTags(inner).trim()}\n\n`,
  );
  text = text.replace(BLOCKS, "\n").replace(CELLS, " | ");
  text = decode(stripTags(text));
  const lines = text.split("\n").map((line) => line.replace(/[ \t ]+/g, " ").trim());
  return {
    title,
    text: lines
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim(),
  };
}

function stripTags(html: string): string {
  return html.replace(TAGS, "");
}

function decode(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, name: string) => {
    if (name.startsWith("#x") || name.startsWith("#X"))
      return codePoint(Number.parseInt(name.slice(2), 16), whole);
    if (name.startsWith("#")) return codePoint(Number.parseInt(name.slice(1), 10), whole);
    return ENTITIES[name.toLowerCase()] ?? whole;
  });
}

function codePoint(value: number, whole: string): string {
  if (!Number.isFinite(value) || value <= 0 || value > 0x10ffff) return whole;
  return String.fromCodePoint(value);
}
