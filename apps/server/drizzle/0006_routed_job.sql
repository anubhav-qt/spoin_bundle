CREATE TABLE "routed_job" (
	"job_id" uuid PRIMARY KEY NOT NULL,
	"routed_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "routed_job" ADD CONSTRAINT "routed_job_job_id_generation_job_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."generation_job"("id") ON DELETE cascade ON UPDATE no action;