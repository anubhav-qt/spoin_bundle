import { describe, expect, test } from "vitest";
import { htmlText } from "../src/agents/html-text.ts";
import { isBotCheck, markdownTitle, tidy } from "../src/agents/pages.ts";

/*
 * A fetched page's text (task 0045) keeps its code as code: the first Rust run's pages lost every
 * code block's indentation, since each line was trimmed with the prose around it.
 */

describe("a fetched page's text", () => {
  test("an HTML code block keeps its indentation, fenced, while the prose around it is tidied", () => {
    const html = `<html><head><title>Ownership</title></head><body>
      <p>A   move   transfers ownership.</p>
      <pre><code class="language-rust">fn main() {
    let s = String::from(&quot;hi&quot;);
    takes(s);
}</code></pre>
      <p>Then s is gone.</p></body></html>`;
    const page = htmlText(html);
    expect(page.title).toBe("Ownership");
    expect(page.text).toBe(
      [
        "A move transfers ownership.",
        "",
        "```",
        "fn main() {",
        '    let s = String::from("hi");',
        "    takes(s);",
        "}",
        "```",
        "",
        "Then s is gone.",
      ].join("\n"),
    );
  });

  test("plain text keeps its indentation, and a markdown file is titled by its first heading", () => {
    const markdown = "## What Is Ownership?   \n\n\n\n```rust\nfn main() {\n    let x = 5;\n}\n```\n";
    expect(tidy(markdown)).toBe("## What Is Ownership?\n\n```rust\nfn main() {\n    let x = 5;\n}\n```");
    expect(markdownTitle(tidy(markdown))).toBe("What Is Ownership?");
    expect(markdownTitle("No heading here.")).toBe("");
  });

  test("a site's bot check is told from the page, and an article about bot checks is not", () => {
    // The two the stage 2 rerun stored as pages (2026-10-14).
    const sacredTexts =
      "sacred-texts.com\nPerforming security verification\n\nThis website uses a security service to protect against malicious bots. This page is displayed while the website verifies you are not a bot.\n\nRay ID: a4a54332a81dca42";
    const medium =
      "Sorry, you have been blocked\nYou are unable to access medium.com\nWhy have I been blocked?";
    expect(isBotCheck("Just a moment...", sacredTexts)).toBe(true);
    expect(isBotCheck("Attention Required! | Cloudflare", medium)).toBe(true);
    expect(isBotCheck("", medium)).toBe(true);
    const article = `How bot checks work. ${"A challenge page asks the browser to run a script. ".repeat(60)} Performing security verification is what the page says.`;
    expect(isBotCheck("Bot checks, explained", article)).toBe(false);
    expect(isBotCheck("Ownership", "A move transfers ownership.")).toBe(false);
  });
});
