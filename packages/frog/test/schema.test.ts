import { getTableConfig } from "drizzle-orm/pg-core";
import { describe, expect, it } from "vitest";
import { EMBEDDING_DIM } from "../src/embeddings.ts";
import { universeUrl } from "../src/universe/db.ts";
import { chunk, document, documentKind, documentScope } from "../src/universe/schema.ts";

/*
 * The corpus schema's decisions fail SILENTLY if they drift: a nullable `source` still
 * works, a non-unique `source_path` still ingests, and both surface only later, as an
 * uncitable card or a corpus that quietly doubled (ADR-0088).
 */

const doc = getTableConfig(document);
const chk = getTableConfig(chunk);
const column = (table: typeof doc, name: string) => table.columns.find((c) => c.name === name);

describe("the corpus schema", () => {
  it("stores 1024-dimensional vectors, Qwen3-Embedding-0.6B's width (ADR-0092)", () => {
    // Mismatched dimensions compare as noise rather than failing, so the number is pinned.
    expect(EMBEDDING_DIM).toBe(1024);
    expect(column(chk, "embedding")?.getSQLType()).toBe("vector(1024)");
  });

  it("keeps provenance NOT NULL: a document that cannot say where it came from backs no card (ADR-0089)", () => {
    for (const name of ["source", "title", "kind", "source_path", "content_hash", "ingested_at"]) {
      expect(column(doc, name)?.notNull, name).toBe(true);
    }
    // When the material is from, and when we read it, are two facts; canon has only the second.
    expect(column(doc, "source_date")?.notNull).toBe(false);
  });

  it("keeps source_path unique, which idempotent re-ingestion rests on", () => {
    expect(column(doc, "source_path")?.isUnique).toBe(true);
  });

  it("cascades chunks from their document", () => {
    expect(chk.foreignKeys[0]?.onDelete).toBe("cascade");
  });

  it("has exactly the two document kinds: a third is a migration and a decision", () => {
    expect(documentKind.enumValues).toEqual(["spoin_canon", "topic_source"]);
  });

  it("has the three scopes the app's topic_scope has (ADR-0106)", () => {
    expect(documentScope.enumValues).toEqual(["survey", "topic", "one_shot"]);
  });

  it("indexes topic_tags for overlap search, and category for the intake step", () => {
    const gin = chk.indexes.find((i) => i.config.method === "gin");
    expect(gin?.config.columns.map((c) => (c as { name: string }).name)).toEqual(["topic_tags"]);
    const byCategory = doc.indexes.find((i) => i.config.name === "ix_document_category_sub_category");
    expect(byCategory?.config.columns.map((c) => (c as { name: string }).name)).toEqual([
      "category",
      "sub_category",
    ]);
  });

  it("requires the hierarchy of subject matter and exempts canon, in a CHECK (ADR-0091)", () => {
    expect(doc.checks.map((c) => c.name)).toContain("ck_document_topic_source_has_category_and_scope");
  });
});

describe("the corpus database's URL", () => {
  it("comes from UNIVERSE_DATABASE_URL", () => {
    expect(universeUrl({ UNIVERSE_DATABASE_URL: "postgres://x/the_spoin_universe" })).toBe(
      "postgres://x/the_spoin_universe",
    );
  });

  it("never falls back to the app's DATABASE_URL (ADR-0088)", () => {
    // The whole decision as a test: DATABASE_URL is set, as in every process this runs in.
    expect(() => universeUrl({ DATABASE_URL: "postgres://x/spoin" })).toThrow(
      /UNIVERSE_DATABASE_URL is not set/,
    );
  });
});
