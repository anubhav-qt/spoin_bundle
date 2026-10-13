-- find_topics scores a requested name against every alias by trigram similarity (task 0045).
CREATE EXTENSION IF NOT EXISTS pg_trgm;--> statement-breakpoint
ALTER TABLE "topic" ADD COLUMN "category" varchar(120);--> statement-breakpoint
ALTER TABLE "topic" ADD COLUMN "sub_category" varchar(120);--> statement-breakpoint
ALTER TABLE "topic" ADD COLUMN "meaning_embedding" vector(1024);--> statement-breakpoint
ALTER TABLE "topic" ADD COLUMN "meaning_embedding_model" varchar(120);--> statement-breakpoint
ALTER TABLE "topic" ADD CONSTRAINT "ck_topic_meaning_embedding_names_its_model" CHECK (("topic"."meaning_embedding" IS NULL) = ("topic"."meaning_embedding_model" IS NULL));