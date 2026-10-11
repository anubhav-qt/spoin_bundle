/**
 * The corpus store, `the_spoin_universe` (ADR-0088): documents and their chunks, the
 * image catalog (ADR-0095), and authored curricula (authored-curriculum.md §7).
 *
 * A SEPARATE database from the app's, with its own migrations folder: a universe
 * migration structurally cannot land on the app database. Nothing here holds a
 * foreign key across that boundary; references cross it by value.
 */
import { sql } from "drizzle-orm";
import {
  boolean,
  check,
  index,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
  vector,
} from "drizzle-orm/pg-core";
import { EMBEDDING_DIM } from "../embeddings.ts";

const id = () => uuid("id").primaryKey().defaultRandom();
const createdAt = () => timestamp("created_at", { withTimezone: true }).notNull().defaultNow();

/**
 * `spoin_canon` is how the product itself works and is pinned, never retrieved
 * (ADR-0096); `topic_source` is curated material, relevant by subject. An enum so a
 * front-matter typo cannot create a silent third kind nothing retrieves.
 */
export const documentKind = pgEnum("document_kind", ["spoin_canon", "topic_source"]);

/** Breadth (a field toured) or depth (a subject taught). Mirrors `topic.is_survey` by value (ADR-0007). */
export const documentScope = pgEnum("document_scope", ["survey", "topic"]);

/**
 * A closed vocabulary because a typo'd licence is a legal problem, not a quality one.
 * NC is absent because Spoin is commercial; ND because serving an image at card width
 * is a derivative work. ND cannot be re-admitted by deciding to be careful (ADR-0095).
 */
export const imageLicence = pgEnum("image_licence", [
  "cc0",
  "public-domain",
  "cc-by",
  "cc-by-sa",
  "unsplash",
  "pexels",
  "pixabay",
]);

/** One authored source file, and enough provenance to cite it (ADR-0089). */
export const document = pgTable(
  "document",
  {
    id: id(),
    createdAt: createdAt(),
    /** A URL, or an origin description. NOT NULL: a document nothing can cite is not one this corpus wants. */
    source: text("source").notNull(),
    title: varchar("title", { length: 500 }).notNull(),
    kind: documentKind("kind").notNull(),
    /** ADR-0091. Stored through `normalizeTopicText` so "Computer Science" and "computer-science" are one category. */
    category: varchar("category", { length: 120 }),
    /** Optional even for subject matter: a level that restates its parent is noise. */
    subCategory: varchar("sub_category", { length: 120 }),
    scope: documentScope("scope"),
    /** The document's identity within the delivered corpus; re-ingesting a revision updates one row. */
    sourcePath: varchar("source_path", { length: 1000 }).notNull().unique("uq_document_source_path"),
    /** sha256 of the raw file: unchanged hash skips, changed hash replaces the chunks in one transaction. */
    contentHash: varchar("content_hash", { length: 64 }).notNull(),
    /** When the SOURCE MATERIAL is from, distinct from when we read it. */
    sourceDate: timestamp("source_date", { withTimezone: true }),
    ingestedAt: timestamp("ingested_at", { withTimezone: true }).notNull(),
  },
  (t) => [
    /** Canon sits outside the subject hierarchy; everything else must place itself in it. */
    check(
      "ck_document_topic_source_has_category_and_scope",
      sql`${t.kind} <> 'topic_source' OR (${t.category} IS NOT NULL AND ${t.scope} IS NOT NULL)`,
    ),
    index("ix_document_category_sub_category").on(t.category, t.subCategory),
  ],
);

/** A retrievable span of one document. */
export const chunk = pgTable(
  "chunk",
  {
    id: id(),
    createdAt: createdAt(),
    /** CASCADE: re-ingesting a changed document deletes and rebuilds its chunks wholesale. */
    documentId: uuid("document_id")
      .notNull()
      .references(() => document.id, { onDelete: "cascade" }),
    /** Position within the document: citable as "part 3 of", and widenable to neighbours. */
    ordinal: integer("ordinal").notNull(),
    text: text("text").notNull(),
    /**
     * The `##` heading this chunk was cut at. What makes a chunk addressable by a
     * curriculum's `<path>#<heading>` grounding reference, as a join rather than a
     * LIKE against the prefix of `text`.
     */
    heading: text("heading"),
    embedding: vector("embedding", { dimensions: EMBEDDING_DIM }).notNull(),
    /** NOT NULL: every chunk has a vector, so it can always name what made it (task 0039). */
    embeddingModel: varchar("embedding_model", { length: 120 }).notNull(),
    /** Normalized topic slugs; tagging crosses the database boundary by value (ADR-0088). */
    topicTags: text("topic_tags").array().notNull().default(sql`'{}'::text[]`),
  },
  (t) => [
    uniqueIndex("ix_chunk_document_id_ordinal").on(t.documentId, t.ordinal),
    index("ix_chunk_document_id_heading").on(t.documentId, t.heading),
    index("ix_chunk_topic_tags").using("gin", t.topicTags),
  ],
);

/**
 * One open-licensed photograph a card may carry (ADR-0095). Not a `document`: an image
 * is retrieved whole as something a card SHOWS, and it carries an attribution that must
 * be displayed and a licence that decides whether it may be used at all.
 */
export const image = pgTable(
  "image",
  {
    id: id(),
    createdAt: createdAt(),
    manifestPath: varchar("manifest_path", { length: 1000 }).notNull(),
    /** The image's identity, globally: the same photograph under two subjects is one entry. */
    sourceUrl: text("source_url").notNull().unique("uq_image_source_url"),
    /** sha256 of the entry's own fields, so one reworded description re-embeds one row. */
    contentHash: varchar("content_hash", { length: 64 }).notNull(),
    title: varchar("title", { length: 500 }).notNull(),
    /** The highest-leverage field in the catalog: it is what gets embedded and matched. */
    description: text("description").notNull(),
    /** The page a human re-checks the licence against; `sourceUrl` usually states none. */
    sourcePage: text("source_page").notNull(),
    licence: imageLicence("licence").notNull(),
    /** NOT NULL even for public domain: a renderer deciding whether attribution is required gets it wrong once. */
    attribution: text("attribution").notNull(),
    category: varchar("category", { length: 120 }).notNull(),
    subCategory: varchar("sub_category", { length: 120 }),
    topicTags: text("topic_tags").array().notNull().default(sql`'{}'::text[]`),
    embedding: vector("embedding", { dimensions: EMBEDDING_DIM }).notNull(),
    embeddingModel: varchar("embedding_model", { length: 120 }).notNull(),
    /** Where the image is served from once re-hosted; NULL while it is served from `sourceUrl`. */
    hostedUrl: text("hosted_url"),
    ingestedAt: timestamp("ingested_at", { withTimezone: true }).notNull(),
  },
  (t) => [
    index("ix_image_category_sub_category").on(t.category, t.subCategory),
    index("ix_image_manifest_path").on(t.manifestPath),
    index("ix_image_topic_tags").using("gin", t.topicTags),
  ],
);

/**
 * One authored curriculum, parsed. Teaching structure, not knowledge: no vector and
 * nothing embedded, because syllabus scaffolding in the retrieval pool is something
 * cards would ground on.
 */
export const curriculum = pgTable("curriculum", {
  id: id(),
  createdAt: createdAt(),
  sourcePath: varchar("source_path", { length: 1000 }).notNull().unique("uq_curriculum_source_path"),
  contentHash: varchar("content_hash", { length: 64 }).notNull(),
  /** The projection's match key against `topic.canonical_name`, by value. */
  topicName: varchar("topic_name", { length: 500 }).notNull(),
  description: text("description").notNull(),
  isSurvey: boolean("is_survey").notNull(),
  ingestedAt: timestamp("ingested_at", { withTimezone: true }).notNull(),
});

/** One curriculum unit; becomes a subtopic group (one row per tier) in the projection. */
export const curriculumSubtopic = pgTable(
  "curriculum_subtopic",
  {
    id: id(),
    createdAt: createdAt(),
    curriculumId: uuid("curriculum_id")
      .notNull()
      .references(() => curriculum.id, { onDelete: "cascade" }),
    ordinal: integer("ordinal").notNull(),
    /** The projection's match key against `subtopic.title`: renaming replaces rather than edits. */
    title: varchar("title", { length: 160 }).notNull(),
    description: text("description").notNull(),
    /** Titles of other subtopics in this curriculum; a DAG, checked before a row is written. */
    prerequisites: text("prerequisites").array().notNull().default(sql`'{}'::text[]`),
    sourcePaths: text("source_paths").array().notNull().default(sql`'{}'::text[]`),
    /** `{tier: {...}}` for the 1-3 tiers taught, shape guaranteed by the curriculum contract. */
    tiers: jsonb("tiers").$type<Record<string, unknown>>().notNull(),
  },
  (t) => [uniqueIndex("ix_curriculum_subtopic_curriculum_id_ordinal").on(t.curriculumId, t.ordinal)],
);
