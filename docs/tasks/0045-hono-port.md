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
| 5 | Read path, each with its tests (`/auth/me` gains `preferences` here): topics, feed (interleave, strata, ranking, session profile), engagement, quiz, notes, profile (preferences, fonts, avatar), reports, AskAI | done |
| 6 | frog: `normalize_topic_text`, the ONNX Qwen3 embedder, ingest contract + chunking + runner, curriculum contract + runner + projection, image contract + runner, retrieval | done |
| 7 | Admin in Next.js: repairs, ASCII review, the topic queue, tadpole runs, job status, model accounts | |
| 8 | pi fork from Trotter (+ images), CLIProxyAPI compose service, NIM balancer (from breader) | |
| 9 | The tadpoles: wake queue, runs and transcripts, compaction, versioned records; toad_sage, the curriculum tadpole, one tadpole per topic, auditor and lessons, the verification checklist; the AskAI chat behind `AskChat`; toad_sage links related topics (`topic_edge`) and spins new topics out of a survey, recommended once it is done; q8 vs fp32 measured on the first new topic's corpus | |
| 10 | Web rewire: `lib/api.ts` to the shared contract, Better Auth client for login | |
| 11 | Delete the Python (`apps/api`, `apps/worker`, `apps/frog`, `packages/api-types`), update CLAUDE.md, READMEs, Makefile, CI | |
| 12 | Port Paribelle from the ThinkPad to Oracle Cloud's free tier | later |
| 13 | Host spoin on the ThinkPad | later |

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
- **Cards are written once; a finished topic is announced** (2026-10-11). A topic's first
  generation is all the cards it gets; only reported cards are rewritten, by the frog. Readers
  master a topic and move on, so nothing generates more on demand and a short feed page
  enqueues nothing. When a reader has read everything, the feed serves the read cards again
  and sets `recycling` (the Python repeated them silently). Phase 10 rewrites the web notices
  that promise more cards are being written.
- **Hard rule 1 is enforced twice** (2026-10-11): a Biome `noRestrictedImports` override on the
  read path's files, and `test/architecture.test.ts`, which follows imports transitively.
- **The quiz grades through an injected `Grader`** (2026-10-11). Free-text grading is a model
  call on the request path, and the model layer is Phase 8, so `Deps.grader` is an interface:
  the server has `noGrader` until then (a written answer answers 502, "Grading failed, try
  again") and the tests stand the model in. No transaction stays open across the call; the
  attempt row is locked when the grade is written, so a double submit is graded once. ADR-0005's
  collection rule is checked by the typechecker in `test/architecture.test.ts`.
- **The repair queue and ASCII review are behind the admin role** (2026-10-11), in every
  environment, closing task 0035. They are ported as ADR-0076 has them: a report writes a row,
  and the operator's fix or remake enqueues the `repair` job. The executor is the frog's, so the
  tests write a landed repair directly. The gag library is copied to
  `apps/server/src/content/ascii-library/` and `build.mjs` puts it beside the bundle; a missing
  file throws instead of loading an empty library, because it is committed.
- **`/dev/*` never runs in production** (2026-10-11): mounted only with `DEV_ROUTES` and outside
  production, checked by a test. `/dev/reset` unfollows through the same path as the button, so
  subscriber counts stay true (the Python deleted the rows directly).
- **Topic scope; surveys and one-shots are tierless** (2026-10-11). `is_survey` is replaced by
  `scope` = `survey | topic | one_shot`, in the app DB (`topic_scope`) and the corpus DB
  (`document_scope` gains `one_shot`; `curriculum.is_survey` becomes `curriculum.scope`).
  Both `0001` migrations carry their old flag over. Only `topic` keeps three tiers. A
  tierless topic's feed fills its slate from the strata in order, easy first, each one
  diversified on its own so no harder card is pulled forward; a skipped card's cycle turns
  over only once the whole topic has nothing unseen. Its progress is the weakest subtopic's
  coverage across the whole topic. Its one quiz is mastery: `difficulty` is optional and
  ignored (a topic with tiers answers 422 without it), the MCQs split evenly across
  difficulties (any remainder to the hardest, a short difficulty topped up from the rest)
  and are asked easy to advanced, the free-text question comes from any difficulty, and
  the attempt is recorded in the advanced slot, so `QuizStartOut.difficulty` reads
  `advanced` and a pass sets `tier_quiz_passed[2]` and `mastered_at`. Following a tierless
  topic ignores the entry tier, and reads show `beginner` whatever is stored. `scope` is on
  `TopicOut`, `ProgressOut` and `TopicStatsOut`. The harness picks each topic's scope and
  card count; 125-750 cards per topic is an instruction to it, never a check in code.
- **AskAI: a chat per reader per topic** (2026-10-11). `GET /topics/{id}/ask`, the streamed
  `POST /topics/{id}/ask` and `POST /topics/{id}/ask/reset` keep ADR-0077's wire shape, so the
  web's `askStream` is unchanged. The answer comes from `Deps.askChat`, an injected `AskChat`:
  `noAskChat` until Phase 9 plugs the pi chat in (every turn ends in `error`, cause `empty`),
  and a stand-in in the tests. A turn hands the chat the conversation id (its memory is its
  own), the question, the card hint and `topicTools`: read-only, one topic, active cards
  only, with no user id or database handle, plus `passages` when a corpus is configured.
  `turn` is the one single-item model method, pinned in `test/architecture.test.ts`. The
  server keeps the 200-a-day cap and the `OFF_TOPIC` sentinel (any reply that starts with
  it, however chunked); the embedding pre-check and `ASK_AI_TOPIC_SIMILARITY_FLOOR` are gone.
  A refused turn counts against the cap; a failed or empty one does not.
- **spoin is hosted on the ThinkPad, not Oracle** (2026-10-11). Oracle Cloud's free tier takes
  Paribelle instead, moved off the ThinkPad.
- **Tool errors teach** (2026-10-11). A wrong tool call throws `ToolError`, one short line on
  what was wrong and how to call it right, which the harness returns to the agent as the
  call's result; any other failure is logged and reaches the agent as a short line. A
  half-good call returns what it could plus a `note`: AskAI's `read()` returns the cards it
  found and names the ids it left out, and errors only when none was found. Phase 9's tools
  follow the same rule, and its tool wrapper keeps argument-validation errors short too.

- **frog on TypeScript** (2026-10-11). The corpus, curriculum and image contracts, their
  runners and retrieval are in `packages/frog`, with `corpus:*`, `curriculum:*` and `images:*`
  scripts (`--check` needs no database or model). frog importing the server or the shared
  contract is caught twice, by a Biome override and `test/architecture.test.ts`; the values the
  two sides share are mirrored, and `apps/server/test/frog-mirror.test.ts` keeps them equal.
  The projection writes the app database, so it is the server's (`npm run curriculum:project`).
  Two fixes over the Python: an image manifest that lost a `source_url` to another is skipped
  rather than tripping the unique constraint, and a grounding ref whose heading repeats in a
  document resolves to both sections.
- **Curriculum front matter says `scope:`** (2026-10-11): `survey | topic | one_shot`, like the
  corpus. A file still carrying `is_survey` fails with a line naming the replacement.
- **The corpus is brand new** (2026-10-11). The tadpoles write it from Phase 9; the delivered
  corpus, curricula and images are not carried over, and nothing is measured on them.
- **The embedder stays q8 until Phase 9 measures it** (2026-10-11), on the first new topic's
  corpus, against fp32; if fp32 wins, everything is re-embedded.
- **AskAI's corpus tool** (2026-10-11). `passages(query)` searches the sections this topic's
  subtopics are grounded in, and those of every topic joined to it by a `topic_edge`, either
  way and of any kind. toad_sage decides those links in Phase 9. `ASK_AI_CONTEXT_NEIGHBOURS`
  sets how many results it returns, as it does for card search.

## Asked when we get there

- Web research tools for the tadpoles (Gemini search grounding through CLIProxyAPI, own fetch tools, or both).
- Provider probes for CLIProxyAPI-Gemini and NIM before the harness depends on them (CLAUDE.md).
- The verification checklist's contents, written with the owner.
- Backups and image hosting on the ThinkPad.
- Which model grades quiz answers and answers AskAI on the request path, through the Phase 8
  balancer.
- What hands a reader's report to the frog in Phase 9: the report enqueuing the per-card
  `repair` job itself, or the frog reading open reports. Today only the operator enqueues it.
- A per-user rate limit on `/engagement/events`. The Python left it as a to-do ("a buggy client
  loop is indistinguishable from an attack", ADR-0011); the port has none until the owner picks
  one.
