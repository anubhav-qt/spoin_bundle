ALTER TYPE "public"."document_scope" ADD VALUE 'one_shot';--> statement-breakpoint
ALTER TABLE "curriculum" ADD COLUMN "scope" "document_scope";--> statement-breakpoint
UPDATE "curriculum" SET "scope" = (CASE WHEN "is_survey" THEN 'survey' ELSE 'topic' END)::"document_scope";--> statement-breakpoint
ALTER TABLE "curriculum" ALTER COLUMN "scope" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "curriculum" DROP COLUMN "is_survey";