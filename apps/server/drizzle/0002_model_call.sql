CREATE TYPE "public"."model_call_failure" AS ENUM('rate', 'busy', 'slow', 'empty', 'cut', 'bad', 'gone');--> statement-breakpoint
CREATE TABLE "model_call" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"started_at" timestamp with time zone NOT NULL,
	"provider" varchar(32) NOT NULL,
	"model" varchar(128) NOT NULL,
	"ok" boolean NOT NULL,
	"failure" "model_call_failure",
	"reason" text,
	"first_token_ms" integer,
	"total_ms" integer NOT NULL,
	"prompt_tokens" integer,
	"output_tokens" integer,
	CONSTRAINT "ck_model_call_failure" CHECK (ok = (failure IS NULL))
);
--> statement-breakpoint
CREATE INDEX "ix_model_call_model_started" ON "model_call" USING btree ("model","started_at");