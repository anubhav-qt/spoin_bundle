/**
 * Text no one in spoin wrote (a reader's words, a web page) reaches a model inside a tag that marks
 * it as data (writing-prompts.md). The tag is taken out of the text first, so the text can't close
 * it and carry on as instructions.
 */
export function withoutTag(text: string, tag: string): string {
  return text.replace(new RegExp(`<\\s*/?\\s*${tag}\\b[^>]*>`, "gi"), "");
}

/** The requester's own words: a topic name and description (`handovers/job.njk`, `merge.njk`). */
export function withoutRequestTag(text: string): string {
  return withoutTag(text, "request");
}
