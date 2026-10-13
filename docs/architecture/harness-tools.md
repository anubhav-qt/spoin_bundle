# The harness's tools

Every tool each chat of the authoring harness gets ([ADR-0106](../adr/0106-typescript-on-hono-and-the-authoring-harness.md),
task 0045). Designed with the owner one chat at a time before Phase 8, so the pi fork's tool
wrapper is built knowing all of them; the reasoning behind each choice is in task 0045's
"Decided during the port".

Five rules hold for every chat and tool. **Every output is checked in code first**: whatever a
model returns (tool arguments, a draft, a verdict, a report) is validated by code as soon as it
is generated, before anything acts on it, and a rejection always carries its reason. **Tool
errors teach**: a wrong call throws `ToolError`, one short line on what was wrong and how to call
it right. **Records live in Postgres**: whatever a tool writes is a versioned record or a row
checked in code, never something an agent only remembers. **Every step is saved**: plans,
drafts, both gate passes, renders and picks are records, so a run that restarts picks up from
them and never does finished work twice. **Prompts live in `prompts/`**: every system
instruction and prompt is a Nunjucks template in its own `prompts/` directory, never a string
in the code.

## Models

| Chat | Model |
|---|---|
| toad_sage, every chat (the writers' included), research, the gate's two passes, designer_toad, visual_toad | Gemini 3.8 Flash, medium thinking, through CLIProxyAPI |
| The writers' big writes, one call each: a corpus document, a curriculum, a tier's cards, a tier's questions | NIM, on breader's ladder: Kimi K3 (high reasoning) as primary, Nemotron 3 Ultra only while it is down, with breader's cooldowns per failure kind, doubling with each failure in a row, jittered waits, and empty answers and refusals asked again. The worker doesn't start without a NIM key; a call goes to Gemini only once NIM gives up on it: 12 tries spent, no model left to ask, or no answer within 30 minutes |

## Running it

The worker (`apps/server/src/worker.ts`, the compose `worker` service) runs the scheduler, and
`apps/server/src/agents/set-up.ts` gives each chat its tools and model when it wakes. The tools
live in `apps/server/src/agents/` and `apps/server/src/harness/`. `npm run monitor -w
@spoin/server` serves a live page of every chat at http://localhost:4040, read only.

## Every chat

As in Trotter, every chat but AskAI, which ADR-0106 gives no database handle. Nor do they see
AskAI, which is for its readers alone: the reads leave out its compaction summaries, the only
records it writes, and read one by id as a record that isn't there. A helper gets only
the three reads: it has no address to be asked at, and it asks nothing, leaving what it can't
settle to its report. Each record reads as its own template shows it, with who wrote it, by role
and topic, and when, in India time.

| Tool | Does |
|---|---|
| `read_record(id, version?)` | One record: the latest version, or the version named. The kind is looked up from the id |
| `read_record_history(id)` | Every version of one record, oldest first |
| `list_records(kind, status?)` | A line for the latest version of each record of a kind: its ref, status, writer, time and the start of its text, from the kind's template in `prompts/lines/`. The chat reads the ones that matter |
| `ask(to, topic?, question, reasoning)` | A question to any chat that exists, never itself: toad_sage, curriculum, ero_sennin and wise_toad are made on first need, and a topic's tadpole, designer_toad or visual_toad is asked only once it has started. Wakes the chat asked |
| `answer(question, answer)` | Only from the chat asked. A chat can answer again once it knows more; each answer is its own record and wakes the asker |
| `write_summary(...)` | In a compaction run only, the chat's summary under 2,000 tokens, exactly as Trotter's (task 0045) |

## toad_sage

The manager. One chat, the orchestrator, running a helper per task in parallel. Every queued
name wakes it at once, with its generate job.

### Intake, one per queued name

A topic is a **subject plus an angle**: who it is for and how it is written ("plain language
for newcomers", or none). "Rust" and "Rust in easy language" are two topics, and Rust the game
is never Rust the language. The reader's optional description says what they want from the
topic, and toad_sage reads it with the name. A name that matches an existing alias exactly
reaches toad_sage too when it comes with a description, so a description that doesn't fit the
existing topic gets its own.

| Tool | Does |
|---|---|
| `find_topics_by_name(name)` | The 5 topics nearest a name by `pg_trgm` similarity against every alias, live or queued, rejected ones left out. Each shows where it stands (with its job), its intake's name, subject and angle if taken in, its aliases, its requester's description, and the name match. Never runs the embedder, so toad_sage tries it first |
| `find_topics_by_meaning(subject, angle?)` | The 5 topics taken in whose meaning (subject, angle and description, embedded at intake) is nearest toad_sage's own statement of the subject and angle, shown as above with the meaning match. Runs the embedder, so toad_sage calls it only when the name leaves the question open |
| `read_topic(topic)` | One topic: where it stands, how many readers asked for it, its aliases and description, its intake record, its links both ways, and its subtopics per tier with their live card counts |
| `list_categories()` | The categories and sub-categories in use, with counts |
| `web_search(query)` | Whether a name is a real subject: Gemini's Google Search, in a call of its own, giving Gemini's account of what the results say and its sources (title and real URL) |
| `reject_topic(job, reason)` | Fails the job; the reason is what the reader sees |
| `merge_topic(job, into, subject, angle?, into_subject, into_angle?, reasoning)` | Into a live or a queued topic: the subscriptions and alias move, and the placeholder goes with its job. toad_sage states both topics' subject and angle; the merge record keeps the requested name, description, requesters and the job's priority, so ero_sennin can check it and undo it |
| `accept_topic(job, name, subject, angle, scope, category, sub_category?, card_count, brief, builds_on?)` | The name is the full name ("Rust in easy language") and makes the slug; the subject is what it is about, disambiguated ("Rust, the programming language"), so two topics on one subject state the same subject. The slug is made and the category normalized by code; writes the topic row and the intake record. The topic then waits in the queue: its tadpole starts when the topics ahead of it are written (task 0045). `builds_on` names the topics sharing its subject, whose corpus and fetched pages the tadpole reuses before it searches the web |
| `change_intake(topic, reason, subject, angle?, scope, category, sub_category?, card_count, brief, builds_on?)` | Corrects the subject, angle, scope, category, card count, brief or `builds_on` before the topic goes live, the whole intake restated: its next version, and the topic row updated. The name stays as accepted |

### Reviews

toad_sage plays the owner's part at the procedure's approval points: the coverage note, the
curriculum proposal, every "insufficient evidence" and the closing report.

| Tool | Does |
|---|---|
| `search_corpus(query)` | Any corpus section, to check what a note says is already covered |
| `review(record, go_on \| change, notes)` | Answers a handover; the verdict wakes the chat that sent it |

### Links and spin-outs

| Tool | Does |
|---|---|
| `link_topics(from, to, deep_dive \| related)` | Refuses a link to itself and one that exists either way |
| `unlink_topics(from, to, kind)` | Removes a wrong link |
| `spin_out(survey, name, description)` | Queues a topic the survey introduces at priority 0, with a `deep_dive` edge from the survey |

### Helpers

| Tool | Does |
|---|---|
| `start_helper(task, brief)` | A short-lived helper for one task, with every tool above but this one |
| `report(summary)` | The helper's last call: the record its main chat reads. A helper that works alone (a plain helper, a document or curriculum writer) and ends a run without it is woken again on its brief; after three runs, or a given-up wake, code reports for it, so the main chat never waits for good |

## A topic's tadpole: research, corpus, report

The one author of its topic, running helpers for parallel work. Its run follows
[ADR-0100](../adr/0100-the-universe-is-a-claim-qualified-knowledge-system.md) in full: maps
before prose, labelled claims, auditors who are not the author. Its cards and questions come
after the curriculum, as their own set.

### Research

The tadpole looks in what is already stored before it goes to the web: a topic that shares its
subject with one already written reshapes that material to what its request asks. A fetched
page's content stays on disk; Postgres keeps its pointer, and pgvector its passages' embeddings.

| Tool | Does |
|---|---|
| `search_pages(query)` | The pages already fetched, by meaning |
| `search_corpus(query)` | Corpus sections, by meaning |
| `read_document(path)` | A corpus document in full |
| `list_documents(category?, topic?)` | What the corpus holds |
| `web_search(query)` | As toad_sage's: Gemini's Google Search |
| `fetch(url, fresh?)` | Plain HTTP, then a headless Chromium for a page with no real text; public pages only, robots.txt ignored, paced per site. Stores the page, and returns it as numbered passages; a stored page comes from disk unless `fresh`, and a long one says how to read the rest |
| `read_page(page, from_passage)` | The rest of a long page |

### Maps and handovers

| Tool | Does |
|---|---|
| `write_map(kind, body)` | One of ADR-0100's maps, A to J, as a versioned record with its own schema. Claims carry class, scope and confidence; evidence cites stored page passages, each checked to exist |
| `change_map(map, reason, body)` | The map's next version |
| `hand_over(kind, records)` | The coverage note, the maps, an "insufficient evidence" or the closing report, to toad_sage. The run ends until its review wakes the tadpole. The closing report is refused until the latest drafts are audited, every finding is fixed or answered, `corpus:check` passes, and the documents hold at least one section for every 3 of the intake's cards (a tier of 5 to 25 cards is written from 5 to 10 sections) |

### Documents

A tadpole writes only its own topic's documents, each one through a writer helper whose write is one NIM call.
Stale material it notices elsewhere goes in its closing report, and toad_sage routes it to that
topic's frog. Drafts are ingested only once toad_sage says go on to the closing report, so no
other topic retrieves them before; the curriculum chat starts after ingestion.

| Tool | Does |
|---|---|
| `start_writer(path, brief, sections)` | A writer helper for one document, with the research tools, `write_document` and `report`. It reads the maps and their cited passages from the records. `sections` (3 to 30) is how many the document has whole, and `write_document` refuses it with fewer: the first Rust run's tadpole, only told the corpus's size, wrote 56 sections for 700 cards |
| `write_document(path, title, source, source_date, tags, epistemic fields, sections)` | The writer's. Code copies kind, category, sub-category and scope from the topic row, checks the corpus contract at write time naming every problem at once, writes the file and keeps the previous version as a record. Every call's sections are kept as the writer's try, and a document already written is the starting try, so each later call, a rewrite included, sends only the sections that change (`drop` removes one) |
| `audit_drafts()` | The three auditing calls (versions, false precision, the coverage matrix) with their own fixed prompts, which the tadpole does not brief. Findings are records |

The topic's photographs are visual_toad's, sourced after the curriculum (below).

### Helpers

`start_helper(task, brief)` and `report(summary)`, as toad_sage's.

## The curriculum chat

One chat for every topic, the orchestrator, running a Gemini writer helper per topic. A topic's
curriculum starts once its corpus is ingested and follows
`docs/handoff/antigravity-curriculum-authoring.md`. It goes to toad_sage as one checked file;
after go-on it only grows, and only when the topic's frog asks.

### The curriculum chat (Gemini)

| Tool | Does |
|---|---|
| `list_waiting()` | Oldest first: topics whose corpus is ingested but have no curriculum, and frogs' requests for additions |
| `start_writer(topic, brief)` | A writer helper for one topic's curriculum or addition |
| `read_curriculum(topic)` | A topic's curriculum, its versions, toad_sage's notes on each, and each tier's card counts |
| `send_back(record, notes)` | After the quick review, wakes the writer with what to change |
| `hand_over("curriculum", record, reasoning)` | To toad_sage, with a paragraph of reasoning per major decision. On go-on, code writes the file, ingests it, projects it onto the subtopics, and wakes the topic's tadpole (or frog) so visual_toad's sourcing starts |

### A topic's curriculum writer (Gemini)

| Tool | Does |
|---|---|
| `read_intake(topic)` | toad_sage's intake: scope, angle, card count, brief, `builds_on` |
| `list_documents`, `read_document`, `search_corpus` | The topic's ingested corpus. `read_document` shows the exact `##` headings a grounding anchor must name |
| `read_curriculum(topic)` | For an addition: what exists already |
| `write_curriculum(topic, curriculum, reasoning)` | Stores a version as a record. Code runs the whole contract at once and names every problem (below) |
| `report(summary)` | The helper's last call |

`write_curriculum` checks that the `scope` matches the topic's and its corpus documents'; the
prerequisites form a DAG; every `target_cards` is 5 to 25; every tier's quotas are the card mix
below, with image 0 until photographs are sourced; a survey or a one-shot gives each subtopic
only `beginner`; every tier has 5 to 10 grounding anchors, each an exact existing heading. Past go-on, any
change to an existing subtopic or tier is refused, so only additions get through.

## A topic's tadpole: cards and questions

After the curriculum is projected onto the topic's subtopics, code runs the tiers (task 0045),
and the tadpole watches and hands over what code can't settle:

1. On publish, code starts a writer helper for every tier whose lower tiers in its group have
   their cards live, and starts the tiers above each one as its cards go live.
2. The writer's `write_cards` sends the drafts that pass to the tier's pass-1 helper, made with
   its first drafts. When pass 1 has nothing left to correct, code starts a pass-2 verifier on
   the survivors with a brief of its own, so the verifier reads none of the writer's or pass 1's
   reasoning.
3. designer_toad draws the art on every accepted card that asked for it, in batches. Once no
   accepted card is waiting for art, on the last verdict or the last piece of art, the tier's
   accepted cards go live together.
4. Only then is the writer briefed to write the tier's questions: the topic's budget of its card
   target clamped to 200 to 300 (the old pipeline's `persistence.py`), shared among its tiers by
   their targets, one free text and the rest four-option MCQs, each from one card. Each question
   goes live as it passes pass 2.
5. The job completes when every tier's cards and quiz are live; code then makes the tadpole the
   topic's frog.

A survey or a one-shot has no tiers (ADR-0106): each subtopic has one, and its cards keep the
difficulty pass 2 reads them at, easy to advanced.

### The card mix

Every tier has the same mix (the owner, 2026-10-13, ADR-0107), its numbers each type's share of
the target, rounded so they sum to it:

| Type | Share | What it is |
|---|---|---|
| ascii | 50% | A card carrying ASCII art: 30% of the tier a gag, 20% a small informative drawing |
| diagram | 20% | A mermaid flowchart, always black on white: no styling, colour or emoji |
| prose | 20% | Words. On a code subject any part of it may be code cards instead |
| comparison | 10% | Myth against fact |

Only the ascii cards carry art, so the other half of a tier waits for no drawing. A card can hold
more than its form needs, and still counts as its form: on a code subject an ascii card with a
code block is an ascii card. No photographs until they are sourced, so visual_toad and
`request_photos` are not wired in.

### The tadpole

| Tool | Does |
|---|---|
| `list_subtopics()` | Every group and tier: target, grounding, its writer, and progress (in the gate, accepted, with art, live, rejected; questions live against their target) |
| `hand_over("insufficient_evidence", records)` | A tier that cannot reach its target from its grounding, to toad_sage. The only way a tier finishes short |

### A tier's writer helper

The writer's chat runs on Gemini; its two big writes are NIM's (ADR-0108). It calls
`write_on_nim(tool, instructions)` with `write_cards` or `write_questions`, and the tool hands
NIM the writer's whole chat with the instructions, so NIM writes a whole tier's cards, or its
whole quiz, in one call, at most a tier (the owner's cap). NIM answers with the tool's arguments
as JSON text, and code stores them through the real tool, whose checks decide what passes. The
result shows what NIM wrote and what was stored or refused. A tier's first cards and first
questions are NIM's alone: the writer's own `write_cards` and `write_questions` refuse until the
tier has some (the owner's rule), and after that the writer makes corrections with them itself,
since NIM takes some five minutes to start any answer. The balancer retries a call across NIM's
ladder and Gemini takes one NIM gives up on; an unusable answer goes back to the writer. The
document writer writes the same way; the curriculum writer writes on Gemini alone (the owner's
call).

| Tool | Does |
|---|---|
| `read_grounding(subtopic)` | The tier's grounding sections, as numbered passages |
| `read_cards(subtopic)` | The tier's cards so far, the lower tiers' card bodies to build on, and the topic's titles |
| `plan_cards(subtopic, briefs[])` | The tier's plan (ADR-0059): concept, form and angle per card, as a record |
| `write_cards(subtopic, cards[])` | Drafts, sent to pass 1 as they are stored: dual titles, summary, body, cited passages, form, an art request on an ascii card (gag or informative, what to show, and ideas), hero. Code refuses a structural fault and names it (lengths, prose over 1,200 characters, a code block in a topic with no code cards, mermaid and its emoji or styling, a diagram card that isn't a flowchart, an ascii card without an art request, a correction note in the body, a passage outside the grounding, the type and art quotas). An art request on any other card is dropped. Each draft stands alone: the passing ones are stored and only the faulty ones come back to be written again. Embeds the drafts and derives their archetype |
| `write_questions(subtopic, questions[])` | Refused until the tier's cards are live. Code checks the shape (four distinct options, a correct index in range, a rubric for free text), that the card is live in this tier, the tier's question target, one free-text question, and near-duplicate stems; the passing questions go to a pass-2 verifier and only the faulty ones come back |

### Pass 1: correction (one helper per writer)

The old gate's first pass (ADR-0030) with its own fixed instructions, which the writer does not
brief. The corrector's chat runs on Gemini, and NIM writes each draft's first correction
(ADR-0108, the owner's rule): the corrector calls `write_on_nim` with `correct_cards` for all the
waiting drafts, and its own `correct_cards` refuses a draft until NIM has written its entry,
stored or refused. After that the corrector fixes what code refused itself.

| Tool | Does |
|---|---|
| `read_drafts()` | The waiting drafts, with their passages and the canonical topic. Difficulty withheld |
| `write_on_nim(tool, instructions)` | NIM writes `correct_cards` for the waiting drafts from the corrector's chat; code marks each draft it names as tried, then stores the entries through `correct_cards` |
| `correct_cards(cards[])` | Rewrites a card, or returns it unchanged; never rejects. The corrector's own copy refuses a draft NIM hasn't tried. Code checks the structure again, embeds the corrected body, and rejects a near-duplicate of the topic's cards or an earlier one in the batch, naming its twin. The passing corrections are stored and only the refused ones come back |

### Pass 2: verification (a helper of the tadpole, later of the frog)

| Tool | Does |
|---|---|
| `read_survivors()` | The cards past pass 1, with their passages and requested difficulty |
| `verify_cards(verdicts[])` | Per card: the difficulty it reads as, accept, and feedback. A rejection is a `rejected_card` with that feedback |
| `solve_questions(answers[])` | Each MCQ without its key; code compares the answer with the key, and a wrong or doubtful one is a rejection with feedback |
| `check_rubrics(verdicts[])` | Each free-text rubric against its card |

### designer_toad (one per tadpole)

Draws every ASCII art itself, for the ascii cards the gate accepted, replacing the curated scene
library (ADR-0021, ADR-0079, ADR-0080). Each piece is the kind its card asked for (ADR-0107): a gag
or an informative drawing, on Gemini, in batches of up to 10. The art carries the idea, drawn as
scenes and objects more than faces and stick figures, and its text is labels of 1 to 3 words, plus
a gag's one line of dialogue; code caps each piece's words, letters and box lines (ADR-0109). For a
meme or a famous character it searches the web and looks at a reference picture before drawing. A
tier's cards go live once every accepted card that asked for art has it. Art of an older style
(`ART_STYLE`) is drawn again, live cards' too, after the cards waiting for their first. Each
screenshot is shown to the model once, in the call after the render or the look.

| Tool | Does |
|---|---|
| `list_art_requests()` | The next 10 cards waiting for art, first art before redraws, with the writer's request: its kind, what to show, and ideas; and how many more wait |
| `web_search`, `fetch` | Memes, characters and their lines, and references for a subject it can't picture |
| `look_at(url)` | A public page or picture in headless Chromium at a laptop's width, returned as one screenshot: a meme's picture or a character's look to draw from |
| `render_art(art[])` | Up to 10 pieces, each a card, its art and its caption: checks the 40 columns (any height), the character set, the text and the boxes (a gag at most 12 words, 30% letters and 40% box lines, an informative drawing 20, 40% and 45%), refuses rows of `#` standing in for text, then renders each card on a phone and returns the screenshots. A piece that fails is refused alone. Every render is a record |
| `attach_art(art[])` | Up to 10 pieces, each refused unless this run rendered that exact art; marks each card's art the current style. Puts a tier's cards live once no accepted card is waiting for art |

### visual_toad (one per tadpole)

Owns every photograph. Once the curriculum is in, it sources the topic's manifest against each
tier's `image_needs` (what a camera would capture), ending when `images:check` passes; then it
picks one for each image card before the card is written (ADR-0105).

| Tool | Does |
|---|---|
| `web_search`, `fetch` | As the tadpole's |
| `view_image(url)` | Downloads and stores the image, and shows it to the model |
| `add_image(image, licence, licence_url, author, description, …)` | An entry in the topic's image manifest. Refuses a licence outside the allowlist and an image this run has not viewed |
| `remove_image(image)` | Takes an entry out |
| `list_photo_requests()` | Image briefs waiting for a photo |
| `find_images(query)` | Manifest photos not yet used in the topic, by meaning |
| `pick_photo(request, image \| none, note)` | Refuses a photo already used in the topic or not viewed in this run |

## A topic's frog

The topic's tadpole once its last tier is live: the same chat, keeping every tadpole tool
(research, maps, document writers, `audit_drafts`, designer_toad and visual_toad), with code
starting an added tier's writer and gate as it does the first ones. A report wakes it at once, and a tadpole
gets the report tools as soon as its first tier is live. toad_sage's routed stale material and
map J's due dates wake it too.

### Reports

Each report gets one verdict, stored with its reason: acted on; honest, but the card is right;
or suspicious. Reports from the owner's account (`OWNER_EMAIL`) are never judged.

| Tool | Does |
|---|---|
| `list_reports()` | Open reports on the topic's cards, oldest first. Each comes with its card, reason and note, the reporter's mark, and whether it came from the owner's account. Muted accounts' reports aren't listed |
| `read_reporter(user)` | The account's earlier reports in every topic, their verdicts, and its mark with the reasons |
| `find_similar_reports(report)` | Reports from any account and topic whose notes are close in meaning, to catch a burst |
| `judge_report(report, acted_on \| card_right \| suspicious, reason)` | Stores the verdict. `card_right` and `suspicious` resolve the report; `acted_on` stays open until the new version lands or the card is retired. The owner's account's reports can only be `acted_on` |
| `mark_reporter(user, safe \| suspicious, reasons)` | `suspicious` mutes the account in every topic until ero_sennin lifts the mark: its reports are stored but wake no frog. Refused for the owner's account |

### Changing cards

| Tool | Does |
|---|---|
| `start_rewrite(card, brief)` | A NIM writer helper for the card's next version, given the card, its reports and the verdict, with the tier writer's tools. Its `write_cards` writes only that card's family, and `submit_version(card)` replaces the old version once the gate has passed it. The draft goes through pass 1, the near-duplicate check, pass 2 and the visual helpers; its questions are checked against the new body and rewritten if they no longer fit |
| `retire_card(card, reason)` | Retires the card and resolves its reports; the row and its history stay. If the tier drops below `target_cards`, the result says so, and the frog starts the tier's writer for a replacement |

### Corpus and freshness

| Tool | Does |
|---|---|
| `list_due_claims()` | Map J's time-sensitive claims whose check date has come |
| `hand_over("corpus_update", records)` | A corpus update for toad_sage, refused on the closing report's terms. On go-on, code ingests the documents again and wakes the frog |
| `list_stale_cards()` | Live cards grounded in a section that changed since they were written. The frog sends them to a pass-2 helper, where a card that no longer holds is flagged for `start_rewrite` rather than becoming a `rejected_card` |
| `request_addition(reason)` | Asks the curriculum chat for new subtopics or tiers; the request appears in its `list_waiting` |

### Lessons

| Tool | Does |
|---|---|
| `hand_to_lessons(report)` | Sends wise_toad the report, the old and new card, and what changed. Refused unless the report came from the owner's account and its new version is live |

## ero_sennin

The Auditor, one chat on Gemini, woken as each run ends, helpers' included. It never writes
content: what it finds wrong is a finding the chat that ran fixes or answers. It undoes only a
merge, a suspicious mark and a compaction summary.

### Reading

| Tool | Does |
|---|---|
| `list_runs(chat?, since?)` | Runs by chat and time, helpers included, each with its trigger and status (Trotter's) |
| `read_run(run)` | A run's messages, and each tool call with its arguments, reasoning and result (Trotter's) |
| `search_corpus`, `read_document`, `search_pages`, `read_page` | To check a claim against the corpus or a stored page |
| `web_search`, `fetch` | To check what nothing stored covers |

### Findings

| Tool | Does |
|---|---|
| `write_finding(about, problem, summary, evidence, reasoning)` | Trotter's finding. Code checks every cited record or passage exists. It wakes the chat that ran (its main chat, once a helper has ended) and goes to wise_toad |
| `dispute(finding, reason)` | An answer ero_sennin still disagrees with: to toad_sage, or to the owner's admin list when the finding is about toad_sage's own run |

### Undo

Each undo stores its finding with it.

| Tool | Does |
|---|---|
| `undo_merge(merge, …finding)` | Recreates the topic with its requested name and description, moves the subscriptions back and puts its job back in the queue |
| `lift_mark(user, …finding)` | Unmutes the account; its stored reports that never woke a frog wake their topics' frogs now |
| `undo_summary(chat, …finding)` | Puts back the chat's earlier compaction summary with its cut point (Trotter's undo, limited to summaries) |

## wise_toad

The Lessons chat, Trotter's, one chat on Gemini. It learns from the owner's reports once fixed,
ero_sennin's findings, the owner's rulings, the gate's rejections, toad_sage's change verdicts
and readers' reports the frog acted on; the last four become lessons only when they repeat.
Each input wakes it as it arrives, except a tier's rejections, which wake it once when the tier
is submitted. A lesson takes effect as soon as it is written, for the chats it names, in the
categories it names (none: every category).

### Reading

| Tool | Does |
|---|---|
| `list_runs`, `read_run` | As ero_sennin's: the reasoning behind a rejection, a verdict or a finding |
| `search_feedback(query, kinds?, category?)` | Earlier inputs in any topic, by meaning (findings, rejections, change verdicts, acted-on reports, the owner's reports and rulings), to tell whether something repeats |
| `search_cards(query, status?)` | Cards by meaning, accepted or rejected, to check that a lesson drawn from rejections would not have turned away good accepted cards (Trotter's check against winners) |
| `list_lessons(chat?, category?, status?)` | The lessons in force and the retired ones, with their reasons |
| `list_categories()` | As toad_sage's |

### Lessons

| Tool | Does |
|---|---|
| `write_lesson(title, rule, chats, categories, evidence, reasoning)` | In force at once. Code checks every cited record exists, the chats are real roles and the categories are in use; a lesson from the owner's report applies to every category |
| `change_lesson(lesson, reason, …)` | Its next version, for a merge or an improvement |
| `retire_lesson(lesson, reason)` | Keeps the reason; refused for a lesson not in force |
