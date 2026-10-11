-- First boot of the Hono stack's own volume only (docker-entrypoint-initdb.d).
-- POSTGRES_DB creates `spoin`; the corpus is a second database (ADR-0088).
CREATE DATABASE the_spoin_universe OWNER spoin;
