ALTER TYPE "public"."chat_role" ADD VALUE 'ask_ai';--> statement-breakpoint
ALTER TABLE "action_log" DROP CONSTRAINT "action_log_run_id_chat_run_id_fk";
--> statement-breakpoint
ALTER TABLE "chat_message" DROP CONSTRAINT "chat_message_chat_id_chat_id_fk";
--> statement-breakpoint
ALTER TABLE "chat_message" DROP CONSTRAINT "chat_message_run_id_chat_run_id_fk";
--> statement-breakpoint
ALTER TABLE "chat_run" DROP CONSTRAINT "chat_run_chat_id_chat_id_fk";
--> statement-breakpoint
ALTER TABLE "model_call" DROP CONSTRAINT "model_call_run_id_chat_run_id_fk";
--> statement-breakpoint
ALTER TABLE "chat" ADD COLUMN "ask_conversation_id" uuid;--> statement-breakpoint
ALTER TABLE "action_log" ADD CONSTRAINT "action_log_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "chat_ask_conversation_id_ask_conversation_id_fk" FOREIGN KEY ("ask_conversation_id") REFERENCES "public"."ask_conversation"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_message" ADD CONSTRAINT "chat_message_chat_id_chat_id_fk" FOREIGN KEY ("chat_id") REFERENCES "public"."chat"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_message" ADD CONSTRAINT "chat_message_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat_run" ADD CONSTRAINT "chat_run_chat_id_chat_id_fk" FOREIGN KEY ("chat_id") REFERENCES "public"."chat"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "model_call" ADD CONSTRAINT "model_call_run_id_chat_run_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."chat_run"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "uq_chat_ask_conversation" UNIQUE("ask_conversation_id");--> statement-breakpoint
ALTER TABLE "chat" ADD CONSTRAINT "ck_chat_ask_conversation" CHECK ((ask_conversation_id IS NOT NULL) = (role::text = 'ask_ai'));--> statement-breakpoint
-- Only an AskAI chat is ever deleted, with its reader's thread (task 0045). Its runs, transcript,
-- action log and compaction summaries go with it; every other chat's are kept for good.
CREATE FUNCTION refuse_chat_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	IF OLD.role::text <> 'ask_ai' THEN
		RAISE EXCEPTION 'Only an AskAI chat is ever deleted, with its thread';
	END IF;
	RETURN OLD;
END;
$$;--> statement-breakpoint
CREATE TRIGGER chat_deleted_only_if_ask_ai BEFORE DELETE ON "chat" FOR EACH ROW EXECUTE FUNCTION refuse_chat_delete();--> statement-breakpoint
CREATE FUNCTION forget_chat_summaries() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	WITH gone AS (
		DELETE FROM harness_record WHERE kind = 'compaction_summary' AND body->>'chatId' = OLD.id::text RETURNING id
	)
	DELETE FROM routed_record WHERE record_id IN (SELECT id FROM gone);
	RETURN NULL;
END;
$$;--> statement-breakpoint
CREATE TRIGGER chat_summaries_go_with_it AFTER DELETE ON "chat" FOR EACH ROW EXECUTE FUNCTION forget_chat_summaries();--> statement-breakpoint
-- The cascades below run after the chat's row is gone, so a row whose chat or run is gone is one
-- being deleted with its AskAI chat.
CREATE FUNCTION refuse_run_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	IF EXISTS (SELECT 1 FROM chat WHERE id = OLD.chat_id) THEN
		RAISE EXCEPTION 'A run is deleted only with its AskAI chat';
	END IF;
	RETURN OLD;
END;
$$;--> statement-breakpoint
CREATE TRIGGER chat_run_deleted_only_with_chat BEFORE DELETE ON "chat_run" FOR EACH ROW EXECUTE FUNCTION refuse_run_delete();--> statement-breakpoint
CREATE FUNCTION chat_message_only_grows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM chat WHERE id = OLD.chat_id) THEN
		RETURN OLD;
	END IF;
	RAISE EXCEPTION '% is only ever added to: write a new row instead', TG_TABLE_NAME;
END;
$$;--> statement-breakpoint
DROP TRIGGER chat_message_only_grows ON "chat_message";--> statement-breakpoint
CREATE TRIGGER chat_message_only_grows BEFORE UPDATE OR DELETE ON "chat_message" FOR EACH ROW EXECUTE FUNCTION chat_message_only_grows();--> statement-breakpoint
CREATE FUNCTION action_log_only_grows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM chat_run WHERE id = OLD.run_id) THEN
		RETURN OLD;
	END IF;
	RAISE EXCEPTION '% is only ever added to: write a new row instead', TG_TABLE_NAME;
END;
$$;--> statement-breakpoint
DROP TRIGGER action_log_only_grows ON "action_log";--> statement-breakpoint
CREATE TRIGGER action_log_only_grows BEFORE UPDATE OR DELETE ON "action_log" FOR EACH ROW EXECUTE FUNCTION action_log_only_grows();--> statement-breakpoint
CREATE FUNCTION harness_record_only_grows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
	IF TG_OP = 'DELETE' AND OLD.kind = 'compaction_summary'
		AND NOT EXISTS (SELECT 1 FROM chat WHERE id::text = OLD.body->>'chatId') THEN
		RETURN OLD;
	END IF;
	RAISE EXCEPTION '% is only ever added to: write a new row instead', TG_TABLE_NAME;
END;
$$;--> statement-breakpoint
DROP TRIGGER harness_record_only_grows ON "harness_record";--> statement-breakpoint
CREATE TRIGGER harness_record_only_grows BEFORE UPDATE OR DELETE ON "harness_record" FOR EACH ROW EXECUTE FUNCTION harness_record_only_grows();
