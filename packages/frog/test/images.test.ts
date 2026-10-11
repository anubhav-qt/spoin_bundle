import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { count, eq } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { HashEmbedder } from "../src/embeddings.ts";
import {
  entryHash,
  MIN_DESCRIPTION_CHARS,
  type ParsedManifest,
  parseImages,
  parseManifest,
} from "../src/images/contract.ts";
import { ingestImages, ingestManifest } from "../src/images/runner.ts";
import { image } from "../src/universe/schema.ts";
import { useUniverse } from "./universe.ts";

/* The image catalog (ADR-0095, task 0040): the manifest contract, pure, and its ingestion. */

const db = useUniverse();
const embedder = new HashEmbedder();

const LONG_A =
  "A tide pool at low water on a granite shore, anemones open and a hermit crab crossing a coralline crust, showing how organisms sort by exposure time.";
const LONG_B =
  "A wooden loom mid-weave in a workshop, the warp threads under tension and a shuttle resting on the cloth, illustrating how a plain weave interlaces.";

const entry = (title: string, url: string, description: string, tags = "[shores]") => `  - title: "${title}"
    description: "${description}"
    source_url: "${url}"
    source_page: "${url}/page"
    licence: cc-by
    attribution: "Jane Photographer, CC BY 4.0"
    topic_tags: ${tags}`;

const manifest = (...entries: string[]) => `---
kind: image_manifest
category: Natural History
sub_category: Shores
images:
${entries.join("\n")}
---
`;

const POOL = entry("Tide pool", "https://example.org/pool.jpg", LONG_A, "[Tide Pools, shores]");
const LOOM = entry("Loom", "https://example.org/loom.jpg", LONG_B);

const parse = (text: string) => parseManifest("nature/images.md", new TextEncoder().encode(text));
const problems = (text: string) => parse(text).errors.problems;

describe("the image manifest contract", () => {
  it("parses a valid manifest", () => {
    const { manifest: m, errors } = parse(manifest(POOL));
    expect(errors.problems).toEqual([]);
    expect(m).toMatchObject({ category: "natural history", subCategory: "shores" });
    expect(m?.images[0]).toMatchObject({
      title: "Tide pool",
      licence: "cc-by",
      attribution: "Jane Photographer, CC BY 4.0",
      topicTags: ["tide pools", "shores"],
    });
    const { contentHash, ...rest } = (m as ParsedManifest).images[0] as ParsedManifest["images"][number];
    expect(contentHash).toBe(entryHash(rest));
  });

  it("fails a licence outside the allowlist", () => {
    expect(
      problems(manifest(POOL.replace("cc-by", "cc-by-nc-4.0"))).some((p) =>
        p.includes("not in the allowlist"),
      ),
    ).toBe(true);
  });

  it("fails a description under the minimum, which is a caption rather than a retrieval surface", () => {
    const short = problems(manifest(POOL.replace(LONG_A, "A tide pool.")));
    expect(short.some((p) => p.includes(`under the ${MIN_DESCRIPTION_CHARS} minimum`))).toBe(true);
  });

  it("fails a source_url repeated within a manifest", () => {
    const twice = manifest(POOL, LOOM.replace("loom.jpg", "pool.jpg"));
    expect(problems(twice).some((p) => p.includes("duplicate `source_url` within this manifest"))).toBe(true);
  });

  it("fails a source_url delivered in two manifests, naming the first", () => {
    const root = mkdtempSync(join(tmpdir(), "frog-images-"));
    for (const dir of ["a", "b"]) {
      mkdirSync(join(root, dir));
      writeFileSync(join(root, dir, "images.md"), manifest(POOL));
    }
    const { parsed, failures } = parseImages(root);
    expect(parsed).toHaveLength(2);
    expect(failures).toHaveLength(1);
    expect(failures[0]?.manifestPath).toBe("b/images.md");
    expect(failures[0]?.problems[0]).toContain("was already delivered in a/images.md");
  });

  it("treats a missing images tree as an empty delivery", () => {
    expect(parseImages(join(tmpdir(), "frog-no-such-images-dir"))).toEqual({ parsed: [], failures: [] });
  });

  it("hashes the entry, and any field changes the hash", () => {
    const base = {
      sourceUrl: "https://example.org/x.jpg",
      title: "Title",
      description: LONG_A,
      sourcePage: "https://example.org/x",
      licence: "cc0" as const,
      attribution: "Someone",
      topicTags: ["shores"],
    };
    expect(entryHash(base)).toBe(entryHash({ ...base }));
    expect(entryHash(base)).toHaveLength(64);
    expect(entryHash({ ...base, title: "Other" })).not.toBe(entryHash(base));
    expect(entryHash({ ...base, topicTags: ["other"] })).not.toBe(entryHash(base));
  });

  it("fails text after the closing front matter", () => {
    const found = problems(`${manifest(POOL)}\nExtra trailing body text.\n`);
    expect(found.some((p) => p.includes("a manifest is front matter only"))).toBe(true);
  });

  it("fails a document that is not a manifest", () => {
    expect(problems(manifest(POOL).replace("kind: image_manifest", "kind: topic_source"))[0]).toContain(
      "`kind` must be exactly `image_manifest`",
    );
  });
});

const ingest = (text: string, force = false) =>
  ingestManifest(db, parse(text).manifest as ParsedManifest, embedder, { force });

async function rows(): Promise<number> {
  const [r] = await db.select({ n: count() }).from(image);
  return r?.n ?? 0;
}

describe("ingesting the image catalog", () => {
  it("writes once, and a re-run changes nothing", async () => {
    expect(await ingest(manifest(POOL, LOOM))).toEqual({ created: 2, updated: 0, unchanged: 0, removed: 0 });
    expect(await ingest(manifest(POOL, LOOM))).toEqual({ created: 0, updated: 0, unchanged: 2, removed: 0 });
    expect(await rows()).toBe(2);
  });

  it("removes an entry its manifest withdrew", async () => {
    await ingest(manifest(POOL, LOOM));
    expect(await ingest(manifest(POOL))).toEqual({ created: 0, updated: 0, unchanged: 1, removed: 1 });
    const left = await db.select({ title: image.title }).from(image);
    expect(left).toEqual([{ title: "Tide pool" }]);
  });

  it("rewrites a changed entry, and force rewrites all, keeping a hosted url", async () => {
    await ingest(manifest(POOL, LOOM));
    await db
      .update(image)
      .set({ hostedUrl: "https://cdn.example/pool.jpg" })
      .where(eq(image.title, "Tide pool"));
    const reworded = manifest(POOL.replace("Tide pool", "Tide pool at dusk"), LOOM);
    expect(await ingest(reworded)).toEqual({ created: 0, updated: 1, unchanged: 1, removed: 0 });
    expect(await ingest(reworded, true)).toEqual({ created: 0, updated: 2, unchanged: 0, removed: 0 });
    const [pool] = await db.select().from(image).where(eq(image.sourceUrl, "https://example.org/pool.jpg"));
    expect(pool).toMatchObject({ title: "Tide pool at dusk", hostedUrl: "https://cdn.example/pool.jpg" });
  });

  it("does not write a manifest that lost a source_url to another", async () => {
    const root = mkdtempSync(join(tmpdir(), "frog-images-"));
    mkdirSync(join(root, "a"));
    mkdirSync(join(root, "b"));
    writeFileSync(join(root, "a", "images.md"), manifest(POOL));
    writeFileSync(join(root, "b", "images.md"), manifest(POOL, LOOM));
    const report = await ingestImages(db, root, embedder);
    expect(report).toMatchObject({ failedManifests: 1, created: 1 });
    expect(await db.select({ path: image.manifestPath }).from(image)).toEqual([{ path: "a/images.md" }]);
  });
});
