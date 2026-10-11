# The harness's tools

Every tool each chat of the authoring harness gets ([ADR-0106](../adr/0106-typescript-on-hono-and-the-authoring-harness.md),
task 0045). Designed with the owner one chat at a time before Phase 8, so the pi fork's tool
wrapper is built knowing all of them; the reasoning behind each choice is in task 0045's
"Decided during the port".

Two rules hold for every tool. **Tool errors teach**: a wrong call throws `ToolError`, one short
line on what was wrong and how to call it right. **Records live in Postgres**: whatever a tool
writes is a versioned record or a row checked in code, never something an agent only remembers.

## Every chat

As in Trotter: `read_record`, `read_record_history` and `list_records` read any record;
`ask` and `answer` pass a question between chats; `write_summary` writes the chat's summary
in a compaction run.

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

## A topic's tadpole: research, corpus, images, report

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
| `hand_over(kind, records)` | The coverage note, the maps, an "insufficient evidence" or the closing report, to toad_sage. The run ends until its review wakes the tadpole. The closing report is refused until the latest drafts are audited, every finding is fixed or answered, and `corpus:check` and `images:check` pass |

### Documents

A tadpole writes only its own topic's documents. Stale material it notices elsewhere goes in its
closing report, and toad_sage routes it to that topic's frog. Drafts are ingested only once
toad_sage says go on to the closing report, so no other topic retrieves them before; the
curriculum chat starts after ingestion.

| Tool | Does |
|---|---|
| `write_document(path, title, source, source_date, tags, epistemic fields, sections)` | Code copies kind, category, sub-category and scope from the topic row, checks the corpus contract at write time naming every problem at once, writes the file and keeps the previous version as a record |
| `audit_drafts()` | The three auditing calls (versions, false precision, the coverage matrix) with their own fixed prompts, which the tadpole does not brief. Findings are records |

### Images

| Tool | Does |
|---|---|
| `view_image(url)` | Downloads and stores the image, and shows it to the model |
| `add_image(image, licence, licence_url, author, description, …)` | An entry in the topic's image manifest. Refuses a licence outside the allowlist and an image this run has not viewed |
| `remove_image(image)` | Takes an entry out |

### Helpers

`start_helper(task, brief)` and `report(summary)`, as toad_sage's.
