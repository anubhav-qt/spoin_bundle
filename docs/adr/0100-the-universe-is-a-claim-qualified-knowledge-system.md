# ADR-0100: `the_spoin_universe` is a claim-qualified knowledge system, not a document collection

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner

## Context

Three delivered corpora — Rust, LangChain/LangGraph, and 10m air pistol — were read end to
end and assessed. The verdict: the authoring process produces **high-density expert survey
material**, strong on semantic density, mechanism-first explanation, cross-topic
relationships, and practical failure modes. Those properties are exactly what retrieval
wants and are not in question here.

What the corpus is **not yet** is a source of truth. A source of truth must be
authoritative, versioned, evidence-qualified, coverage-complete, internally coherent, and
pedagogically generative. The corpus is strong on the first property in spirit and weak on
the other five in mechanism.

**The dangerous failure is not omission.** It is that the prose sounds more certain than the
underlying evidence justifies, and nothing in the pipeline can tell the difference. frog
does not evaluate a passage's epistemic status — it retrieves it. The generator drafts from
it, the thinker gates against it, and Spoin teaches it. **A beautifully written falsehood
becomes a canonical falsehood**, and the gate cannot catch it, because the gate's own
grounding is that same passage.

Three concrete shapes of this, one per corpus:

- **False precision.** The 10m corpus prescribes 50/50 weight distribution, 30–40% grip
  pressure, 4–8 second firing windows, 60–80% of the cardiac R-R interval, exact trigger
  travel values, specific SCATT thresholds. Some are useful numbers. The prose presents them
  as universal physical law. *"If the shot has not broken by 8.0 seconds"* and *"many
  coaches use roughly 6–8 seconds as a practical upper bound because…"* are different kinds
  of statement, and the corpus collapses them.
- **Scientific-sounding mechanism that outruns its evidence.** The same corpus builds clean
  causal chains through baroreceptor discharge, cortical inhibition, alpha oscillations,
  sensory gating, photopigment bleaching. The problem is not that it sounds smart — it is
  that the reader gets no signal separating experimentally demonstrated fact from
  explanatory interpretation.
- **Temporal decay.** The LangChain corpus describes a moving ecosystem using *"modern"*,
  *"the standard"*, *"preferred mechanism"*, *"fully supported replacement"* — with
  `source_date: 2024` across material about current APIs. `Command` being preferred over
  conditional edges and *"a `TypedDict` declares a mapping of fields"* currently sit in the
  same epistemic bucket. One is version-scoped ecosystem guidance; the other is stable.

Rust wears the same problem in a different costume: *"Rust programs are designed as a DAG of
data transformations"* is a useful architectural heuristic stated as a description of the
language. Language guarantee, common implementation, Tokio behaviour, recommended practice,
and pedagogical mental model bleed together.

Two further gaps, both about what the corpus is *for*:

- **"Comprehensive-looking" is not comprehensive.** Nine dense Rust documents are not a
  zero-to-mastery curriculum; the LangChain corpus is an advanced survey that starts in the
  deep end. Density is being mistaken for coverage.
- **The unit is a fact, not a competency.** Documents are mostly `assertion → explanation`.
  Mastery needs `assertion → example → counterexample → misconception → boundary →
  consequence`, and for practical domains it needs learner variability — principle, common
  implementation, individual variation, diagnostic feedback, adaptation — rather than one
  optimal configuration.

## Decision

**`the_spoin_universe` is treated as a canonical knowledge system and one of the project's
primary assets, not a collection of essays.** Three commitments follow.

**1. Claims are first class, and epistemically qualified.** Every substantial claim belongs
to exactly one class, and the classes are never presented as equivalent:

| Class | Means | Example |
|---|---|---|
| `normative` | A specification, standard or rule says so | ISSF regulation, Rust reference, an RFC |
| `empirical` | Measured, with a population and conditions | "Elite shooters exhibited X under these conditions" |
| `mechanistic` | A causal explanation of why | The baroreceptor chain — the class needing most care |
| `heuristic` | Practical, usually works, not a law | "Prefer bounded channels" |
| `implementation` | True of one product/framework/version | "LangGraph 1.x prefers `Command`" |
| `pedagogical` | A teaching abstraction | "Rust as a DAG of data transformations" |

Forbidden conversions, stated as rules because each is a silent promotion: heuristic → law,
typical value → universal constant, implementation detail → conceptual truth, mental model →
formal specification, expert recommendation → experimentally proven fact.

**2. Versioning and provenance are part of truth.** Implementation-scoped claims carry
applicability (framework, version, `verified_on`) and status. Words like *modern*,
*standard*, *preferred*, *current*, *supported* may not appear without version or date
scope. The source hierarchy is explicit — primary specification → official documentation →
primary research → authoritative textbook → recognised expert material → secondary
synthesis → community heuristic — and **a lower tier is never silently promoted**. A
manufacturer's manual does not become an empirical law; a coach's recommendation does not
become a universal biological truth.

**3. Coverage is audited against competency, not page count.** Every topic gets an explicit
coverage matrix across twelve stages, from awareness and vocabulary through diagnosis,
trade-off reasoning, novel situations, cross-topic integration and expert judgment, marking
each stage strongly supported, weakly supported, or absent. *"We have nine documents"* stops
being an answer.

**The authoring workflow inverts.** Prose is authored **last**, after a domain map,
prerequisite graph, claim inventory, evidence mapping, competency map, misconception map,
application map, variability map, gap audit and version audit. It is executed by a family of
role-specific prompts rather than one generation prompt —
[`docs/handoff/corpus-authoring-system.md`](../handoff/corpus-authoring-system.md) is that
system.

**"Insufficient evidence" is a valid, expected deliverable.** The workflow must be able to
say the corpus is not good enough, and a gap must never be filled with plausible
model-generated material. This is the same rule the image contract states for imagery
([ADR-0095](0095-open-licensed-image-catalog.md), task 0040), for the same reason.

## Consequences

**Easier.** "Is this topic good enough to found mastery on?" becomes answerable from an
audit rather than from reading it and feeling impressed. Eventually a card can answer *why
does Spoin believe this* — concept, claim, evidence, scope, misconceptions addressed —
because provenance is retrievable rather than implicit.

**Harder.** Authoring gets substantially more expensive per topic, and the front half of it
produces no prose at all. The existing corpus does not meet this bar and will need a
retrofit pass. Epistemic labels are themselves authored, so they can be wrong — a
mislabelled claim is more dangerous than an unlabelled one, because it carries borrowed
authority.

**Committed to.** Density stays; this sits *above* the prose, and the corpus must not become
Wikipedia sludge. The existing retrieval contract is unchanged — document title/context on
every chunk, `##` sections as chunk boundaries, the token bound, human curation, and frog as
retrieval infrastructure rather than an authority.

## Alternatives considered

**Keep authoring as-is and rely on the two-pass quality gate.** Rejected: the gate is
grounded on the same passages. A corpus claim that is confidently wrong is invisible to it —
that is precisely the failure mode ADR-0089 moved grounding upstream to avoid.

**Make documents longer and more complete.** Rejected: length is what the corpus already
optimises for, and it produced "comprehensive-looking". Completeness must emerge from the
network of documents and semantic units, not from enormous individual files — which would
also break the chunking contract.

**A full claim database with claims as rows, replacing prose.** Rejected for now as a
schema-first answer to an authoring problem. Get the epistemic discipline into the authoring
workflow and the document format first; promote claims to their own table when the labels
have proven stable enough to be worth a migration.

**Have an LLM review the corpus and grade it.** Rejected: it is the same class of evidence
as the corpus itself, and produces the same confident-sounding output the decision exists to
distrust.

## Revisit when

- The first topic completes the full workflow. Measure what it cost against what the audit
  caught; if the front half finds little, the process is too heavy for the value.
- Epistemic labels prove stable across several domains — the signal to promote claims from
  document metadata to first-class retrievable rows, and to have frog return an evidence
  package rather than passages.
- A card is found teaching a corpus claim that was confidently wrong. That is the failure
  this ADR exists to prevent; it should be traced back to which qualification was missing.
