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
| toad_sage, every main chat, research, the gate's two passes, designer_toad, visual_toad | Gemini 3.8 Flash, medium thinking, through CLIProxyAPI |
| The writers: corpus documents, curricula, cards, questions | NIM, on breader's ladder: Kimi K3 (high reasoning) as primary, Nemotron 3 Ultra only while it is down, with breader's cooldowns per failure kind, doubling with each failure in a row, jittered waits, and empty answers and refusals asked again |

## Every chat

As in Trotter: `read_record`, `read_record_history` and `list_records` read any record;
`ask` and `answer` pass a question between chats; `write_summary` writes the chat's summary
in a compaction run, under 2,000 tokens, exactly as Trotter's (task 0045).

## toad_sage

The manager. One chat, the orchestrator, running a helper per task in parallel.

### Intake, one per queued name

A topic is a **subject plus an angle**: who it is for and how it is written ("plain language
for newcomers", or none). "Rust" and "Rust in easy language" are two topics, and Rust the game
is never Rust the language. The reader's optional description says what they want from the
topic, and toad_sage reads it with the name. A name that matches an existing alias exactly
reaches toad_sage too when it comes with a description, so a description that doesn't fit the
existing topic gets its own.

| Tool | Does |
|---|---|
| `find_topics(query)` | The topics nearest a name, live or queued, each with its subject, angle, description and aliases, the name match and the meaning match scored separately |
| `read_topic(topic)` | One topic: its intake record, subtopics, card counts, links, and how many readers asked for it |
| `list_categories()` | The categories and sub-categories in use, with counts |
| `web_search(query)` | Whether a name is a real subject. Decided with the research tools |
| `reject_topic(job, reason)` | Fails the job; the reason is what the reader sees |
| `merge_topic(job, into)` | Into a live or a queued topic: the subscriptions and alias move, the placeholder goes, the job completes. toad_sage states both topics' subject and angle; the merge record keeps the requested name and description, so ero_sennin can check it and undo it |
| `accept_topic(job, name, scope, category, sub_category?, angle, card_count, brief, builds_on?)` | The slug is made and the category normalized by code; writes the topic row and the intake record, and starts the topic's tadpole. `builds_on` names the topics sharing its subject, whose corpus and fetched pages the tadpole reuses before it searches the web |
| `change_intake(topic, …)` | Corrects the scope, category, angle, card count, brief or `builds_on` before the topic goes live |

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
| `report(summary)` | The helper's last call: the record its main chat reads |

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
| `web_search(query)` | Our own SearXNG |
| `fetch(url, fresh?)` | Plain HTTP, then a headless Chromium for a page with no real text; public pages only, robots.txt ignored, paced per site. Stores the page, and returns it as numbered passages; a stored page comes from disk unless `fresh`, and a long one says how to read the rest |
| `read_page(page, from_passage)` | The rest of a long page |

### Maps and handovers

| Tool | Does |
|---|---|
| `write_map(kind, body)` | One of ADR-0100's maps, A to J, as a versioned record with its own schema. Claims carry class, scope and confidence; evidence cites stored page passages, each checked to exist |
| `change_map(map, reason, body)` | The map's next version |
| `hand_over(kind, records)` | The coverage note, the maps, an "insufficient evidence" or the closing report, to toad_sage. The run ends until its review wakes the tadpole. The closing report is refused until the latest drafts are audited, every finding is fixed or answered, and `corpus:check` passes |

### Documents

A tadpole writes only its own topic's documents, each one through a writer helper on NIM.
Stale material it notices elsewhere goes in its closing report, and toad_sage routes it to that
topic's frog. Drafts are ingested only once toad_sage says go on to the closing report, so no
other topic retrieves them before; the curriculum chat starts after ingestion.

| Tool | Does |
|---|---|
| `start_writer(path, brief)` | A writer helper for one document, with the research tools, `write_document` and `report`. It reads the maps and their cited passages from the records |
| `write_document(path, title, source, source_date, tags, epistemic fields, sections)` | The writer's. Code copies kind, category, sub-category and scope from the topic row, checks the corpus contract at write time naming every problem at once, writes the file and keeps the previous version as a record |
| `audit_drafts()` | The three auditing calls (versions, false precision, the coverage matrix) with their own fixed prompts, which the tadpole does not brief. Findings are records |

The topic's photographs are visual_toad's, sourced after the curriculum (below).

### Helpers

`start_helper(task, brief)` and `report(summary)`, as toad_sage's.

## The curriculum chat

One chat for every topic, the orchestrator, running a NIM writer helper per topic. A topic's
curriculum starts once its corpus is ingested and follows
`docs/handoff/antigravity-curriculum-authoring.md`. It goes to toad_sage as one checked file;
after go-on it only grows, and only when the topic's frog asks.

### The curriculum chat (Gemini)

| Tool | Does |
|---|---|
| `list_waiting()` | Oldest first: topics whose corpus is ingested but have no curriculum, and frogs' requests for additions |
| `start_writer(topic, brief)` | A NIM writer helper for one topic's curriculum or addition |
| `read_curriculum(topic)` | A topic's curriculum, its versions, toad_sage's notes on each, and each tier's card counts |
| `send_back(record, notes)` | After the quick review, wakes the writer with what to change |
| `hand_over("curriculum", record, reasoning)` | To toad_sage, with a paragraph of reasoning per major decision. On go-on, code writes the file, ingests it, projects it onto the subtopics, and wakes the topic's tadpole (or frog) so visual_toad's sourcing starts |

### A topic's curriculum writer (NIM)

| Tool | Does |
|---|---|
| `read_intake(topic)` | toad_sage's intake: scope, angle, card count, brief, `builds_on` |
| `list_documents`, `read_document`, `search_corpus` | The topic's ingested corpus. `read_document` shows the exact `##` headings a grounding anchor must name |
| `read_curriculum(topic)` | For an addition: what exists already |
| `write_curriculum(topic, curriculum, reasoning)` | Stores a version as a record. Code runs the whole contract at once and names every problem (below) |
| `report(summary)` | The helper's last call |

`write_curriculum` checks that the `scope` matches the topic's and its corpus documents'; the
prerequisites form a DAG; every `target_cards` is 5 to 25; the quotas use the six card types
and sum to the target; a tier with an image quota lists as many `image_needs` as the quota;
every tier has 5 to 10 grounding anchors, each an exact existing heading. Past go-on, any
change to an existing subtopic or tier is refused, so only additions get through.

## A topic's tadpole: cards and questions

After the curriculum is projected onto the topic's subtopics. The tadpole stays the
orchestrator: visual_toad's sourcing first, then one writer helper per tier, each tier's two gate passes, designer_toad and
visual_toad. Each tier goes live as soon as it is finished, and once the last one is live,
code makes the tadpole the topic's frog.

### The tadpole

| Tool | Does |
|---|---|
| `list_subtopics()` | Every group and tier: target, grounding, and progress (drafted, accepted, rejected, art, questions, live) |
| `start_subtopic(subtopic)` | A tier's writer helper. Refused until the topic's photographs are sourced and `images:check` passes, and while a lower tier of its group is unfinished; the tadpole decides which tiers run at once |
| `start_verifier(subtopic, brief)` | A pass-2 helper for a tier's cards past pass 1, or its questions. The tadpole decides what context it gets, and gives it none of the writer's or pass 1's reasoning |
| `hand_over("insufficient_evidence", records)` | A tier that cannot reach its target from its grounding, to toad_sage. The only way a tier finishes short |

### A tier's writer helper (NIM)

| Tool | Does |
|---|---|
| `read_grounding(subtopic)` | The tier's grounding sections, as numbered passages |
| `read_cards(subtopic)` | The tier's cards so far, the lower tiers' card bodies to build on, and the topic's titles |
| `plan_cards(subtopic, briefs[])` | The tier's plan (ADR-0059): concept, form and angle per card, as a record |
| `request_photos(briefs[])` | Asks visual_toad for the image briefs' photographs. An image card is written only after its photo is picked; a brief left without one becomes prose |
| `write_cards(subtopic, cards[])` | Drafts: dual titles, summary, body, cited passages, form, a picked photo or an art request (what to show, and ideas), hero. Code refuses a structural fault and names it (lengths, mermaid, a passage outside the grounding, a photo not picked for it or used elsewhere, the type quotas); nothing refused is stored. Embeds the drafts and derives their archetype |
| `gate_cards(subtopic)` | Sends the drafts to the tier's pass-1 helper; the survivors go to the tadpole for pass 2, and the verdicts wake the writer. Accepted cards stay; a rejected one is a `rejected_card` with its feedback, and the writer drafts again against it until the tier reaches its `target_cards` |
| `write_questions(subtopic, questions[])` | Refused until the tier reaches its target. Code checks the shape (distinct options, a correct index in range, a rubric for free text), that the card is accepted in this tier, and near-duplicate stems |
| `gate_questions(subtopic)` | Sends the questions to the tadpole for pass 2 |
| `submit_tier(subtopic)` | Refused until the tier reaches its target, every accepted card has its art or photo, and every question has passed. Then the tier goes live |

### Pass 1: correction (one helper per writer)

The old gate's first pass (ADR-0030) with its own fixed instructions, which the writer does not
brief.

| Tool | Does |
|---|---|
| `read_drafts()` | The waiting drafts, with their passages and the canonical topic. Difficulty withheld |
| `correct_cards(cards[])` | Rewrites a card, or returns it unchanged; never rejects. Code checks the structure again, embeds the corrected body, and rejects a near-duplicate of the topic's cards or an earlier one in the batch, naming its twin |

### Pass 2: verification (a helper of the tadpole, later of the frog)

| Tool | Does |
|---|---|
| `read_survivors()` | The cards past pass 1, with their passages and requested difficulty |
| `verify_cards(verdicts[])` | Per card: the difficulty it reads as, accept, and feedback. A rejection is a `rejected_card` with that feedback |
| `solve_questions(answers[])` | Each MCQ without its key; code compares the answer with the key, and a wrong or doubtful one is a rejection with feedback |
| `check_rubrics(verdicts[])` | Each free-text rubric against its card |

### designer_toad (one per tadpole)

Draws every ASCII art itself, for cards the gate accepted, replacing the curated scene library
(ADR-0021, ADR-0079, ADR-0080). A card goes live only with its art.

| Tool | Does |
|---|---|
| `list_art_requests()` | Accepted cards waiting for art, with the writer's request and ideas |
| `web_search`, `fetch`, `view_image` | Recent trends and references |
| `render_art(card, art)` | One call: checks the 40 columns and the character set, renders the card on a phone and returns the screenshot. Every render is a record |
| `attach_art(card, art)` | Refused unless this run rendered that exact art |

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
(research, maps, document writers, `audit_drafts`, `start_subtopic` for added tiers,
`start_verifier`, designer_toad and visual_toad). A report wakes it at once, and a tadpole
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
