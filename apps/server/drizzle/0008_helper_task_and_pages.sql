-- A helper carries its task, and the pages chats fetch are stored (task 0045).
CREATE TYPE "public"."helper_task" AS ENUM('helper', 'document_writer', 'curriculum_writer', 'tier_writer', 'corrector', 'verifier');--> statement-breakpoint
CREATE TABLE "page" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"url" text NOT NULL,
	"title" text,
	"path" varchar(1000) NOT NULL,
	"content_hash" varchar(64) NOT NULL,
	"fetched_with" varchar(16) NOT NULL,
	"fetched_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_page_url" UNIQUE("url")
);
--> statement-breakpoint
CREATE TABLE "page_passage" (
	"page_id" uuid NOT NULL,
	"ordinal" integer NOT NULL,
	"text" text NOT NULL,
	"embedding" vector(1024) NOT NULL,
	"embedding_model" varchar(120) NOT NULL,
	CONSTRAINT "pk_page_passage" PRIMARY KEY("page_id","ordinal")
);
--> statement-breakpoint
ALTER TABLE "chat" ADD COLUMN "task" "helper_task";--> statement-breakpoint
ALTER TABLE "page_passage" ADD CONSTRAINT "page_passage_page_id_page_id_fk" FOREIGN KEY ("page_id") REFERENCES "public"."page"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "ck_chat_task" CHECK ((task IS NOT NULL) = (role = 'helper'));