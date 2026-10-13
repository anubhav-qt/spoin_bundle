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
| 8 | pi fork from Trotter (+ images), CLIProxyAPI compose service, NIM balancer (from breader) | done |
| 9 | The tadpoles: wake queue, runs and transcripts, compaction, versioned records; toad_sage, the curriculum tadpole, one tadpole per topic, auditor and lessons; the AskAI chat behind `AskChat`; toad_sage links related topics (`topic_edge`) and spins new topics out of a survey, recommended once it is done; q8 vs fp32 measured on the first new topic's corpus | in progress: store, run loop, compaction, scheduler and AskAI done; next the tools every chat has (`read_record`, `list_records`, `ask`, `answer`) with the real `handovers/question.njk` and `answer.njk` (a test fixture stands in), then the worker entrypoint and the agents, each prompt from the owner's gist |
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
  the server had `noGrader` until then (a written answer answers 502, "Grading failed, try
  again") and the tests stand the model in. Since Phase 8 it is `modelGrader` (below); `noGrader`
  is left for a process with no model keys. No transaction stays open across the call; the
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
  the harness chat from Phase 9 (below), `noAskChat` in a process with neither model key (every
  turn ends in `error`, cause `empty`), and a stand-in in the tests. A turn hands the chat the conversation id (its memory is its
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
  topic's tadpole does the coverage check, research, corpus and `tips-and-tricks.md`;
  the curriculum chat writes the curriculum against that corpus; visual_toad sources the images
  against it (2026-10-12); the topic's tadpole writes the cards and questions; each tier goes
  live once it passes the gate, and after the last one the tadpole becomes the topic's frog.
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
  (2026-10-12: a tier's writer helper starts its own pass-1 helper, and designer_toad and
  visual_toad serve a tadpole's requests for its whole run.)
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
  at a time as the owner approves each set. Complete on 2026-10-12: toad_sage's, a topic's
  tadpole's research, corpus and report, the curriculum chat's, the tadpole's cards and
  questions with their helpers, the frog's, ero_sennin's and wise_toad's.
- **A topic is a subject plus an angle** (2026-10-11): who it is for and how it is written.
  "Rust" and "Rust in easy language" are two topics, and a homonym never merges into its
  namesake. The intake record stores the angle; `find_topics` shows each match's subject,
  angle, description and aliases, scoring the name and the meaning separately; toad_sage's
  judgment decides a merge, stating both topics' subject and angle. The reader's optional
  description is read by toad_sage and ero_sennin alike, and a merge record keeps the requested
  name and description. ero_sennin reads every merge and can undo a wrong one, recreating the
  topic and putting its job back in the queue.
- **The Auditor is ero_sennin** (2026-10-11), after the toad sage Jiraiya.
- **The Lessons chat is wise_toad** (2026-10-12), Trotter's Lessons chat: lessons are versioned
  records it writes, changes and retires, each citing its evidence. It learns from the owner's
  reports once fixed (each one a lesson), ero_sennin's findings, the owner's rulings on
  disputes, the gate's rejections (rejected cards and wrongly solved questions, with pass 2's
  feedback), toad_sage's change verdicts, and readers' reports the frog acted on. Those last four
  become lessons only when they repeat. Every input wakes it as it arrives, except the gate's
  rejections, which wake it once per tier, together, when the tier is submitted. A lesson takes
  effect as soon as it is written, as in Trotter; a bad one becomes an ero_sennin finding. Each
  lesson names the chats it is for and the categories it applies to (none: every category), and
  a chat reads only the lessons for it and its topic's category. A lesson from the owner's
  report applies in every category.
- **ero_sennin reads each run as it ends** (2026-10-12). Every finished run, helpers included,
  queues a wake for it, so a wrong merge, retirement or verdict is caught while it is fresh.
- **An ero_sennin finding goes to the chat and to wise_toad** (2026-10-12). Each finding is a
  record that wakes the chat that ran (a helper's main chat, once the helper has ended), which
  fixes it or answers why not. wise_toad gets every finding and turns the ones that repeat into
  lessons. When ero_sennin still disagrees with an answer, toad_sage settles it with go on or
  change. A dispute over toad_sage's own decision goes to the owner instead: the decision
  stands meanwhile, the dispute is listed in admin with both sides, and the owner's ruling
  wakes both chats and goes to wise_toad. ero_sennin never writes content: a live card it finds
  wrong is a finding to the frog, which retires or rewrites it through the gate. It undoes only
  three things itself, each with its finding: a merge, a suspicious mark, and a compaction
  summary (putting back the earlier one with its cut point). Every other record is fixed by the
  chat that wrote it.
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
  passes (`images:check` moved to the end of image sourcing, 2026-10-12). The curriculum chat
  starts after ingestion.
- **Prompts are Nunjucks templates in `prompts/`** (2026-10-12): every chat's system
  instructions and every fixed prompt live in their own directory, so the code does not grow
  with them. Each one is written with the owner, one at a time: first a sentence or two on what
  the prompt will be, then the owner's gist of what it should do, then the template.
- **Every model output is checked in code first** (2026-10-12): validated right after it is
  generated, before anything acts on it, and a rejection always carries the reason why.
- **Gemini orchestrates and reviews, NIM writes** (2026-10-12). toad_sage, every main chat, the
  research, the gate's two passes, designer_toad and visual_toad run on Gemini 3.8 Flash at
  medium thinking through CLIProxyAPI. The heavy writing (corpus documents, curricula, cards,
  questions) runs on NIM behind breader's balancer and its ladder: Kimi K3 as primary, Nemotron 3
  Ultra while it is down, with breader's retries and overload handling.
- **Compaction is Trotter's, copied exactly** (2026-10-12): `E:\trotter`'s ADRs 0014 and 0026,
  `harness/src/compaction.ts`, `harness/src/wake-chat.ts`, `system-tools/compacting.ts`,
  `packages/schemas/src/compaction.ts` and its prompts (`compaction.njk`,
  `handovers/compaction-summary.njk`, `partials/summary.njk`, `tools/write-summary.njk`). A chat
  compacts at 400,000 tokens or 60% of its model's window, whichever is smaller. A compaction
  is a run of its own: the chat first stores what isn't stored, then `write_summary` writes a
  summary of under 2,000 tokens in fixed sections (so far, learnings, feedback received, do's,
  don'ts, next steps), folding in the earlier one. The summary is one versioned record per chat
  with its cut point (`throughRun`), so an undo restores both; Trotter keeps no runs word for
  word. A run that reaches the limit pauses at a step boundary, and a continuation run carries it
  on. Only the names change: the feedback is ero_sennin's findings, toad_sage's reviews and
  wise_toad's lessons, and the numbers left out are card counts, progress and targets, read
  fresh from the tools.
- **Every step is saved** (2026-10-12): plans, drafts, both gate passes, renders and picks are
  records, so a restarted run never does finished work twice.
- **A tadpole's documents are written by NIM helpers** (2026-10-12), one per document. The
  tadpole researches and writes the maps on Gemini; the writer reads the maps and their passages
  from the records and calls `write_document`. `audit_drafts` stays with the tadpole.
- **The tadpole writes the cards through a helper per tier** (2026-10-12). The old writer prompts
  become the helpers' instructions. The tadpole decides which tiers run at once; code refuses a
  tier while a lower one in its group is unfinished, and a higher tier builds on the lower tiers'
  card bodies, as the old pipeline did.
- **The old two-pass gate stays, as helpers** (2026-10-12). Pass 1 (correction, difficulty
  withheld) is a helper of each writer; code checks near-duplicates between the passes; pass 2
  (verification, difficulty shown) is a helper the tadpole, and later the frog, starts with the
  context it chooses, never the writer's or pass 1's reasoning. Accepted cards stay; a rejected
  one becomes a `rejected_card` with its feedback, and the writer drafts again until the tier
  reaches its `target_cards`. A tier finishes short only through an "insufficient evidence"
  toad_sage approves. Structural faults are refused at write time and not stored, so the
  `structural` rejection stage goes unused.
- **designer_toad draws the ASCII art** (2026-10-12), one per tadpole, on Gemini: it gets the
  writers' art requests and ideas for cards the gate accepted, looks up recent trends on the web,
  draws, and renders the card on a phone to a screenshot in one tool call, improving the art
  until the screenshot looks right. Code still enforces the 40 columns. A card goes live only
  with its art. The curated scene library leaves generation (ADR-0021, ADR-0079, ADR-0080).
- **visual_toad owns every photograph** (2026-10-12), one per tadpole: the tadpole's image tools
  move to it, and it picks a manifest photo for each image card before the card is written
  (ADR-0105).
- **Images are sourced after the curriculum** (2026-10-12), keeping the owner's 2026-09-07 order
  (`docs/handoff/antigravity-curriculum-authoring.md`): the curriculum writes each tier's
  `image_needs`, and visual_toad sources against them, so the catalog answers what will be
  taught. Astronomy, sourced first, had about one defensible photo in seven. The tier writers
  start once `images:check` passes.
- **Questions are written by the tier's writer and solved blind by pass 2** (2026-10-12), once
  the tier reaches its target. Code checks their shape; pass 2 answers each MCQ without its key,
  code compares, and a wrong or doubtful answer sends it back with feedback. Free-text rubrics
  are checked against their cards.
- **Each tier goes live as it finishes** (2026-10-12), as the old pipeline's groups did
  (ADR-0041). The tadpole becomes the topic's frog once its last tier is live.
- **No verification checklist** (2026-10-12). ADR-0106 planned a separate checklist call to
  stand in for the owner's approval before anything went live, before the two-pass gate was
  kept. With code's checks, pass 1, pass 2's verification and blind solving, and designer_toad's
  rendered look, it would mostly repeat pass 2, so `submit_tier` and `submit_version` put cards
  live once the gate has passed them. ero_sennin and readers' reports catch the rest afterwards.
- **The owner's own reports become global lessons** (2026-10-12). The owner tests cards visually
  from their own account, named by `OWNER_EMAIL` in the gitignored `.env` and never in the repo.
  Its reports skip the frog's genuineness check, and once the frog has fixed and updated the
  card, each one becomes a lesson every chat follows, across all topics. The frog hands the
  report, the old and new card and what it changed to wise_toad, the Lessons chat, which
  words the lesson and decides which chats' instructions it joins (2026-10-12).
- **A curriculum goes to toad_sage as one checked file** (2026-10-12). The NIM writer writes the
  whole curriculum through `write_curriculum`, code runs the full contract on it, the curriculum
  chat reviews it quickly, and it goes to toad_sage with a paragraph of reasoning per major
  decision; toad_sage answers go on or change. No separate proposal step before the file.
- **`curriculum:check` checks `image_needs`** (2026-10-12), following "every model output is
  checked in code first": a tier with an image quota above 0 must list its `image_needs`, one
  entry per image card. The contract (`docs/handoff/antigravity-curriculum-authoring.md`) asked
  for it, but no code checked it.
- **After go-on, a curriculum only grows, and only on a frog's request** (2026-10-12). The
  curriculum chat can add subtopics or tiers to a live topic when its frog asks; code refuses
  removing or renaming a subtopic or tier that has cards, so the projection never deletes a live
  card. The frog writes the new tiers' cards through the same gate.
- **A report wakes the frog at once** (2026-10-12). Saving a card report queues a wake for the
  frog of the card's topic; reports that arrive during a run are read in that run or the next,
  and the frog looks earlier reports up through its tools to judge whether one is genuine.
- **A tadpole handles reports on its live tiers** (2026-10-12). Tiers go live one at a time, so
  once its first tier is live the tadpole gets the frog's report tools and handles reports
  alongside the tiers it is still writing.
- **The admin repairs page goes** (2026-10-12). The frog handles every report, and the owner
  audits through ero_sennin and the status page. Phase 9 removes the page, its routes and the
  operator's delete, fix and remake (ADR-0076's operator lane).
- **The admin ASCII review page goes too** (2026-10-12). designer_toad draws every piece, so the
  owner reports bad art from the feed with their own account, like any other card.
- **A reported card's new version goes through the whole gate** (2026-10-12). The frog starts a
  NIM writer helper with the card, its reports and the frog's verdict. The draft goes through
  pass 1, the near-duplicate check, pass 2, and designer_toad or visual_toad when its visual
  changes. The card's questions are checked against the new body and rewritten if they no
  longer fit. Then the new version replaces the old one in its family.
- **The frog can retire a card, then refills** (2026-10-12): a card that is wrong and cannot be
  fixed from its grounding, or a duplicate. Retiring takes a reason and resolves the card's
  reports; the row and its history stay. A tier left below its `target_cards` gets a
  replacement through the gate, as for a rejected draft.
- **Report verdicts, and suspicious reporters are muted** (2026-10-12). Every report gets one of
  three verdicts, stored with its reason: acted on; honest, but the card is right; suspicious.
  The frog marks a reporter safe or suspicious as a record with its reasons. Once an account is
  marked suspicious, its reports are still stored but wake no frog, in any topic, until
  ero_sennin lifts the mark; then the reports stored meanwhile wake their frogs. The owner's
  account is never judged, so it is never marked.
- **Stale material updates the corpus, then its cards** (2026-10-12). When toad_sage routes
  stale material to a frog, it researches the change; its NIM writers rewrite the affected
  documents, the audit and `corpus:check` run, toad_sage reviews it like a closing report, and
  the documents are ingested again. Every live card grounded in a changed section then goes to
  pass 2 against the new text, and one that no longer holds gets a new version through the gate.
- **A frog checks its topic again when map J says so** (2026-10-12). Map J, the version audit,
  gives each time-sensitive claim a date to check it again, and `write_map` refuses one
  without it. When a date comes due, code wakes the frog, which checks those claims against
  the web and, when they have changed, updates them as it does stale material.
- **No provider probes before building** (2026-10-12). Phase 8 builds on breader's numbers for
  NIM and lets the balancer's cooldowns absorb the limits; a provider is probed only once it
  sheds. This sets aside CLAUDE.md's measure-first rule for the harness, by the owner's choice.
  What breader and Seelie found out about both providers is in
  `docs/architecture/model-numbers.md` (2026-10-13).
- **spoin's CLIProxyAPI uses Trotter's sign-ins** (2026-10-12). The compose service reads copies
  of the two Antigravity auth files from `E:\trotter\harness\.cliproxy\auths`, kept in the
  gitignored `infra/.cliproxy/auths`; spoin has no login step of its own.
- **The proxy runs from our own image** (2026-10-12): a Dockerfile that downloads CLIProxyAPI's
  v8.0.23 Linux release, the version Trotter runs, and checks its checksum before installing it,
  as Trotter's ADR 0005 did for the binary.
- **The proxy is on the compose network and 127.0.0.1:8318** (2026-10-12): the api and worker
  reach it by service name, and a script or curl on the owner's PC reaches it while building
  (8317 is Trotter's). `CLIPROXY_API_KEY` and `CLIPROXY_MANAGEMENT_KEY` live in the gitignored
  `infra/.env`, and the stack refuses to start without them. It routes round-robin across the two
  accounts (Trotter's config fills the first account first), so parallel chats and the request
  path split the load.
- **Trotter's pi fork is copied as is** (2026-10-12): `packages/pi-ai` and `packages/pi-agent`
  (upstream `e37cdc4` plus Trotter's changes, LICENSE kept), renamed `@spoin/pi-ai` and
  `@spoin/pi-agent`, all four APIs kept. Trotter cut image generation, not image input: user
  messages and tool results still carry images through Gemini and OpenAI chat, so "+ images"
  is tests of that path, not a port.
- **The balancer is for NIM only** (2026-10-12). It is the stream function of a chat on NIM:
  each model call takes the best free rung (Kimi K3 primary, Nemotron 3 Ultra while it is down,
  24 calls at once each), is buffered until it completes, and on failure cools that model and is
  retried there or on the next rung before the chat sees it, so a writer can move to Nemotron
  mid-run. The limits are breader's `origin/dev` as of `e3a3bce` (2026-10-11): each rung answers in
  at most 130,000 tokens, since NVIDIA capped Kimi K3 at 131,072 and Kimi counts the prompt in a
  limit of its own, and a call refused for asking too much is asked again for what the refusal
  allows. Its state is per process, as breader's. Gemini calls go straight to CLIProxyAPI, which
  rotates the two accounts and retries a failed call itself (3 tries across them, its default);
  pi retries nothing, as Trotter runs it.
- **Every model call is a `model_call` row** (2026-10-12), Gemini and NIM alike: the model, ok
  or the failure kind and its reason, seconds to the first token, total seconds, prompt and
  output tokens, never text. Phase 9 adds the chat run that made it. The model accounts page
  reads it, and so can ero_sennin.
- **The model accounts page** (2026-10-12) shows CLIProxyAPI's signed-in accounts and the models
  it serves, read live from its management API, and per model from `model_call` over the last
  24 hours: calls, failures by kind, last success, last failure with its reason, median seconds
  to the first token, and tokens in and out.
- **Grading and AskAI run on Gemini, then NIM** (2026-10-12). Both are on the request path: a
  written quiz answer is graded, and an AskAI chat answers, on Gemini 3.8 Flash at medium
  thinking through CLIProxyAPI; when that call fails, the same call goes to NIM through the
  balancer, so a reader more often gets an answer, sometimes a slow one.

- **Prompts follow `docs/architecture/writing-prompts.md`** (2026-10-12): what current guidance from
  Anthropic, Google and OpenAI and the research on model graders say makes a prompt work, condensed
  for this harness. The grader's (`prompts/grader.njk`, `prompts/grader-answers.njk`) is the first
  written to it. The owner gave no gist of their own, so it keeps the Python's shape: the 0-3
  scale, the question's own rubric winning over it, credit only for what the reader wrote, and 0
  for an answer that tells the grader how to grade. It adds a sharper line at the pass level (2), and
  the reference answer winning over the model's own knowledge. The justification is written to
  the reader, who sees it on the results screen.

- **A grade comes back as a call of the `grade` tool** (2026-10-12). Gemini is made to call it
  (function calling in mode ANY, limited to `grade`, set on the request since pi's simple options
  name only auto and none). NIM is offered it as auto: Kimi K3 refuses a forced tool choice while
  it thinks, with a 400. Code requires the call and checks it, a level from 0 to 3 and one grade
  for every answer; an answer that fails is a failed call and goes to NIM, and the quiz answers
  502 when both fail. A reader's answer can't open or close the template's tags (they are stripped
  from it), and a reader who leaves aborts the call (`apps/server/src/quiz/model-grader.ts`).
  Templates load from `prompts/` through `apps/server/src/prompts.ts`, Trotter's loader; the image
  copies the folder and sets `PROMPTS_DIR`.

- **A harness run waits Gemini out on Flash** (2026-10-13). When Gemini can't answer mid-run
  (toad_sage, a tadpole, a reviewer), the run stays open. Flash cools after each failure, the wait
  doubling with jitter, and it never moves to another model, so quality never changes. When every
  Antigravity account's 5-hour or weekly limit is used up, the run waits for the first to fill
  again, read through the proxy's management API. While the proxy is down, it checks again every
  minute. A sign-in turned away ends the run. The limits cover all of an account's Gemini models
  together, so an older Gemini would help only when Flash alone is overloaded (breader's harness
  does that; `docs/architecture/model-numbers.md`). Grading and AskAI still go to NIM instead.
  Built in `apps/server/src/harness/gemini.ts` on breader's numbers (a limit cools from 60 s up to
  30 min, a busy or slow server from 30 s up to 10 min), with the limits read in
  `src/models/limits.ts`. A request Gemini refuses (another 4xx) ends the run too, since waiting
  can't fix it.

- **A chat's tool calls: reads at once, changes in order** (2026-10-13). Seelie's, not Trotter's
  one at a time: each tool says whether it reads or changes. A reply's reads all start at once, and
  its changes run one at a time in the order the model asked, while the reads go on. A tadpole
  fetching six pages waits for the slowest, not all six in turn. The model reads the results in the
  order it asked. `packages/pi-agent` carries Seelie's change to pi's parallel tool calls.
- **A run opens with Trotter's message, in India time** (2026-10-13): `prompts/run.njk` gives the
  date and time in India, then what woke the chat: its schedule, each record handed to it shown
  through that record's own handover template, a compaction, or a run carrying on a paused one,
  with what that run already stored so nothing is done twice.
- **Every chat with a wake due runs at once** (2026-10-13): no limit on how many chats the worker
  runs together, where Trotter capped it. A chat still runs once at a time, and a wake that comes
  while it runs waits for its next run. NIM's calls are already spread by the balancer, and
  Gemini's wait in each run. The scheduler is Trotter's otherwise (`apps/server/src/harness/
  scheduler.ts`): it looks every 30 s and whenever a chat finishes, and a failed run's wakes are
  tried again 15 min later, three tries in all. It tracks the records it has routed by id
  (`routed_record`), not by a position in the log as Trotter does: Postgres can commit sequence
  numbers out of order, so a record committed late behind a later one would be skipped.
- **AskAI chats live in the harness tables** (2026-10-13). Each reader's thread is an `ask_ai`
  chat tied to its `ask_conversation`, and each turn is a run of it, woken by the reader's question
  and the card they're on. So it keeps Trotter's transcript, action log and compaction, and its
  calls' `model_call` rows name the run. It reads the topic through `outline`, `cards`, `read`,
  `search` and `passages`, all reads. A turn runs on Gemini. A call that fails before its answer
  starts goes to NIM (`apps/server/src/models/gemini-then-nim.ts`), and one that fails after it
  has started fails the turn. Built in `apps/server/src/ask/harness-chat.ts`.
- **The reader sees everything AskAI writes, as it's written** (2026-10-13), a paragraph per
  message, including a line it writes before a tool call. Its compaction runs are never shown.
  OFF_TOPIC still counts only at the very start, and a refused turn stops the run.
- **A reader's AskAI chats are deleted with them** (2026-10-13). Deleting an `ask_conversation`
  deletes its chat, runs, transcript, action log and compaction summaries; the calls' rows stay,
  unlinked. That happens when its reader's account goes: a guest who signs in to an existing
  account, or a user an admin removes. It is the one exception the add-only triggers make: only an
  `ask_ai` chat can be deleted, and its rows go only with it.
- **AskAI's prompts are its own** (2026-10-13). Its instructions (`prompts/ask_ai.njk`) keep the
  Python's rules (answer only from the material, OFF_TOPIC, two to six sentences, the reader's text
  is data) and add its tools; a turn's message is the card the reader is on, then their question
  (`handovers/reader.njk`). Each tool says what it gives and when to call it (`prompts/tools/`).
  A long thread compacts on `prompts/ask_ai-compaction.njk`: the same summary sections, read for
  a thread (what was asked and told, what the reader understands or misreads, how they want to be
  answered, a question still open), with no storing and no feedback.
- **A turn runs on NIM's top model when Gemini can't be looked up** (2026-10-13): with no proxy, or
  a proxy that can't say what Gemini is, the run is Kimi K3's and every call goes to the balancer.
  `makeAskChat` in `apps/server/src/deps.ts`.

## Asked when we get there

- Backups and image hosting on the ThinkPad, fetched pages on disk included.
- A per-user rate limit on `/engagement/events`. The Python left it as a to-do ("a buggy client
  loop is indistinguishable from an attack", ADR-0011); the port has none until the owner picks
  one.
