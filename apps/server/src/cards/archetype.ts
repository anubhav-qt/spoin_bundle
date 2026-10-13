/*
 * Which content shapes a card's body holds (ADR-0017), from the body alone: whether it has a
 * fenced code block is true or false from the text, so a model is never asked. Ported from the
 * Python `content/archetype.py`.
 */

const FENCE = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;

/**
 * A fence tagged as a diagram, or one mostly box-drawing and arrows rather than a language.
 * `mermaid` counts as a diagram whatever its body holds (ADR-0067).
 */
const DIAGRAM_LANG_TAGS = new Set(["diagram", "text", "ascii", "mermaid", ""]);
const DIAGRAM_CHARS = /[─│┌└┐┘├┤┬┴┼→▶►]|-->|==>|──>/;
const COMPARISON_MARKERS = ["❌", "✅"];

export function classifyArchetype(body: string): string[] {
  let hasCode = false;
  let hasDiagram = false;
  for (const match of body.matchAll(FENCE)) {
    const lang = (match[1] ?? "").toLowerCase();
    const content = match[2] ?? "";
    if (!DIAGRAM_LANG_TAGS.has(lang)) hasCode = true;
    else if (lang === "diagram" || lang === "mermaid" || DIAGRAM_CHARS.test(content)) hasDiagram = true;
    // A fence with no language and no diagram characters is still code: a shell transcript, say.
    else if (content.trim()) hasCode = true;
  }
  // Arrows outside a fence still make a diagram of an otherwise prose body.
  if (!hasDiagram && DIAGRAM_CHARS.test(body)) hasDiagram = true;

  const tags: string[] = [];
  if (hasCode) tags.push("code");
  if (hasDiagram) tags.push("diagram");
  if (COMPARISON_MARKERS.every((marker) => body.includes(marker))) tags.push("comparison");
  return tags;
}
