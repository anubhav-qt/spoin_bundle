# ADR-0095: Cards carry real photographs from an open-licensed image catalog, assigned server-side by retrieval

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner, implementing session
- **Amends:** [ADR-0088](0088-the-spoin-universe.md) — reverses its deliberate dropping of
  `author`/`licence`; attribution is now a stored, required field for images
- **Builds on:** [ADR-0089](0089-retrieval-grounded-generation.md) (retrieval),
  [ADR-0091](0091-corpus-category-hierarchy.md) (corpus hierarchy),
  [ADR-0066](0066-redraw-over-budget-ascii-art.md) (a bad visual rejects its card)
- **Implemented by:** [task 0040](../tasks/0040-open-licensed-image-catalog.md)

## Context

The visual layer of a card is currently ASCII art and mermaid diagrams. ASCII is
deliberately **gags only** ([ADR-0079](0079-ascii-library-is-gags-only.md)) — a hook, not
an explanation — and mermaid handles real diagrams
([ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md)). Neither can show what a thing
*looks like*. For a topic about Saturn, the Osirian cycle, or a nudibranch at 2,000
metres, a photograph is not decoration: it is the most information-dense thing that could
occupy that space, and we currently cannot put one there.

The corpus-authoring track already performs deep, sourced web research for every subject
(`docs/the_spoin_universe/procedure.md`, Phase C). It encounters the relevant imagery
during that research and throws it away. That is the asymmetry this ADR closes: the
expensive part — a human-supervised agent deciding which image genuinely illustrates a
subject — is already happening.

Three constraints shape the answer.

**We serve real users commercially.** The owner confirmed on 2026-09-05 that Spoin is a
commercial product. That removes any reliance on fair use or on non-commercial licences,
and it makes the naive version of this idea — re-hosting whatever the researcher found —
straightforward copyright infringement rather than a grey area.

**A bad visual now costs a whole card.** [ADR-0066](0066-redraw-over-budget-ascii-art.md)
replaced the old "drop the visual, keep the card" degradation: art that cannot be made
valid rejects its card for regeneration. So any mechanism where the model can *get the
image wrong* now destroys an LLM call's output rather than degrading quietly.

**Not every subject can be illustrated.** Under an open-licence-only policy, internet
culture is essentially unavailable — memes carry stacked rightsholders (the underlying
photograph, the meme-maker's edits, the caption) and commercial use is precisely the case
fair use does not cover. Living people, current products and recent news photography are
similarly closed. A design that assumes every topic yields images will loop forever on the
ones that do not.

## Decision

**Antigravity delivers an open-licensed image catalog as part of the corpus. The images
are re-hosted on Cloudinary, ingested like documents, and assigned to cards server-side by
retrieval — never chosen by the model.**

### Only these licences, and the exclusions are not stylistic

Allowed: **CC0, public domain, CC BY, CC BY-SA**, plus the Unsplash, Pexels and Pixabay
licences.

**NonCommercial (NC) is excluded** because Spoin is commercial. This costs real material —
Schmidt Ocean Institute's deep-sea imagery among it — and is not negotiable while that
remains true.

**NoDerivatives (ND) is excluded because of the architecture, not the policy.** Cloudinary
is a transformation pipeline; cropping and resizing produce a derivative work. An ND image
would be disqualified the moment it was served at card width. This one is easy to miss
precisely because ND otherwise looks like the harmless restriction.

### Attribution becomes a stored, required field — reversing ADR-0088

CC BY and CC BY-SA require displayed attribution. ADR-0088 deliberately dropped `author`
and `licence` from `document`, and said in the same breath: *"If you find yourself needing
to record either, that is a real signal — raise it rather than smuggling it into
`source`."* This is that signal, taken at face value rather than worked around.

So the image catalog stores `licence`, `attribution` and `source_url` as NOT NULL, and the
card renderer gains a place to display attribution. An image that cannot state its licence
does not enter the catalog — which makes the constraint structural rather than a promise
the authoring track has to keep.

### The model never sees the images

Image assignment is **retrieval, not generation**: after a card is drafted, its text is
embedded and matched against image descriptions in `the_spoin_universe`, filtered to
images not already used in that topic, and the best match is attached.

The alternative — listing available images in the prompt and letting the model pick, then
removing used ones from the list — was considered seriously and rejected on three grounds.

**It is the approach this project already rejected once.**
[ADR-0021](0021-ascii-scene-library.md) capped scene reuse by *counting server-side at
insert time*, explicitly "not trusted to the prompt", because "the model generates in
batches of ~10 and cannot see the rest of the corpus". Image assignment has exactly that
shape, and nothing about images makes the batching problem easier.

**It costs prompt budget the corpus work just finished protecting.** A menu of 450 images
at an id plus a short description is roughly 5.4k tokens on every generation call, before
any retrieved context. ADR-0089's table puts `ministral-8b` below the target throughput
above ~18k tokens, and task 0038's Phase 2 spent real effort keeping chunks small for that
reason. Server-side assignment costs zero prompt tokens.

**Under ADR-0066 its failure mode is now expensive.** A hallucinated or duplicated image
id would reject the card and burn the call. Server-side, the model emits no image
reference at all, so that failure class does not exist rather than being handled.

This is CLAUDE.md's rule applied literally: *the generator is trusted for taste, never for
constraints.* "No repeats within a topic" is a constraint.

### Availability is a planning input, so absence never loops

**The planner may only assign image cards up to the number of unused images the topic
actually has.** This is the load-bearing consequence of ADR-0066 and is the reason the
naive design is dangerous: if a card is planned as an image card, no licensable image
exists, and the missing visual rejects the card, the pipeline regenerates, plans another
image card, and fails again — an unbounded loop burning quota on a topic that can never
satisfy it.

The same shape already exists one line away in `generation/pipeline/state.py`: a `code`
card is never planned for a non-technical topic, because "the planner is trusted for
taste, not constraints". Image availability joins that check.

Consequently **"no image available" and "image is broken" are different outcomes**: the
first is a planning constraint that prevents the card being planned, the second is an
ADR-0066 rejection. Conflating them is what creates the loop.

### The coverage target is a ceiling, not a quota

The ambition is that a majority of cards carry a photograph. That figure is **read from
what the corpus can source, never aimed at.** Astronomy — NASA and ESA are wholly public
domain — may exceed it comfortably. Internet culture will sit near zero. Forcing a uniform
rate would push irrelevant images onto cards, which is worse than the ASCII gag it
replaced.

### Where the catalog lives, and where usage lives

**The catalog lives in `the_spoin_universe`**, delivered by Antigravity as an `images/`
manifest and ingested by the machinery task 0038's Phase 2 already built — parse, validate
against a contract, hash for idempotency, embed the description as a passage.

**Usage lives in `spoin_db_2`, on the card.** The corpus database is *derived and
rebuildable* (ADR-0088); image-to-card assignments are not. If a `used` flag lived in the
corpus, rebuilding it would silently orphan every assignment. Instead the card references
the image, and "unused" is a query — no active card in this topic references it — which
survives a corpus rebuild by construction.

### The manifest holds metadata, not binaries

Antigravity commits front-mattered manifest entries — source URL, licence, attribution,
description, tags — and **not the image files**. Hundreds of images per topic as git blobs
would bloat the repository permanently and irreversibly, and the corpus is deliberately
text-only.

The ingester fetches each image, uploads it to Cloudinary, and stores the returned URL.
Cloudinary is then our durable copy, which also removes link rot at the original source
from the failure set — a corpus meant to last cannot depend on a museum keeping a URL
stable.

## Consequences

**Easier.** The most information-dense visual a card can carry becomes available for the
subjects that warrant it. The expensive judgment — does this image actually illustrate
this idea — is made by a supervised researcher during work that already happens, not by a
model at generation time. Because assignment is retrieval, it costs no prompt budget and
no additional LLM call, on a path whose entire history is a fight for calls per minute.

**Harder.** A third visual kind joins ASCII and mermaid, and the renderer must handle all
three plus an attribution line. The corpus gains a delivery type with a genuinely
different contract. Cloudinary becomes a new external dependency with its own quota and
its own failure modes, and a second place where corpus state lives. Licence compliance is
now an ongoing obligation rather than a one-time check: an image whose licence is later
found to be misstated has to be removable, and the cards citing it repaired.

**Committed to.** Open licences only, indefinitely, and the coverage gaps that implies —
internet culture, living people, current products. Attribution displayed on cards. One
more thing that must be true about a corpus delivery before it can be ingested.

## Alternatives considered

**Re-host whatever the research turns up.** The original proposal, and by far the
cheapest. Rejected: copying third-party images to our own CDN and serving them
commercially is reproduction plus distribution, and the corpus contract already forbids
exactly this for text — *"Do not copy material you do not have the right to reproduce...
Cards will be shown to real users."* Images are worse, because unlike prose an image
cannot be restated in one's own words.

**Hotlink the originals instead of re-hosting.** Avoids storing a copy, and is at least
legally arguable where re-hosting is not. Rejected on reliability rather than law: link
rot, hosts that block hotlinking, no control over the served bytes, and a card whose
visual silently disappears months later. Cloudinary makes the image ours to serve.

**Generate images with a model.** No licensing question, unlimited coverage, fills the
brainrot gap. Rejected for this ADR: the product's claim is mastery of *true things*, and
a generated image of a nudibranch is a plausible nudibranch. It also reintroduces a
per-card generation cost on the write path. Worth revisiting for purely decorative slots
where no truth claim is made.

**Let the model pick from an in-prompt menu.** Discussed at length above: rejected on
ADR-0021's precedent, on prompt budget, and on ADR-0066 making its failure mode expensive.

**Put the image catalog in `spoin_db_2`.** No cross-database concern, and usage state sits
beside the images. Rejected: the catalog is authored material derived from a corpus
delivery, which is exactly what ADR-0088 separated, and it would make every image
re-delivery a migration against production.

## Revisit when

- **A topic is generated whose imagery is important and wholly unlicensable.** That is the
  moment to re-argue model-generated images for decorative slots, with a real example
  rather than in the abstract.
- **Cloudinary's free tier is exceeded.** Bandwidth, not storage, will be the binding
  constraint, and it arrives with user growth rather than corpus growth.
- **An image's licence is found to be misstated.** The first real test of whether the
  catalog can retract an image and repair the cards citing it — the image equivalent of
  ADR-0089's dangling-chunk question.
- **Spoin stops being commercial**, which would reopen the entire NC tier.
