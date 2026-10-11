# Task 0045: Port spoin to TypeScript on Hono, and build the tadpole harness

- **Status:** In progress, branch `hono`
- **Decisions:** [ADR-0106](../adr/0106-typescript-on-hono-and-the-authoring-harness.md). Every one is the
  owner's. Do not re-open them; ask the owner when something new comes up, one question at a time.
- **Commits:** one line, `type: message`, no body, no Co-Authored-By. Push only with the owner's go-ahead.

## The rule that makes this fast and safe

Port, don't redesign. Same HTTP paths, same JSON field names, same schema (columns, constraints,
partial indexes, CHECKs), same invariants, each package's tests ported with it. The ADRs are
language-neutral: when a Python comment cites one, the TS keeps the citation. The exceptions are
the ones ADR-0106 decided: auth (Better Auth), generation (rebuilt as the harness), embeddings
(ONNX), jobs (our own queue).

The new stack runs as its own compose project with its own volume. Nothing in this task points at
`spoin_db_2`, its volume, or the old `.env` database URLs.

That stack is `infra/compose.yml` (project `spoin-hono`, volume `hono-db`), Postgres on host port
5434 and the API on 8001; 5432 and 5433 belong to other projects on this machine. `npm run stack`
starts it; `npm test` runs against `spoin_test` and `the_spoin_universe_test` there, and the
global setup refuses any database name that doesn't end in `_test`. Local settings live in
`infra/dev.env`, committed because nothing in it is real.

## Phases

| # | Phase | Status |
|---|---|---|
| 0 | ADR-0106, this doc, branch `hono` | done |
| 1 | Workspace: root `package.json`, Biome, `tsconfig.base.json`; `packages/shared`, `packages/frog`, `apps/server` skeletons | done |
| 2 | Drizzle schemas: app DB (from `apps/api/src/spoin/domain`) and universe DB (from `apps/frog/src/frog/universe` + `curriculum/models.py`), first migrations, `migrate.ts`, the test-DB guard (name must end in `_test`) | done |
| 3 | Hono app: env, logging, request id, errors as `{detail}`, CORS, OpenAPI doc, `/health` | done |
| 4 | Better Auth: email + password, Google, anonymous guests, bearer plugin, admin role. A guest claims *in place* (`/auth/claim`, `/auth/claim/google`), same user id, as ADR-0033 | done |
| 5 | Read path, each with its tests (`/auth/me` gains `preferences` here): topics, feed (interleave, strata, ranking, session profile), engagement, quiz, notes, profile (preferences, fonts, avatar), reports, AskAI | profile, notes, topics, engagement, feed done |
| 6 | frog: `normalize_topic_text`, the ONNX Qwen3 embedder, ingest contract + chunking + runner, curriculum contract + runner + projection, image contract + runner, retrieval | |
| 7 | Admin in Next.js: repairs, ASCII review, the topic queue, tadpole runs, job status, model accounts | |
| 8 | pi fork from Trotter (+ images), CLIProxyAPI compose service, NIM balancer (from breader) | |
| 9 | The tadpoles: wake queue, runs and transcripts, compaction, versioned records; toad_sage, the curriculum tadpole, one tadpole per topic, auditor and lessons, the verification checklist | |
| 10 | Web rewire: `lib/api.ts` to the shared contract, Better Auth client for login | |
| 11 | Delete the Python (`apps/api`, `apps/worker`, `apps/frog`, `packages/api-types`), update CLAUDE.md, READMEs, Makefile, CI | |
| 12 | Oracle Cloud free tier deploy | later |

## Decided during the port

- **Asking for a topic by name** (2026-10-11). `POST /topics` and `/topics/batch` call no model.
  Code checks the name (guests refused, word count); an exact alias match subscribes at once;
  a miss mints a pending topic (no subtopics, so nobody else sees it), the requester's custom
  subscription, an alias and a `generate` job at priority 10. In Phase 9 toad_sage takes
  those jobs and either rejects the name (job `failed`, `last_error` is the reason the user
  sees), merges it (repoint the subscriptions and the alias, drop the placeholder, complete
  the job), or accepts it (canonical name and slug, category, then the curriculum tadpole).
- **Tadpoles become frogs** (2026-10-11). A topic's tadpole becomes its frog once the topic's
  first generation is live in production; later updates and feedback-driven improvements
  run in the frog. `packages/frog`, the retrieval library, keeps its name: the owner is fine
  with both being frogs.
- **Reports go to the frogs** (2026-10-11). Card reports keep their ADR-0076 shape and their
  `repair` job, coalesced per card; in Phase 9 that job is routed to the frog of the card's
  topic. The frog sorts safe from suspicious by comparing with earlier reports of a similar
  style or from the same usernames, implements a genuine one as a new card version in the
  same family, and that version replaces the old one in production.
- **Agents fetch their history, they don't remember it** (2026-10-11). Every record an agent
  flags or judges lives in Postgres, and agents read it through tools when they need it, never
  from their own context. Phase 9's tool set and schema are built around that.
- **The feed's filter key is a digest** (2026-10-11). The Python stored the sorted, joined topic
  ids in a 64-character column, so filtering the feed to two or more topics overflowed it and
  500'd. The port stores their SHA-1 instead; no schema change.
- **Hard rule 1 is enforced twice** (2026-10-11): a Biome `noRestrictedImports` override on the
  read path's files, and `test/architecture.test.ts`, which follows imports transitively.

## Asked when we get there

- Web research tools for the tadpoles (Gemini search grounding through CLIProxyAPI, own fetch tools, or both).
- Provider probes for CLIProxyAPI-Gemini and NIM before the harness depends on them (CLAUDE.md).
- The verification checklist's contents, written with the owner.
- Backups and image hosting on Oracle.
- A per-user rate limit on `/engagement/events`. The Python left it as a to-do ("a buggy client
  loop is indistinguishable from an attack", ADR-0011); the port has none until the owner picks
  one.
