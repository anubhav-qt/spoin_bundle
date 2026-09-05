# The corpus co-authoring system

> Written 2026-09-05. The decision and its reasoning are
> [ADR-0100](../adr/0100-the-universe-is-a-claim-qualified-knowledge-system.md); this
> document is the system. The delivery contract it produces against is unchanged:
> [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md).

**The one-line change:** stop asking *"what should this document say?"* and start asking
*"what must Spoin know to reliably teach this domain from zero to expert judgment?"* Prose
is authored **last**, from an evidence-qualified map, by a family of role-specific prompts
rather than one generation prompt.

## Why a family of prompts, not one

A single prompt asked to research, structure, qualify evidence, write, and audit does all
six at the quality of whichever it weights highest — and what it weights highest is prose,
because prose is what it is scored on by a reader. Splitting the roles means the auditor is
not the author, and the epistemic-confidence pass cannot be quietly satisfied by the same
pen that wrote the overconfident sentence.

Each role below states: what it plays, what evidence it may use, what it must never invent,
and when it stops and asks the human. **Every role may return "insufficient evidence", and
that is a successful outcome, not a failed one.**

## Phase 1 — Map before prose (A–J)

No document is written until these exist and the owner has approved them.

| | Stage | Produces | The question it answers |
|---|---|---|---|
| A | Domain map | The major areas of knowledge | What is this domain made of? |
| B | Prerequisite graph | Directed edges between concepts | What must be understood before what? |
| C | Claim inventory | The statements Spoin will assert as true | What are we actually committing to? |
| D | Evidence mapping | A source per major claim, with its tier | Why do we believe each one? |
| E | Competency map | What a learner must *do* at each level | What does mastery look like here? |
| F | Misconception map | Wrong beliefs Spoin must detect and correct | Where do learners predictably go wrong? |
| G | Application map | Where each concept is actually used | Why does this matter outside a card? |
| H | Variability map | Where several legitimate approaches exist | Where is there no single right answer? |
| I | Gap audit | What is missing, stated plainly | What can we not yet teach? |
| J | Version audit | Which claims are time-sensitive | What will rot, and when? |

**K — Final curation.** Only now is dense prose authored, against the existing delivery
contract, from the maps above.

## Phase 2 — The roles

**1. Domain architect.** Produces A. May use official documentation, syllabi, standards
bodies, authoritative texts. Must not invent an area because a domain "usually has one".
Stops when the domain's own boundaries are contested — that is an owner decision.

**2. Prerequisite mapper.** Produces B. Edges must be justified by a real dependency ("you
cannot reason about lifetimes without borrowing"), never by conventional teaching order.
Stops on cycles: a cycle is a signal that a concept needs splitting.

**3. Authoritative-source researcher.** Produces the source pool for D, each entry tagged
with its tier: primary specification → official documentation → primary research →
authoritative textbook → recognised expert material → secondary synthesis → community
heuristic. **Never silently promotes a tier.** A manufacturer's manual stays a manufacturer's
manual. Stops when the best available source for a load-bearing claim is community
heuristic — the owner decides whether that claim ships qualified or not at all.

**4. Canonical claim curator.** Produces C, each claim carrying `claim_type` (`normative` |
`empirical` | `mechanistic` | `heuristic` | `implementation` | `pedagogical`), scope
(`universal` | `common` | `conditional` | `product-specific`), and confidence. **This role
owns the forbidden conversions**: heuristic → law, typical value → universal constant,
implementation detail → conceptual truth, mental model → formal specification, expert
recommendation → proven fact.

**5. Mechanism explainer.** Writes the causal chains. **The most dangerous role, and it is
told so**: a fluent mechanism is exactly what a language model manufactures best, and a
clean causal story can far exceed what the cited research establishes. Every link in a chain
is separately evidenced or the chain is labelled `mechanistic` with its speculative joints
named.

**6. Example / counterexample author.** For each important concept: canonical example,
counterexample, boundary condition, consequence. **A concept with only a definition is not
represented.** For Rust's `&mut T`: the rule, the example, the rejected `let a = &x; let b =
&mut x;`, the misconception ("so Rust never lets me have two references"), the boundary
(shared references are fine), the consequence (why iteration plus mutation behaves as it
does).

**7. Misconception analyst.** Produces F from real learner error, not imagined error —
forums, errata, "why doesn't this compile", coaching literature on common faults.

**8. Practical application author.** Produces G. Where the concept is used, in what kind of
system, at what stakes.

**9. Diagnostic / failure-mode author.** What breaking looks like, and how to tell which
break it is. The 10m corpus's diagnostic signatures and the LangGraph recovery material are
the standard to match.

**10. Trade-off / alternative analyst.** Produces H. For practical domains the shape is
`principle → common implementation → individual variation → diagnostic feedback →
adaptation`, never `principle → one optimal configuration`.

**11. Versioning auditor.** Produces J. Flags every *modern*, *standard*, *preferred*,
*current*, *supported* lacking version or date scope, and separates stable conceptual
knowledge from version-specific, deprecated, current and historical behaviour.

**12. Epistemic-confidence auditor.** Reads the drafted prose hunting for false precision:
unsupported exact values, thresholds, percentages, timings, universal prescriptions. For
every numeric claim it asks whether it is normative, measured, typical, approximate,
implementation-dependent, or heuristic — and rewrites toward the honest form.
*"Elite shooters always fire within 8 seconds"* → *"many coaching protocols use a bounded
hold window; the exact duration varies by athlete and method."*

**13. Coverage auditor.** Produces the zero-to-mastery matrix: awareness, vocabulary,
foundational mental model, fundamentals, basic application, guided practice, independent
application, diagnosis/debugging, trade-off reasoning, novel situations, cross-topic
integration, expert judgment. Each marked **strongly supported / weakly supported /
absent**, with the evidence for the mark. This is what replaces "we have nine documents".

**14. Human co-curator.** The owner. Approves the maps before prose, resolves every
"insufficient evidence", and is the only role that may declare a topic canonical.

## The quality gate

Before a topic is canonical: factual correctness, source authority, evidence quality,
epistemic labelling, version correctness, prerequisite coherence, conceptual coverage,
competency coverage, misconception coverage, counterexample coverage, practical usefulness,
internal consistency, cross-topic relationships, retrieval atomicity, and absence of
unsupported precision.

**The gate prefers "unknown / insufficient evidence" over a plausible but unsupported
answer.** It is a hard preference, not a tiebreak.

## What does not change

Keep the dense authoring style — it is the corpus's strongest property and this system sits
*above* the prose, not in place of it. Keep contextual chunk headers, cross-topic retrieval
(do not partition knowledge by topic), authoring by relationships, and practical examples
and failure modes. The delivery contract is unchanged: `##` sections are chunk boundaries,
the token bound holds, sources are human-curated, and frog stays retrieval infrastructure
rather than an authority.

**Completeness emerges from the network, not from enormous files.** A document that tries to
be a textbook breaks the chunking contract and helps nobody.

## The standard this is held to

Spoin never teaches something because a model can explain it convincingly. It teaches it
because the knowledge exists in the canonical universe, its provenance and scope are
understood, its relationships are represented, its uncertainty is represented where
relevant, and a learner can meet it at the right point in a competency progression.
