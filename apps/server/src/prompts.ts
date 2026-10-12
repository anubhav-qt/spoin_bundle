import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import nunjucks from "nunjucks";

/*
 * Every prompt is a Nunjucks template in the repository's `prompts/` (task 0045, Trotter's
 * ADR 0020): code picks a template and passes it data, and `docs/architecture/writing-prompts.md`
 * says how they're written. Runs from src/ in development and dist/ in the build, both two
 * folders below the repository root; the image sets PROMPTS_DIR, as it does the migrations.
 */
const here = dirname(fileURLToPath(import.meta.url));
export const PROMPTS_DIRECTORY = process.env.PROMPTS_DIR ?? resolve(here, "../../../prompts");

export interface Prompts {
  /** Renders a template, named by its path inside prompts/, with its data. */
  render(template: string, data: object): string;
}

/** `directory`: several are searched in order, so tests can put a template of their own first. */
export function loadPrompts(directory: string | string[] = PROMPTS_DIRECTORY): Prompts {
  const environment = new nunjucks.Environment(new nunjucks.FileSystemLoader(directory), {
    // Prompts aren't HTML.
    autoescape: false,
    // A missing value is a mistake in the data, not a blank in the prompt.
    throwOnUndefined: true,
    // A line holding only a tag leaves nothing behind.
    trimBlocks: true,
    lstripBlocks: true,
  });
  return { render: (template, data) => tidy(environment.render(template, data)) };
}

/** Unix line endings, no spaces at line ends, at most one blank line in a row, and none at the ends. */
function tidy(text: string): string {
  return text
    .replaceAll("\r\n", "\n")
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
