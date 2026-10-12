CREATE TYPE "public"."chat_role" AS ENUM('toad_sage', 'curriculum', 'tadpole', 'designer_toad', 'visual_toad', 'ero_sennin', 'wise_toad', 'helper');--> statement-breakpoint
CREATE TYPE "public"."record_status" AS ENUM('active', 'retired', 'rejected', 'disputed');--> statement-breakpoint
CREATE TYPE "public"."run_status" AS ENUM('running', 'done', 'failed', 'stopped', 'interrupted', 'paused');--> statement-breakpoint
CREATE TYPE "public"."wake_status" AS ENUM('waiting', 'taken', 'done', 'given_up', 'dropped');--> statement-breakpoint
CREATE TABLE "action_log" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"run_id" uuid NOT NULL,
	"tool_call_id" varchar(256) NOT NULL,
	"at" timestamp with time zone DEFAULT now() NOT NULL,
	"tool" varchar(64) NOT NULL,
	"arguments" jsonb NOT NULL,
	"reasoning" text NOT NULL,
	"result" jsonb NOT NULL,
	"data_seen" jsonb NOT NULL,
	"records_written" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "chat" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"role" "chat_role" NOT NULL,
	"topic_id" uuid,
	"parent_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "ck_chat_topic" CHECK ((topic_id IS NOT NULL) = (role IN ('tadpole', 'designer_toad', 'visual_toad'))),
	CONSTRAINT "ck_chat_parent" CHECK ((parent_id IS NOT NULL) = (role = 'helper'))
);
--> statement-breakpoint
CREATE TABLE "chat_message" (
	"chat_id" uuid NOT NULL,
	"seq" integer NOT NULL,
	"run_id" uuid NOT NULL,
	"message" jsonb NOT NULL,
	CONSTRAINT "pk_chat_message" PRIMARY KEY("chat_id","seq")
);
--> statement-breakpoint
CREATE TABLE "chat_run" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"chat_id" uuid NOT NULL,
	"model" varchar(128) NOT NULL,
	"status" "run_status" DEFAULT 'running' NOT NULL,
	"triggers" jsonb NOT NULL,
	"system_prompt" text NOT NULL,
	"started_at" timestamp with time zone DEFAULT now() NOT NULL,
	"ended_at" timestamp with time zone,
	"error" text,
	CONSTRAINT "ck_chat_run_ended" CHECK ((status = 'running') = (ended_at IS NULL)),
	CONSTRAINT "ck_chat_run_error" CHECK ((status = 'failed') = (error IS NOT NULL))
);
--> statement-breakpoint
CREATE TABLE "harness_record" (
	"id" uuid NOT NULL,
	"version" integer NOT NULL,
	"seq" bigserial NOT NULL,
	"kind" varchar(64) NOT NULL,
	"status" "record_status" NOT NULL,
	"written_at" timestamp with time zone DEFAULT now() NOT NULL,
	"author" jsonb NOT NULL,
	"reason" text,
	"reverts_to" integer,
	"body" jsonb NOT NULL,
	CONSTRAINT "pk_harness_record" PRIMARY KEY("id","version"),
	CONSTRAINT "uq_harness_record_seq" UNIQUE("seq"),
	CONSTRAINT "ck_harness_record_version" CHECK (version >= 1),
	CONSTRAINT "ck_harness_record_reason" CHECK (version = 1 OR reason IS NOT NULL),
	CONSTRAINT "ck_harness_record_reverts" CHECK (reverts_to IS NULL OR (reverts_to >= 1 AND reverts_to < version))
);
--> statement-breakpoint
CREATE TABLE "scheduler_mark" (
	"name" varchar(64) PRIMARY KEY NOT NULL,
	"value" text NOT NULL
);
--> statement-breakpoint
CREATE TABLE "wake" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"chat_id" uuid NOT NULL,
	"status" "wake_status" DEFAULT 'waiting' NOT NULL,
	"due_at" timestamp with time zone NOT NULL,
	"trigger" jsonb NOT NULL,
	"tries" integer DEFAULT 0 NOT NULL,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "model_call" ADD COLUMN "run_id" uuid;--> statement-breakpoint
ALTER TABLE "action_log" ADD CONSTRAINT "action_log_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "chat_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "chat_parent_id_chat_id_fk" FOREIGN KEY ("parent_id") REFERENCES "public"."chat"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_message" ADD CONSTRAINT "chat_message_chat_id_chat_id_fk" FOREIGN KEY ("chat_id") REFERENCES "public"."chat"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_message" ADD CONSTRAINT "chat_message_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_run" ADD CONSTRAINT "chat_run_chat_id_chat_id_fk" FOREIGN KEY ("chat_id") REFERENCES "public"."chat"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "wake" ADD CONSTRAINT "wake_chat_id_chat_id_fk" FOREIGN KEY ("chat_id") REFERENCES "public"."chat"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "ix_action_log_run" ON "action_log" USING btree ("run_id","at");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_chat_single_role" ON "chat" USING btree ("role") WHERE role IN ('toad_sage', 'curriculum', 'ero_sennin', 'wise_toad');--> statement-breakpoint
CREATE UNIQUE INDEX "uq_chat_topic_role" ON "chat" USING btree ("topic_id","role") WHERE topic_id IS NOT NULL;--> statement-breakpoint
CREATE INDEX "ix_chat_message_run" ON "chat_message" USING btree ("run_id");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_chat_run_running" ON "chat_run" USING btree ("chat_id") WHERE status = 'running';--> statement-breakpoint
CREATE INDEX "ix_chat_run_chat_started" ON "chat_run" USING btree ("chat_id","started_at");--> statement-breakpoint
CREATE INDEX "ix_chat_run_started" ON "chat_run" USING btree ("started_at");--> statement-breakpoint
CREATE INDEX "ix_harness_record_kind" ON "harness_record" USING btree ("kind","id");--> statement-breakpoint
CREATE INDEX "ix_wake_status_due" ON "wake" USING btree ("status","due_at");--> statement-breakpoint
CREATE INDEX "ix_wake_chat" ON "wake" USING btree ("chat_id","status");--> statement-breakpoint
ALTER TABLE "model_call" ADD CONSTRAINT "model_call_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "ix_model_call_run" ON "model_call" USING btree ("run_id");--> statement-breakpoint
-- The transcript, the action log and every record version are only ever added to (Trotter's ADR
-- 0024): a change to a record is a new version, never an edit.
CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	RAISE EXCEPTION '% is only ever added to: write a new row instead', TG_TABLE_NAME;
END;
$$;--> statement-breakpoint
CREATE TRIGGER chat_message_only_grows BEFORE UPDATE OR DELETE ON "chat_message" FOR EACH ROW EXECUTE FUNCTION refuse_change();--> statement-breakpoint
CREATE TRIGGER chat_message_never_truncated BEFORE TRUNCATE ON "chat_message" FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();--> statement-breakpoint
CREATE TRIGGER action_log_only_grows BEFORE UPDATE OR DELETE ON "action_log" FOR EACH ROW EXECUTE FUNCTION refuse_change();--> statement-breakpoint
CREATE TRIGGER action_log_never_truncated BEFORE TRUNCATE ON "action_log" FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();--> statement-breakpoint
CREATE TRIGGER harness_record_only_grows BEFORE UPDATE OR DELETE ON "harness_record" FOR EACH ROW EXECUTE FUNCTION refuse_change();--> statement-breakpoint
CREATE TRIGGER harness_record_never_truncated BEFORE TRUNCATE ON "harness_record" FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
