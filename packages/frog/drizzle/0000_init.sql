CREATE TYPE "public"."document_kind" AS ENUM('spoin_canon', 'topic_source');--> statement-breakpoint
CREATE TYPE "public"."document_scope" AS ENUM('survey', 'topic');--> statement-breakpoint
CREATE TYPE "public"."image_licence" AS ENUM('cc0', 'public-domain', 'cc-by', 'cc-by-sa', 'unsplash', 'pexels', 'pixabay');--> statement-breakpoint
CREATE TABLE "chunk" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"document_id" uuid NOT NULL,
	"ordinal" integer NOT NULL,
	"text" text NOT NULL,
	"heading" text,
	"embedding" vector(1024) NOT NULL,
	"embedding_model" varchar(120) NOT NULL,
	"topic_tags" text[] DEFAULT '{}'::text[] NOT NULL
);
--> statement-breakpoint
CREATE TABLE "curriculum" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"source_path" varchar(1000) NOT NULL,
	"content_hash" varchar(64) NOT NULL,
	"topic_name" varchar(500) NOT NULL,
	"description" text NOT NULL,
	"is_survey" boolean NOT NULL,
	"ingested_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_curriculum_source_path" UNIQUE("source_path")
);
--> statement-breakpoint
CREATE TABLE "curriculum_subtopic" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"curriculum_id" uuid NOT NULL,
	"ordinal" integer NOT NULL,
	"title" varchar(160) NOT NULL,
	"description" text NOT NULL,
	"prerequisites" text[] DEFAULT '{}'::text[] NOT NULL,
	"source_paths" text[] DEFAULT '{}'::text[] NOT NULL,
	"tiers" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "document" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"source" text NOT NULL,
	"title" varchar(500) NOT NULL,
	"kind" "document_kind" NOT NULL,
	"category" varchar(120),
	"sub_category" varchar(120),
	"scope" "document_scope",
	"source_path" varchar(1000) NOT NULL,
	"content_hash" varchar(64) NOT NULL,
	"source_date" timestamp with time zone,
	"ingested_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_document_source_path" UNIQUE("source_path"),
	CONSTRAINT "ck_document_topic_source_has_category_and_scope" CHECK ("document"."kind" <> 'topic_source' OR ("document"."category" IS NOT NULL AND "document"."scope" IS NOT NULL))
);
--> statement-breakpoint
CREATE TABLE "image" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"manifest_path" varchar(1000) NOT NULL,
	"source_url" text NOT NULL,
	"content_hash" varchar(64) NOT NULL,
	"title" varchar(500) NOT NULL,
	"description" text NOT NULL,
	"source_page" text NOT NULL,
	"licence" "image_licence" NOT NULL,
	"attribution" text NOT NULL,
	"category" varchar(120) NOT NULL,
	"sub_category" varchar(120),
	"topic_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"embedding" vector(1024) NOT NULL,
	"embedding_model" varchar(120) NOT NULL,
	"hosted_url" text,
	"ingested_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_image_source_url" UNIQUE("source_url")
);
--> statement-breakpoint
ALTER TABLE "chunk" ADD CONSTRAINT "chunk_document_id_document_id_fk" FOREIGN KEY ("document_id") REFERENCES "public"."document"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "curriculum_subtopic" ADD CONSTRAINT "curriculum_subtopic_curriculum_id_curriculum_id_fk" FOREIGN KEY ("curriculum_id") REFERENCES "public"."curriculum"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "ix_chunk_document_id_ordinal" ON "chunk" USING btree ("document_id","ordinal");--> statement-breakpoint
CREATE INDEX "ix_chunk_document_id_heading" ON "chunk" USING btree ("document_id","heading");--> statement-breakpoint
CREATE INDEX "ix_chunk_topic_tags" ON "chunk" USING gin ("topic_tags");--> statement-breakpoint
CREATE UNIQUE INDEX "ix_curriculum_subtopic_curriculum_id_ordinal" ON "curriculum_subtopic" USING btree ("curriculum_id","ordinal");--> statement-breakpoint
CREATE INDEX "ix_document_category_sub_category" ON "document" USING btree ("category","sub_category");--> statement-breakpoint
CREATE INDEX "ix_image_category_sub_category" ON "image" USING btree ("category","sub_category");--> statement-breakpoint
CREATE INDEX "ix_image_manifest_path" ON "image" USING btree ("manifest_path");--> statement-breakpoint
CREATE INDEX "ix_image_topic_tags" ON "image" USING gin ("topic_tags");