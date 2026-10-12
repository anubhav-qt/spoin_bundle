CREATE TABLE "routed_record" (
	"record_id" uuid PRIMARY KEY NOT NULL,
	"routed_at" timestamp with time zone DEFAULT now() NOT NULL
);
