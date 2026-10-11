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

## Phases

| # | Phase | Status |
|---|---|---|
| 0 | ADR-0106, this doc, branch `hono` | done |
| 1 | Workspace: root `package.json`, Biome, `tsconfig.base.json`; `packages/shared`, `packages/frog`, `apps/server` skeletons | in progress |
| 2 | Drizzle schemas: app DB (from `apps/api/src/spoin/domain`) and universe DB (from `apps/frog/src/frog/universe` + `curriculum/models.py`), first migrations, `migrate.ts`, the test-DB guard (name must end in `_test`) | |
| 3 | Hono app: env, logging, request id, errors as `{detail}`, CORS, OpenAPI doc, `/health` | |
| 4 | Better Auth: email + password, Google, anonymous guests linked on claim, bearer plugin, admin role | |
| 5 | Read path, each with its tests: topics, feed (interleave, strata, ranking, session profile), engagement, quiz, notes, profile (preferences, fonts, avatar), reports, AskAI | |
| 6 | frog: `normalize_topic_text`, the ONNX Qwen3 embedder, ingest contract + chunking + runner, curriculum contract + runner + projection, image contract + runner, retrieval | |
| 7 | Admin in Next.js: repairs, ASCII review, the topic queue, tadpole runs, job status, model accounts | |
| 8 | pi fork from Trotter (+ images), CLIProxyAPI compose service, NIM balancer (from breader) | |
| 9 | The tadpoles: wake queue, runs and transcripts, compaction, versioned records; toad_sage, the curriculum tadpole, one tadpole per topic, auditor and lessons, the verification checklist | |
| 10 | Web rewire: `lib/api.ts` to the shared contract, Better Auth client for login | |
| 11 | Delete the Python (`apps/api`, `apps/worker`, `apps/frog`, `packages/api-types`), update CLAUDE.md, READMEs, Makefile, CI | |
| 12 | Oracle Cloud free tier deploy | later |

## Asked when we get there

- Web research tools for the tadpoles (Gemini search grounding through CLIProxyAPI, own fetch tools, or both).
- Provider probes for CLIProxyAPI-Gemini and NIM before the harness depends on them (CLAUDE.md).
- The verification checklist's contents, written with the owner.
- Backups and image hosting on Oracle.
