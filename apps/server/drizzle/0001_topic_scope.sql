CREATE TYPE "public"."topic_scope" AS ENUM('survey', 'topic', 'one_shot');--> statement-breakpoint
ALTER TABLE "topic" ADD COLUMN "scope" "topic_scope" DEFAULT 'topic' NOT NULL;--> statement-breakpoint
UPDATE "topic" SET "scope" = 'survey' WHERE "is_survey";--> statement-breakpoint
ALTER TABLE "topic" DROP COLUMN "is_survey";