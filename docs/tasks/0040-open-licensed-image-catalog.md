# Task 0040: An open-licensed image catalog, and photographs on cards

> **Status:** planned, not started. Written 2026-09-05.
> **Decision:** [ADR-0095](../adr/0095-open-licensed-image-catalog.md) — read it first;
> this document is the build, not the reasoning.
> **Depends on:** [task 0038](0038-frog-rag-and-hybrid-generation.md) Phase 3. Server-side
> image assignment *is* a retrieval query, so it sits on frog's retrieval layer rather
> than reimplementing pgvector search beside it.

## The problem

A card's visual layer is ASCII (gags only, [ADR-0079](../adr/0079-ascii-library-is-gags-only.md))
and mermaid ([ADR-0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md)). Neither can
show what something *looks like*. For Saturn, the Osirian cycle, or a nudibranch at 2,000
metres, a photograph is the densest thing that could occupy that space.

Meanwhile the corpus-authoring track already does deep sourced research per subject and
discards the imagery it encounters. The expensive judgment — *does this picture actually
illustrate this idea* — is already being made by a supervised agent, and thrown away.

## Ownership

| Track | Owner |
|---|---|
| Sourcing images, writing the manifest, licence verification | **Antigravity, supervised by the owner** |
| Ingestion, Cloudinary upload, assignment, planner, schema, renderer | implementing session |

Same split as the corpus itself. What the implementing session owes the authoring track is
**the image manifest contract, written before the images are sourced** — the same mistake
Phase 2 avoided and would have been expensive to retrofit.

---

## Phase 1 — The manifest contract, before anything is sourced

Extend `docs/handoff/antigravity-corpus-authoring.md` with an `images/` section. Nothing
is sourced until this is written and the owner has approved it.

### Layout

`docs/the_spoin_universe/images/`, mirroring the corpus hierarchy so an image sits beside
the subject it illustrates. **Manifest entries only — never image binaries.** Hundreds of
images per topic as git blobs would bloat the repository permanently and irreversibly.

### Front matter, first draft — to be reviewed with the owner

| Field | Required | Notes |
|---|---|---|
| `title` | yes | Human-readable; shown when a card cites the image |
| `description` | yes | **This is what gets embedded and matched against card text.** The highest-leverage field in the file — see below |
| `source_url` | yes | Direct URL to the original image file |
| `source_page` | yes | The page it was found on; what a human checks the licence against |
| `licence` | yes | From a closed allowlist — a free-text licence is a hard error, same reasoning as ADR-0088's `kind` enum |
| `attribution` | yes | The exact string to display. Required even for CC0, where it is "public domain" |
| `category` / `sub_category` | yes | Same normalized hierarchy as documents (ADR-0091) |
| `topic_tags` | yes | Normalized by the same `normalize_topic_text` (ADR-0093) |

`cloudinary_url` and `content_hash` are **derived, never written** — the same two fields
documents already have, for the same idempotency reason.

**`description` deserves its own guidance in the contract.** It is not alt text and not a
caption: it is the text a card's body will be semantically matched against. "Saturn's
rings backlit by the sun, photographed by Cassini from within the planet's shadow" will
match a card about ring composition. "Saturn" will match nothing in particular. Get this
wrong and retrieval silently returns mediocre images, which is exactly the failure shape
the corpus's own contract warns about for prose.

### The licence allowlist

Allowed: `cc0`, `public-domain`, `cc-by`, `cc-by-sa`, `unsplash`, `pexels`, `pixabay`.

Rejected, and the reasons are worth restating in the contract because both are
counter-intuitive:

- **NC (NonCommercial)** — Spoin is commercial (owner, 2026-09-05).
- **ND (NoDerivatives)** — Cloudinary crops and resizes, which produces a derivative work.
  ND is disqualified by the architecture, not by policy.

### Where to source

Give Antigravity the tiers, not a single site. Verified during ADR-0095's research:

| Tier | Sources |
|---|---|
| Gateways | **Openverse API** (800M+ items, filters `license=by,cc0` plus commercial-use and modify/adapt at query time — the single best programmatic entry point), Wikimedia Commons |
| Science / nature | NASA, ESA/Hubble, JWST, **NOAA Photo Library and Ocean Exploration**, FathomNet, USGS, NIH/NLM, CDC PHIL, Wellcome Collection, Biodiversity Heritage Library, PhyloPic |
| Art / history / mythology | Smithsonian Open Access, Met, Rijksmuseum, Art Institute of Chicago, Cleveland Museum, National Gallery of Art, **Getty Open Content** (the museum, *not* Getty Images), Library of Congress, British Library on Flickr, NYPL, Europeana, DPLA |
| Contemporary / everyday | Unsplash, Pexels, Pixabay — the tier museums cannot cover |

Two traps to name explicitly in the contract:

- **NOAA:** public domain *unless the caption contains the word "copyright"*, which some
  do. It is a per-image check, not a blanket rule.
- **Schmidt Ocean Institute:** excellent deep-sea imagery, explicitly prohibits commercial
  use. Excluded despite being exactly on-topic.

### Say plainly which subjects have no images

Internet culture and memes are unavailable: stacked rightsholders (underlying photograph,
meme-maker's edits, caption) and commercial use is the case fair use does not cover.
Living people, current products and logos, recent news photography — the same. The
authoring track should report "no sourceable imagery" as a **normal, expected outcome**
rather than trying to fill a quota, because the planner reads real availability
(Phase 4).

---

## Phase 2 — Ingestion and Cloudinary

Extend `frog/ingest/` rather than building beside it. An image manifest is a document with
a different contract, and everything Phase 2 of task 0038 built — walk, validate-all-report-all,
content-hash idempotency, batch passage embedding — applies unchanged.

- Schema: an `image` table in `the_spoin_universe`. `Vector(1024)` on the description,
  `licence` / `attribution` / `source_url` NOT NULL (ADR-0095 reverses ADR-0088's
  author/licence drop). Its own alembic revision on frog's chain.
- **Licence is a Postgres enum, not free text** — ADR-0088's reasoning for `kind` applies
  with more force here, because a typo'd licence is a legal exposure rather than an
  unretrieved row.
- Upload to Cloudinary on first ingest; store the returned URL. Skip on unchanged hash,
  exactly as documents do — **re-ingestion must not re-upload**, or the free tier is spent
  on repeat deliveries.
- Fetch failures are reported per-image and do not stop the run, matching the existing
  report-everything posture.
- Credentials via environment, following `SPOIN_UNIVERSE_DATABASE_URL`'s precedent, and
  **only the ingester reads them** — the deployed backend never uploads
  ([ADR-0094](../adr/0094-local-generation-lightweight-production.md)).

⚠️ **`--check` must stay pure.** It validates the manifest — required fields, licence in
the allowlist — with no network, no Cloudinary, no model. That property is what makes it
runnable by the authoring track, and it is easy to destroy by adding a URL liveness probe.
If a reachability check is wanted, it is a separate flag.

---

## Phase 3 — Assignment, server-side

After a card is drafted: embed its text as a query, search `image` in the topic's
categories, exclude images already used by an active card in this topic, attach the best
match above a similarity floor.

- **A floor, not just a top-1.** An irrelevant image is worse than none — it makes a card
  look sourced while showing something else, the visual analogue of ADR-0089's
  confidently-grounded-wrong-card. Calibrate the threshold against real cards in Phase 5;
  do not pick it now.
- The model emits **no image reference at any point**. It is not told images exist.
- Uniqueness is a query, not prompt state, so intra-batch collisions cannot happen: a
  second card in the same async run simply gets the next-best image.
- Reuse the frog retrieval layer from task 0038 Phase 3. If that has not landed, this
  phase blocks — do not fork a second pgvector search.

### Schema on the product side

`card.visual_id` and `card.visual_slots` already exist and already carry the right shape:
*"The card stores a reference plus text, never rendered art"* (ADR-0021, still true even
though its degradation rule is not). An image card points `visual_id` at a catalog entry.

Open question for the owner in Phase 3, not now: whether `card.visual_id` is enough or
images want their own nullable FK column. It depends on whether a card may ever hold both
an ASCII gag and a photograph — probably not, but that is a product call.

---

## Phase 4 — The planner, and the loop this prevents

**The planner may assign at most as many image cards as the topic has unused images.**

⚠️ This is the phase that must not be skipped, and the reason is
[ADR-0066](../adr/0066-redraw-over-budget-ascii-art.md). A visual that cannot be made
valid now **rejects its card for regeneration** rather than degrading to an art-less card.
So if a card is planned as an image card, no image exists, and the missing visual rejects
it, the pipeline regenerates, plans another image card, and fails again — **an unbounded
loop burning quota on a topic that can never satisfy it.**

- `CardType` gains `IMAGE`. `card_type_matches` in `generation/pipeline/state.py` requires
  a resolved image for it, mirroring `ASCII`'s existing check.
- Availability is passed into planning the way technical-topic-ness already is: the `code`
  check one line above is the precedent, and the principle is the same — *the planner is
  trusted for taste, not constraints*.
- **"No image available" and "image is broken" must stay distinguishable.** The first
  prevents the card being planned; the second is an ADR-0066 rejection. Conflating them
  is what creates the loop.
- The coverage ambition is a **ceiling read from real availability, never a quota**.
  Astronomy may exceed it; internet culture will sit near zero.

---

## Phase 5 — Render, attribute, and look at it

- The card renderer displays the image and its **attribution** — required by CC BY and
  CC BY-SA, and the reason ADR-0095 reverses ADR-0088.
- Serve through Cloudinary transformations at card width; mind that this is what makes ND
  licences inadmissible.
- Web and the future mobile client render from the same API fields. No business logic in
  `apps/web` (CLAUDE.md).
- **Review in the real feed, not a terminal** — the ADR-0012 posture. The questions worth
  answering are whether assignment is actually relevant card-by-card, and whether photos
  make ASCII gags feel out of place next to them. Both are judgments about the feed, not
  about the code.
- Write it up as a benchmark doc, with the assignment-relevance rate measured rather than
  asserted.

---

## Open questions for the owner

- **Cloudinary account and free-tier headroom.** Bandwidth, not storage, is the binding
  constraint, and it scales with users rather than corpus size.
- **Retraction.** When an image's licence turns out to be misstated, what happens to cards
  citing it? This is the image form of ADR-0089's dangling-chunk question, and it is
  currently unanswered for both.
- **Does a card ever carry both a photograph and an ASCII gag?** Decides whether
  `visual_id` is reused or images get their own column (Phase 3).

## Commit message theme

`a picture is worth a thousand tokens`.
