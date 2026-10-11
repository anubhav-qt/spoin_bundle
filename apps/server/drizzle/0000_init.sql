CREATE TYPE "public"."card_report_reason" AS ENUM('art', 'diagram', 'code_block', 'formatting', 'other');--> statement-breakpoint
CREATE TYPE "public"."card_source" AS ENUM('generated', 'authored');--> statement-breakpoint
CREATE TYPE "public"."card_status" AS ENUM('draft', 'active', 'rejected', 'superseded', 'retired');--> statement-breakpoint
CREATE TYPE "public"."difficulty" AS ENUM('beginner', 'intermediate', 'advanced');--> statement-breakpoint
CREATE TYPE "public"."engagement_kind" AS ENUM('impression', 'expand', 'collapse', 'dwell', 'skip', 'like', 'unlike', 'bookmark', 'unbookmark', 'note', 'share', 'ask_ai', 'explicit_complete', 'dwell_complete');--> statement-breakpoint
CREATE TYPE "public"."question_kind" AS ENUM('mcq', 'free_text');--> statement-breakpoint
CREATE TYPE "public"."question_status" AS ENUM('draft', 'active', 'rejected');--> statement-breakpoint
CREATE TYPE "public"."quiz_kind" AS ENUM('placement', 'promotion', 'mastery');--> statement-breakpoint
CREATE TYPE "public"."rejection_stage" AS ENUM('structural', 'near_duplicate', 'verification');--> statement-breakpoint
CREATE TYPE "public"."repair_mode" AS ENUM('fix', 'remake');--> statement-breakpoint
CREATE TYPE "public"."repair_status" AS ENUM('pending', 'running', 'done', 'failed');--> statement-breakpoint
CREATE TYPE "public"."seen_state" AS ENUM('unseen', 'deferred', 'seen');--> statement-breakpoint
CREATE TYPE "public"."topic_edge_kind" AS ENUM('deep_dive');--> statement-breakpoint
CREATE TYPE "public"."visual_kind" AS ENUM('ascii', 'image');--> statement-breakpoint
CREATE TABLE "app_user" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"display_name" varchar(80) NOT NULL,
	"email" varchar(320) NOT NULL,
	"email_verified" boolean DEFAULT false NOT NULL,
	"image" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"is_anonymous" boolean DEFAULT false NOT NULL,
	"role" varchar(32) DEFAULT 'user' NOT NULL,
	"banned" boolean DEFAULT false NOT NULL,
	"ban_reason" text,
	"ban_expires" timestamp with time zone,
	"onboarding_complete" boolean DEFAULT false NOT NULL,
	"age" integer,
	"gender" varchar(32),
	"avatar_icon" varchar(32),
	"has_avatar_image" boolean DEFAULT false NOT NULL,
	"daily_card_goal" integer DEFAULT 10 NOT NULL,
	CONSTRAINT "uq_app_user_email" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "ask_conversation" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"status" varchar(16) DEFAULT 'active' NOT NULL,
	"last_message_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "ask_message" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"conversation_id" uuid NOT NULL,
	"role" varchar(16) NOT NULL,
	"content" text NOT NULL,
	"on_topic" boolean DEFAULT true NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ask_usage" (
	"day" timestamp with time zone NOT NULL,
	"user_id" uuid NOT NULL,
	"questions_spent" integer DEFAULT 0 NOT NULL,
	CONSTRAINT "ask_usage_day_user_id_pk" PRIMARY KEY("day","user_id")
);
--> statement-breakpoint
CREATE TABLE "auth_account" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"account_id" text NOT NULL,
	"provider_id" text NOT NULL,
	"user_id" uuid NOT NULL,
	"access_token" text,
	"refresh_token" text,
	"id_token" text,
	"access_token_expires_at" timestamp with time zone,
	"refresh_token_expires_at" timestamp with time zone,
	"scope" text,
	"password" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "auth_session" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"token" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"ip_address" text,
	"user_agent" text,
	"user_id" uuid NOT NULL,
	"impersonated_by" text,
	CONSTRAINT "uq_auth_session_token" UNIQUE("token")
);
--> statement-breakpoint
CREATE TABLE "auth_verification" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"identifier" text NOT NULL,
	"value" text NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "card" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"family_id" uuid NOT NULL,
	"version" integer DEFAULT 1 NOT NULL,
	"status" "card_status" DEFAULT 'draft' NOT NULL,
	"topic_id" uuid NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"judged_difficulty" "difficulty",
	"title" varchar(120) NOT NULL,
	"canonical_title" varchar(160) NOT NULL,
	"summary" text NOT NULL,
	"body" text NOT NULL,
	"source" "card_source" DEFAULT 'generated' NOT NULL,
	"author_id" uuid,
	"content_embedding" vector(1024),
	"embedding_model" varchar(120),
	"grounded_chunk_ids" uuid[],
	"gen_meta" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"archetype" text[] DEFAULT '{}'::text[] NOT NULL,
	"is_hero" boolean DEFAULT false NOT NULL,
	"visual_id" varchar(64),
	"visual_kind" "visual_kind",
	"visual_slots" jsonb,
	CONSTRAINT "uq_card_family_id_version" UNIQUE("family_id","version"),
	CONSTRAINT "ck_card_version_positive" CHECK ("card"."version" >= 1),
	CONSTRAINT "ck_card_embedding_names_its_model" CHECK (("card"."content_embedding" IS NULL) = ("card"."embedding_model" IS NULL)),
	CONSTRAINT "ck_card_visual_kind_accompanies_visual_id" CHECK (("card"."visual_id" IS NULL) = ("card"."visual_kind" IS NULL))
);
--> statement-breakpoint
CREATE TABLE "card_bookmark" (
	"user_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_bookmark_user_id_card_id_pk" PRIMARY KEY("user_id","card_id")
);
--> statement-breakpoint
CREATE TABLE "card_like" (
	"user_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_like_user_id_card_id_pk" PRIMARY KEY("user_id","card_id")
);
--> statement-breakpoint
CREATE TABLE "card_note" (
	"user_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"body" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "card_note_user_id_card_id_pk" PRIMARY KEY("user_id","card_id")
);
--> statement-breakpoint
CREATE TABLE "card_repair" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"card_id" uuid NOT NULL,
	"job_id" uuid,
	"mode" "repair_mode" NOT NULL,
	"guidance" text,
	"source_image" "bytea",
	"status" "repair_status" DEFAULT 'pending' NOT NULL,
	"result_card_id" uuid,
	"error" text,
	"resolved_at" timestamp with time zone,
	"dismissed_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "card_report" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"card_id" uuid NOT NULL,
	"user_id" uuid NOT NULL,
	"reason" "card_report_reason" NOT NULL,
	"note" text,
	"resolved_at" timestamp with time zone,
	CONSTRAINT "uq_card_report_card_user" UNIQUE("card_id","user_id")
);
--> statement-breakpoint
CREATE TABLE "card_stats" (
	"card_id" uuid PRIMARY KEY NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"impressions" integer DEFAULT 0 NOT NULL,
	"expands" integer DEFAULT 0 NOT NULL,
	"likes" integer DEFAULT 0 NOT NULL,
	"bookmarks" integer DEFAULT 0 NOT NULL,
	"explicit_completes" integer DEFAULT 0 NOT NULL,
	"dwell_completes" integer DEFAULT 0 NOT NULL,
	"skips" integer DEFAULT 0 NOT NULL,
	"avg_dwell_ms" double precision DEFAULT 0 NOT NULL,
	"quality" double precision DEFAULT 0 NOT NULL,
	"recomputed_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "engagement_event" (
	"id" uuid PRIMARY KEY NOT NULL,
	"user_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"kind" "engagement_kind" NOT NULL,
	"dwell_ms" integer,
	"occurred_at" timestamp with time zone DEFAULT now() NOT NULL,
	"client_occurred_at" timestamp with time zone,
	"session_id" uuid,
	CONSTRAINT "ck_engagement_event_dwell_non_negative" CHECK ("engagement_event"."dwell_ms" IS NULL OR "engagement_event"."dwell_ms" >= 0)
);
--> statement-breakpoint
CREATE TABLE "feed_plan" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"topic_order" uuid[] NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"filter_key" varchar(64) DEFAULT '' NOT NULL,
	"share_fingerprint" varchar(64) DEFAULT '' NOT NULL,
	CONSTRAINT "uq_feed_plan_user_id" UNIQUE("user_id")
);
--> statement-breakpoint
CREATE TABLE "feed_slate" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"card_ids" uuid[] NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"degraded" boolean DEFAULT false NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	CONSTRAINT "uq_feed_slate_user_id_topic_id" UNIQUE("user_id","topic_id")
);
--> statement-breakpoint
CREATE TABLE "generation_job" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"kind" varchar(16) DEFAULT 'generate' NOT NULL,
	"topic_id" uuid NOT NULL,
	"card_id" uuid,
	"status" varchar(16) DEFAULT 'pending' NOT NULL,
	"progress" jsonb,
	"priority" integer DEFAULT 0 NOT NULL,
	"attempts" integer DEFAULT 0 NOT NULL,
	"last_error" text,
	"completed_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "job_runs" (
	"name" varchar(64) PRIMARY KEY NOT NULL,
	"last_ok_at" timestamp with time zone,
	"last_error" text,
	"last_error_at" timestamp with time zone,
	"detail" jsonb
);
--> statement-breakpoint
CREATE TABLE "question" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"kind" "question_kind" NOT NULL,
	"stem" text NOT NULL,
	"options" text[],
	"correct_index" integer,
	"rubric" text,
	"reference_answer" text,
	"explanation" text,
	"status" "question_status" DEFAULT 'draft' NOT NULL,
	"embedding" vector(1024),
	"embedding_model" varchar(120),
	"gen_meta" jsonb DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT "ck_question_kind_fields_present" CHECK (("question"."kind" = 'mcq' AND "question"."options" IS NOT NULL AND "question"."correct_index" IS NOT NULL) OR ("question"."kind" = 'free_text' AND "question"."rubric" IS NOT NULL)),
	CONSTRAINT "ck_question_embedding_names_its_model" CHECK (("question"."embedding" IS NULL) = ("question"."embedding_model" IS NULL))
);
--> statement-breakpoint
CREATE TABLE "quiz_attempt" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"kind" "quiz_kind" NOT NULL,
	"score" double precision,
	"passed" boolean,
	"started_at" timestamp with time zone NOT NULL,
	"submitted_at" timestamp with time zone,
	"graded_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "quiz_attempt_question" (
	"attempt_id" uuid NOT NULL,
	"question_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_answer" text,
	"correct" boolean,
	"rubric_level" integer,
	"justification" text,
	CONSTRAINT "quiz_attempt_question_attempt_id_question_id_pk" PRIMARY KEY("attempt_id","question_id")
);
--> statement-breakpoint
CREATE TABLE "rejected_card" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"topic_id" uuid NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"requested_difficulty" "difficulty" NOT NULL,
	"title" varchar(120) NOT NULL,
	"canonical_title" varchar(160) NOT NULL,
	"summary" text NOT NULL,
	"body" text NOT NULL,
	"stage" "rejection_stage" NOT NULL,
	"reason" text NOT NULL,
	"gen_meta" jsonb DEFAULT '{}'::jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "subtopic" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"topic_id" uuid NOT NULL,
	"subtopic_group_id" uuid DEFAULT gen_random_uuid() NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"title" varchar(160) NOT NULL,
	"description" text NOT NULL,
	"target_cards" integer NOT NULL,
	"min_cards" integer NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"card_type_quotas" jsonb,
	"grounding_refs" text[],
	CONSTRAINT "ck_subtopic_min_within_target" CHECK ("subtopic"."min_cards" <= "subtopic"."target_cards"),
	CONSTRAINT "ck_subtopic_target_cards_band" CHECK ("subtopic"."target_cards" BETWEEN 5 AND 25)
);
--> statement-breakpoint
CREATE TABLE "topic" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"slug" varchar(120) NOT NULL,
	"canonical_name" varchar(120) NOT NULL,
	"description" text,
	"embedding" vector(1024),
	"embedding_model" varchar(120),
	"is_seeded" boolean DEFAULT false NOT NULL,
	"is_survey" boolean DEFAULT false NOT NULL,
	"curriculum_generated_at" timestamp with time zone,
	"curriculum_corpus_version" varchar(64),
	"subscriber_count" integer DEFAULT 0 NOT NULL,
	CONSTRAINT "uq_topic_slug" UNIQUE("slug"),
	CONSTRAINT "ck_topic_embedding_names_its_model" CHECK (("topic"."embedding" IS NULL) = ("topic"."embedding_model" IS NULL))
);
--> statement-breakpoint
CREATE TABLE "topic_alias" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"normalized_text" varchar(200) NOT NULL,
	"raw_text" varchar(200) NOT NULL,
	"topic_id" uuid NOT NULL,
	"decided_by" varchar(20) NOT NULL,
	"similarity" double precision,
	CONSTRAINT "uq_topic_alias_normalized_text" UNIQUE("normalized_text")
);
--> statement-breakpoint
CREATE TABLE "topic_edge" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"from_topic_id" uuid NOT NULL,
	"to_topic_id" uuid NOT NULL,
	"kind" "topic_edge_kind" DEFAULT 'deep_dive' NOT NULL,
	CONSTRAINT "uq_topic_edge_from_topic_id_to_topic_id_kind" UNIQUE("from_topic_id","to_topic_id","kind"),
	CONSTRAINT "ck_topic_edge_no_self_edge" CHECK ("topic_edge"."from_topic_id" <> "topic_edge"."to_topic_id")
);
--> statement-breakpoint
CREATE TABLE "user_avatar" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"data" "bytea" NOT NULL,
	"media_type" varchar(32) NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "user_card_state" (
	"user_id" uuid NOT NULL,
	"card_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"state" "seen_state" DEFAULT 'unseen' NOT NULL,
	"deferred_cycle" integer,
	"completed_via" "engagement_kind",
	"seen_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_card_state_user_id_card_id_pk" PRIMARY KEY("user_id","card_id")
);
--> statement-breakpoint
CREATE TABLE "user_font" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"name" varchar(80) NOT NULL,
	"format" varchar(8) NOT NULL,
	"data" "bytea" NOT NULL,
	"byte_size" integer NOT NULL,
	CONSTRAINT "ck_user_font_format_valid" CHECK ("user_font"."format" IN ('woff2', 'ttf', 'otf'))
);
--> statement-breakpoint
CREATE TABLE "user_preference" (
	"user_id" uuid PRIMARY KEY NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"palette" varchar(64) DEFAULT 'notebook' NOT NULL,
	"custom_palettes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"font" varchar(64) DEFAULT 'literata' NOT NULL
);
--> statement-breakpoint
CREATE TABLE "user_question_seen" (
	"user_id" uuid NOT NULL,
	"question_id" uuid NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_question_seen_user_id_question_id_pk" PRIMARY KEY("user_id","question_id")
);
--> statement-breakpoint
CREATE TABLE "user_seen_bitmap" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"bits" "bytea" NOT NULL,
	"rebuilt_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_seen_bitmap_user_id_topic_id_pk" PRIMARY KEY("user_id","topic_id")
);
--> statement-breakpoint
CREATE TABLE "user_session_topic_signal" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"score" double precision DEFAULT 0 NOT NULL,
	"last_event_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_session_topic_signal_user_id_topic_id_pk" PRIMARY KEY("user_id","topic_id")
);
--> statement-breakpoint
CREATE TABLE "user_subtopic_progress" (
	"user_id" uuid NOT NULL,
	"subtopic_id" uuid NOT NULL,
	"seen_count" integer DEFAULT 0 NOT NULL,
	"total_count" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_subtopic_progress_user_id_subtopic_id_pk" PRIMARY KEY("user_id","subtopic_id")
);
--> statement-breakpoint
CREATE TABLE "user_topic" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"display_name" varchar(120) NOT NULL,
	"is_custom" boolean DEFAULT false NOT NULL,
	"accent_hue" integer,
	CONSTRAINT "uq_user_topic_user_id_topic_id" UNIQUE("user_id","topic_id")
);
--> statement-breakpoint
CREATE TABLE "user_topic_affinity" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"affinity" double precision DEFAULT 1 NOT NULL,
	"recomputed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_topic_affinity_user_id_topic_id_pk" PRIMARY KEY("user_id","topic_id")
);
--> statement-breakpoint
CREATE TABLE "user_topic_cycle" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"cycle" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_topic_cycle_user_id_topic_id_difficulty_pk" PRIMARY KEY("user_id","topic_id","difficulty")
);
--> statement-breakpoint
CREATE TABLE "user_topic_difficulty_progress" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"difficulty" "difficulty" NOT NULL,
	"seen_count" integer DEFAULT 0 NOT NULL,
	"total_count" integer DEFAULT 0 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_topic_difficulty_progress_user_id_topic_id_difficulty_pk" PRIMARY KEY("user_id","topic_id","difficulty")
);
--> statement-breakpoint
CREATE TABLE "user_topic_progress" (
	"user_id" uuid NOT NULL,
	"topic_id" uuid NOT NULL,
	"current_difficulty" "difficulty" DEFAULT 'beginner' NOT NULL,
	"tier_unlocked" boolean[] DEFAULT ARRAY[false, false, false] NOT NULL,
	"tier_content_complete" boolean[] DEFAULT ARRAY[false, false, false] NOT NULL,
	"tier_quiz_passed" boolean[] DEFAULT ARRAY[false, false, false] NOT NULL,
	"mastered_at" timestamp with time zone,
	"revisit_mode" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_topic_progress_user_id_topic_id_pk" PRIMARY KEY("user_id","topic_id")
);
--> statement-breakpoint
ALTER TABLE "ask_conversation" ADD CONSTRAINT "ask_conversation_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ask_conversation" ADD CONSTRAINT "ask_conversation_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ask_message" ADD CONSTRAINT "ask_message_conversation_id_ask_conversation_id_fk" FOREIGN KEY ("conversation_id") REFERENCES "public"."ask_conversation"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "ask_usage" ADD CONSTRAINT "ask_usage_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "auth_account" ADD CONSTRAINT "auth_account_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "auth_session" ADD CONSTRAINT "auth_session_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card" ADD CONSTRAINT "card_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card" ADD CONSTRAINT "card_subtopic_id_subtopic_id_fk" FOREIGN KEY ("subtopic_id") REFERENCES "public"."subtopic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card" ADD CONSTRAINT "card_author_id_app_user_id_fk" FOREIGN KEY ("author_id") REFERENCES "public"."app_user"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_bookmark" ADD CONSTRAINT "card_bookmark_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_bookmark" ADD CONSTRAINT "card_bookmark_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_like" ADD CONSTRAINT "card_like_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_like" ADD CONSTRAINT "card_like_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_note" ADD CONSTRAINT "card_note_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_note" ADD CONSTRAINT "card_note_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_repair" ADD CONSTRAINT "card_repair_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_repair" ADD CONSTRAINT "card_repair_job_id_generation_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."generation_job"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_repair" ADD CONSTRAINT "card_repair_result_card_id_card_id_fk" FOREIGN KEY ("result_card_id") REFERENCES "public"."card"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_report" ADD CONSTRAINT "card_report_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_report" ADD CONSTRAINT "card_report_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "card_stats" ADD CONSTRAINT "card_stats_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "engagement_event" ADD CONSTRAINT "engagement_event_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "engagement_event" ADD CONSTRAINT "engagement_event_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "feed_plan" ADD CONSTRAINT "feed_plan_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "feed_slate" ADD CONSTRAINT "feed_slate_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "feed_slate" ADD CONSTRAINT "feed_slate_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "generation_job" ADD CONSTRAINT "generation_job_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "generation_job" ADD CONSTRAINT "generation_job_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "question" ADD CONSTRAINT "question_subtopic_id_subtopic_id_fk" FOREIGN KEY ("subtopic_id") REFERENCES "public"."subtopic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "question" ADD CONSTRAINT "question_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "quiz_attempt" ADD CONSTRAINT "quiz_attempt_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "quiz_attempt" ADD CONSTRAINT "quiz_attempt_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "quiz_attempt_question" ADD CONSTRAINT "quiz_attempt_question_attempt_id_quiz_attempt_id_fk" FOREIGN KEY ("attempt_id") REFERENCES "public"."quiz_attempt"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "quiz_attempt_question" ADD CONSTRAINT "quiz_attempt_question_question_id_question_id_fk" FOREIGN KEY ("question_id") REFERENCES "public"."question"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "rejected_card" ADD CONSTRAINT "rejected_card_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "rejected_card" ADD CONSTRAINT "rejected_card_subtopic_id_subtopic_id_fk" FOREIGN KEY ("subtopic_id") REFERENCES "public"."subtopic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "subtopic" ADD CONSTRAINT "subtopic_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "topic_alias" ADD CONSTRAINT "topic_alias_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "topic_edge" ADD CONSTRAINT "topic_edge_from_topic_id_topic_id_fk" FOREIGN KEY ("from_topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "topic_edge" ADD CONSTRAINT "topic_edge_to_topic_id_topic_id_fk" FOREIGN KEY ("to_topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_avatar" ADD CONSTRAINT "user_avatar_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_card_state" ADD CONSTRAINT "user_card_state_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_card_state" ADD CONSTRAINT "user_card_state_card_id_card_id_fk" FOREIGN KEY ("card_id") REFERENCES "public"."card"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_font" ADD CONSTRAINT "user_font_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_preference" ADD CONSTRAINT "user_preference_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_question_seen" ADD CONSTRAINT "user_question_seen_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_question_seen" ADD CONSTRAINT "user_question_seen_question_id_question_id_fk" FOREIGN KEY ("question_id") REFERENCES "public"."question"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_seen_bitmap" ADD CONSTRAINT "user_seen_bitmap_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_seen_bitmap" ADD CONSTRAINT "user_seen_bitmap_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_session_topic_signal" ADD CONSTRAINT "user_session_topic_signal_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_session_topic_signal" ADD CONSTRAINT "user_session_topic_signal_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_subtopic_progress" ADD CONSTRAINT "user_subtopic_progress_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_subtopic_progress" ADD CONSTRAINT "user_subtopic_progress_subtopic_id_subtopic_id_fk" FOREIGN KEY ("subtopic_id") REFERENCES "public"."subtopic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic" ADD CONSTRAINT "user_topic_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic" ADD CONSTRAINT "user_topic_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_affinity" ADD CONSTRAINT "user_topic_affinity_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_affinity" ADD CONSTRAINT "user_topic_affinity_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_cycle" ADD CONSTRAINT "user_topic_cycle_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_cycle" ADD CONSTRAINT "user_topic_cycle_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_difficulty_progress" ADD CONSTRAINT "user_topic_difficulty_progress_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_difficulty_progress" ADD CONSTRAINT "user_topic_difficulty_progress_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_progress" ADD CONSTRAINT "user_topic_progress_user_id_app_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."app_user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_topic_progress" ADD CONSTRAINT "user_topic_progress_topic_id_topic_id_fk" FOREIGN KEY ("topic_id") REFERENCES "public"."topic"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "uq_ask_conversation_active" ON "ask_conversation" USING btree ("user_id","topic_id") WHERE status = 'active';--> statement-breakpoint
CREATE INDEX "ix_ask_message_conversation" ON "ask_message" USING btree ("conversation_id","created_at");--> statement-breakpoint
CREATE INDEX "ix_auth_account_user_id" ON "auth_account" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_auth_session_user_id" ON "auth_session" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "ix_card_subtopic_id_status_difficulty" ON "card" USING btree ("subtopic_id","status","difficulty");--> statement-breakpoint
CREATE INDEX "ix_card_topic_id_status_difficulty" ON "card" USING btree ("topic_id","status","difficulty");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_card_family_id_active" ON "card" USING btree ("family_id") WHERE status = 'active';--> statement-breakpoint
CREATE INDEX "ix_card_grounded_chunk_ids" ON "card" USING gin ("grounded_chunk_ids");--> statement-breakpoint
CREATE INDEX "ix_card_repair_status" ON "card_repair" USING btree ("status");--> statement-breakpoint
CREATE INDEX "ix_card_report_unresolved" ON "card_report" USING btree ("card_id") WHERE resolved_at IS NULL;--> statement-breakpoint
CREATE INDEX "ix_engagement_event_card_id_kind" ON "engagement_event" USING btree ("card_id","kind");--> statement-breakpoint
CREATE INDEX "ix_engagement_event_user_id_occurred_at" ON "engagement_event" USING btree ("user_id","occurred_at");--> statement-breakpoint
CREATE UNIQUE INDEX "uq_generation_job_topic_pending" ON "generation_job" USING btree ("topic_id") WHERE kind = 'generate' AND status IN ('pending', 'running');--> statement-breakpoint
CREATE UNIQUE INDEX "uq_generation_job_card_pending" ON "generation_job" USING btree ("card_id") WHERE kind = 'repair' AND status IN ('pending', 'running');--> statement-breakpoint
CREATE INDEX "ix_generation_job_status_priority" ON "generation_job" USING btree ("status","priority");--> statement-breakpoint
CREATE INDEX "ix_question_subtopic_id_status" ON "question" USING btree ("subtopic_id","status");--> statement-breakpoint
CREATE INDEX "ix_rejected_card_subtopic_id" ON "rejected_card" USING btree ("subtopic_id");--> statement-breakpoint
CREATE INDEX "ix_subtopic_topic_id_difficulty" ON "subtopic" USING btree ("topic_id","difficulty");--> statement-breakpoint
CREATE INDEX "ix_subtopic_group_id" ON "subtopic" USING btree ("subtopic_group_id");--> statement-breakpoint
CREATE INDEX "ix_user_card_state_user_id_topic_id_state" ON "user_card_state" USING btree ("user_id","topic_id","state");--> statement-breakpoint
CREATE INDEX "ix_user_font_user_id" ON "user_font" USING btree ("user_id");