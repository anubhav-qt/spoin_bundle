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
| 7 | Admin in Next.js: repairs, ASCII review, the topic queue, job status (tadpole runs land with 9, model accounts with 8). Runs after 10 | done |
| 8 | pi fork from Trotter (+ images), CLIProxyAPI compose service, NIM balancer (from breader) | |
| 9 | The tadpoles: wake queue, runs and transcripts, compaction, versioned records; toad_sage, the curriculum tadpole, one tadpole per topic, auditor and lessons, the verification checklist; the AskAI chat behind `AskChat`; toad_sage links related topics (`topic_edge`) and spins new topics out of a survey, recommended once it is done; q8 vs fp32 measured on the first new topic's corpus | |
| 10 | Web rewire: `lib/api.ts` to the shared contract, Better Auth client for login. Runs before 7 | done |
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
  the job), or accepts it (canonical name and slug, category, then the topic's tadpole).
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
- **A requested topic's content is made the way the manual pipeline made it** (2026-10-11).
  The topic's tadpole runs `docs/the_spoin_universe/procedure.md` phase by phase, toad_sage
  doing Phase A's intake: a coverage check against the corpus already there; web research
  from primary sources into a raw dump that keeps every passage's URL and date; curation
  passage by passage into self-contained `##` sections, 1,000-2,000 characters and never over
  2,200 (one section is one chunk, and nothing splits it); a `tips-and-tricks.md`; the image
  pass; then the curriculum. Each delivery passes frog's `corpus:check`, `images:check` and
  `curriculum:check` before it is ingested.
- **The web is rewired before admin is built** (2026-10-11): Phase 10 runs before Phase 7, so
  the admin pages sign in through the rewired web and nothing is built twice. The tadpole
  runs page lands with Phase 9's tables and the model accounts page with Phase 8's.
- **The topic queue page** (2026-10-11) lists pending topics with their generate jobs, the
  owner's and readers' alike. The owner can add a topic by name (a reader's request without
  the subscription), retry a failed job, cancel a pending topic (its placeholder, alias and
  job go, and so do its requesters' subscriptions) and change a job's priority.
- **A topic the owner adds runs at priority 0** (2026-10-11): behind readers' requests (10),
  ahead of repairs (-10); higher runs first. The owner moves topics through the queue from
  the topic queue page itself.
- **The job status page** (2026-10-11) shows each background job's last success and last
  error from `job_runs`, the generate and repair queue counted by status, and every failed
  job with its `last_error`.
- **Topics move through the queue by drag** (2026-10-11). On `/admin/queue` the owner drags a
  waiting topic to where it should run; the page sends only where it was dropped (just ahead
  of which job, or last), and the server sets the priorities: the moved job takes one from its
  new neighbours, and jobs above it that no longer run first are lifted a tie at a time, so
  nothing below the drop changes and jobs that tied still tie (`apps/server/src/jobs/order.ts`).
  The claim order is `priority desc, created_at, id`, in `QUEUE_ORDER`, which Phase 9's
  worker claims by. Built with framer-motion's `Reorder`, already a web dependency, from a
  handle, so a phone can still scroll the list. `/admin/jobs` is the job status page.
- **The web in the workspace** (2026-10-11). `apps/web` joins the npm workspace and
  `npm run check` typechecks it; Biome stays off it, so the UI keeps its own style
  (ADR-0106: the web changes only where the API did). In development it runs as the `web`
  service of `infra/compose.yml` on host port 3001, next to the API on 8001. The root
  `docker-compose.yml`'s `web` service (the old stack, port 3000) no longer runs this web;
  Phase 11 deletes it.
- **The lockfile is written by npm 10** (2026-10-11). npm 11 prunes other platforms' optional
  entries (`@esbuild/*`, `@rolldown/*`, `lightningcss-*`, `fsevents`, and the musl builds of
  swc and sharp the web image needs), which breaks `npm ci` in the Linux images. Never
  `npm install` with npm 11; regenerate with `npx -y npm@10.9.4 install --package-lock-only`,
  then `npm ci`.
- **The web signs in through Better Auth** (2026-10-11). `lib/api.ts` speaks the `@spoin/shared`
  types; a sign-in keeps the one bearer token from `set-auth-token` (no refresh). A guest's
  Google sign-in claims in place and falls back to a plain sign-in when the Google account
  already has a user (409). Outside production, CORS and Better Auth's origin check share one
  rule (`originAllowed`), so a phone on the owner's network can sign in to a dev server.
- **The web follows `scope`** (2026-10-11). A survey or one-shot shows no tier labels or
  gates; its one quiz starts without a difficulty and reads as a mastery quiz across the
  whole topic, unlocked at 80% of every subtopic. Cards keep their difficulty marks.
  `TopicDiscoverOut` gains `scope`, so discovery's tier picker knows too.
- **The feed notices say what is true** (2026-10-11). Cards are written once, so no notice
  promises more: a second pass says nothing new is on the way, take the quiz or pick another
  topic; `exhausted` means the feed's topics have no cards yet, because a topic is written
  in full before its first card appears.

- **The harness tools are designed before Phase 8** (2026-10-11), one agent at a time, so the
  pi fork's tool wrapper is built knowing every tool.
- **The chats run corpus first, then curriculum** (2026-10-11). toad_sage accepts a topic; the
  topic's tadpole does the coverage check, research, corpus, `tips-and-tricks.md` and images;
  the curriculum chat writes the curriculum against that corpus; the topic's tadpole writes the
  cards and questions; the verification checklist runs; the topic goes live and its tadpole
  becomes its frog.
- **One curriculum chat for every topic** (2026-10-11), not one per topic. When several topics
  need a curriculum at once, it runs a helper agent per topic and stays the one orchestrator,
  and it learns from feedback and experience, so its curricula get better over time.
- **toad_sage plays the owner's part** (2026-10-11) at the procedure's approval points: the
  coverage note, the curriculum proposal, every "insufficient evidence" and the closing report.
  The tadpole or the curriculum chat hands each one over as a record, and toad_sage answers go
  on or change this. toad_sage is one chat too, the orchestrator, running helper agents in
  parallel for different tadpoles and frogs, and it learns from feedback and experience like
  the curriculum chat.
- **A helper acts, then reports** (2026-10-11). A helper agent is short-lived: one task (an
  intake, a review, a curriculum), started by its main chat with a brief. It gets the main
  chat's tools except starting helpers, acts directly, and ends by handing the main chat a
  short report as a record. Its run is stored like any other, so the Auditor reads it.
- **A topic has a category** (2026-10-11). toad_sage's accept writes the canonical name, slug,
  scope, `category` and `sub_category` to the topic row: two new columns on the app's `topic`,
  so the product can group and browse topics by category, normalized as the corpus normalizes
  them (ADR-0091). The card count and what the topic should cover go in a versioned intake
  record, which the topic's tadpole and the curriculum chat read.
- **toad_sage merges into live and queued topics** (2026-10-11). A requested name can fold into
  a topic that is still being written, so near-identical requests are written once and every
  requester gets the topic when it goes live; a reader who already follows the target keeps
  one subscription.
- **A survey's spin-outs are queued when it goes live** (2026-10-11). toad_sage adds each topic
  the survey introduces to the queue at the owner's priority (0), since it plays the owner's
  part, with a `deep_dive` edge from the survey. The owner can drag them like any other topic.
- **Topics link as `related` too** (2026-10-11). `topic_edge_kind` gains `related`, joining peer
  topics that share material; `deep_dive` stays survey to topic. toad_sage writes them when a
  topic goes live and adds more as newer topics arrive. A related edge is stored once and read
  either way, so AskAI's `passages` reaches a peer's corpus too.
- **The tool catalogue is `docs/architecture/harness-tools.md`** (2026-10-11), filled in one chat
  at a time as the owner approves each set. Approved so far: toad_sage's, and a topic's
  tadpole's research, corpus, images and report.
- **A topic is a subject plus an angle** (2026-10-11): who it is for and how it is written.
  "Rust" and "Rust in easy language" are two topics, and a homonym never merges into its
  namesake. The intake record stores the angle; `find_topics` shows each match's subject,
  angle, description and aliases, scoring the name and the meaning separately; toad_sage's
  judgment decides a merge, stating both topics' subject and angle. The reader's optional
  description is read by toad_sage and ero_sennin alike, and a merge record keeps the requested
  name and description. ero_sennin reads every merge and can undo a wrong one, recreating the
  topic and putting its job back in the queue.
- **The Auditor is ero_sennin** (2026-10-11), after the toad sage Jiraiya.
- **A description sends an exact match to toad_sage** (2026-10-11). A requested name that
  matches an alias exactly still subscribes at once when it comes without a description. With
  one, it is queued like a new name, with no alias of its own yet, and toad_sage merges it into
  the existing topic if the description fits or accepts it as its own topic if not (Rust, the
  video game). Lands in `topics/request.ts` with toad_sage in Phase 9.
- **A similar topic reuses what was fetched** (2026-10-11). When a topic shares its subject
  with one already written (Rust in easy language, after Rust), its tadpole works from the
  existing corpus and the pages already fetched, reshaping that material to what the request
  asks, and searches the web only for what the request needs and nothing stored covers.
  toad_sage's intake record names the topics it builds on. So fetched pages are kept and
  searchable after a run, not wiped like the procedure's `temp/`.
- **The tadpoles search with our own SearXNG** (2026-10-11), a compose service querying Google,
  Bing, DuckDuckGo and others at once, as Trotter does: no quota, any model. They read every
  page themselves with our own fetch tool (article text from HTML, text from PDFs), keeping each
  passage's URL and date.
- **Fetched pages live on disk, indexed in Postgres** (2026-10-11). A page's content stays on
  disk; Postgres keeps the pointer (URL, fetch date, source date, path, hash), and pgvector the
  embeddings of its passages, so a later run finds them by meaning. Kept apart from the corpus
  tables, so card writing and AskAI never retrieve an unvetted page. A run's notes and open
  questions are records.
- **The fetch tool falls back to a headless browser** (2026-10-11). Public pages only, never
  past a login or paywall, paced per site, and a stored page is read from disk rather than
  fetched again. A plain HTTP fetch comes first (article text from HTML, text from PDFs); a page
  with no real text is loaded again in a headless Chromium, so docs sites that are JavaScript
  apps are in reach.
- **The fetch tool ignores robots.txt** (2026-10-11), as Trotter's tools do: every public page
  is in reach, and pacing per site is the courtesy.
- **A tadpole's run follows ADR-0100 in full** (2026-10-11). The tadpole writes the maps of
  `docs/handoff/corpus-authoring-system.md` (A to J) as records before any prose, and toad_sage
  approves them, playing the human co-curator. Claims carry their class, scope and confidence;
  documents carry the epistemic front matter, and `corpus:check` enforces it. The auditing
  roles (versions, false precision, the coverage matrix) run as separate calls that see the
  drafts and the sources, never the author's reasoning. "Insufficient evidence" is a valid
  result.
- **A topic's tadpole runs helpers too** (2026-10-11), under the same rules: it stays its topic's
  one author and starts helpers for parallel work, such as several research areas or maps at
  once. The auditing calls stay ones it does not brief.
- **A tadpole writes only its own topic's corpus** (2026-10-11). Stale material it notices in
  another topic's goes in its closing report, and toad_sage routes it to that topic's frog. Its
  drafts are ingested only once toad_sage says go on to the closing report, which is refused
  until the latest drafts are audited, every finding is fixed or answered, and `corpus:check`
  and `images:check` pass. The curriculum chat starts after ingestion.

## Asked when we get there

- Provider probes for CLIProxyAPI-Gemini, NIM and SearXNG before the harness depends on them (CLAUDE.md).
- The verification checklist's contents, written with the owner.
- Backups and image hosting on the ThinkPad, fetched pages on disk included.
- Which model grades quiz answers and answers AskAI on the request path, through the Phase 8
  balancer.
- What hands a reader's report to the frog in Phase 9: the report enqueuing the per-card
  `repair` job itself, or the frog reading open reports. Today only the operator enqueues it.
- A per-user rate limit on `/engagement/events`. The Python left it as a to-do ("a buggy client
  loop is indistinguishable from an attack", ADR-0011); the port has none until the owner picks
  one.
