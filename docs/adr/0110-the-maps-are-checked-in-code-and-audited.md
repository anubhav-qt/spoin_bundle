# ADR-0110: The maps are checked in code and audited before toad_sage reads them

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** project owner
- **Amends:** [ADR-0100](0100-the-universe-is-a-claim-qualified-knowledge-system.md) (how its
  maps are held to its rules in the harness)

## Context

The owner reviewed the harness's second stage, research and maps (task 0045), on the three topics
run so far: System Design, Rust and the Bhagavad Gita. The maps had ADR-0100's shape and little of
its substance:

- All 69 claims of the three maps C were rated high confidence, a personal blog's included.
  One AWS simulation of 100 clients became a universal "over 50%". The Gita's doctrines were
  stated as facts about the world ("the self is imperishable"), two of them labelled empirical.
- Maps C held 18 to 31 claims and maps F 8 misconceptions each, for topics of 450 to 700 cards,
  a tenth of which are myth-vs-fact cards written from map F.
- Rust rested on one introductory book, four of its chapters from the Rust 1.80 copy two years old
  while the book's own front page, stored and cited, said it targets 1.97. Its version map called
  edition 2024 something to re-verify. The Gita rested on 15 of its 700 verses from one devotional
  translator, a two-week-old blog and one encyclopedia article. A devotional commentary was
  labelled the primary text.
- Whole areas of the intake briefs had no source at all, and map I listed only deliberate
  exclusions: "insufficient evidence" was never used.
- Code checked that a cited passage existed, not that it said what the claim said. Spot checks
  found six claims their passages don't support.
- toad_sage said go on to all six handovers, praising "rigorous" maps, from the tadpole's own
  description of them.

## Decision

**What must be true is checked in code; what must be good is audited by a call that didn't write
it.** The maps can't go to toad_sage until code finds them whole, and toad_sage reads what code
counted, not only the tadpole's note.

1. **Each item carries what code needs.** A claim names its domain, an item of map A, and an
   implementation claim names the product and version it is true of (`appliesTo`). A source in
   map D is one publication, with its tier and its date or version (`sourceDate`).
2. **The maps hold together** (`mapsProblems`), checked at `audit_maps` and at the maps' handover:
   - all ten written; every page a claim cites belongs to one source of map D;
   - a claim's confidence is no more than its sources give: high on a specification, official
     documentation, primary research or an authoritative textbook, or on two recognised experts
     that agree; medium on at least a secondary synthesis; a community heuristic alone is low. An
     empirical claim cites the primary research that measured it;
   - every domain of map A is taught from at least two sources, or map I names what is missing as
     a gap of that domain;
   - map C holds a claim for every 3 of the intake's cards and map F a misconception for every 10
     (the owner's ratios).
3. **An evidence auditor reads maps C and F** (`audit_maps`): fixed calls of 15 items each, every
   item beside the passages it cites and their sources, reporting support, class, scope and
   confidence, versions, doctrine stated as fact, and misconceptions nobody holds. Findings are
   records the tadpole settles, only ever as fixed, and code refuses that while the item is as the
   audit read it: it is changed with `change_map` (cite a passage that says it, narrow it, label
   it lower) or dropped. It reads only the items changed since it last read, so nothing is paid
   for twice, and a fix is read again.
4. **The handover waits for it.** `hand_over(maps)` is refused until the maps hold together, the
   latest maps C and F are audited, and every finding is settled. It then stores what code
   counted: claims and misconceptions against their floors, the mix of confidence, class and scope,
   each domain's claims and sources, each source's tier and date, and the findings fixed. toad_sage judges from those and the maps, and its prompt names what code
   can't: coverage of the brief from beginner to mastery, sources at the topic's level and current,
   and the coverage note's promises kept.
5. **`change_map` sends only what changes**, items by name and `drop`, as a document's sections
   are: a claim inventory of 234 claims is never resent to fix one. `write_map` and `change_map`
   say by how much a map C or F falls short of its floor, as it is written.
6. **The web is the helpers'.** Map A is written first, and the tadpole has no `web_search` or
   `fetch`: it starts a helper per domain, and reads what they stored. `fetch` refuses a site's
   bot check rather than store it as the page.
7. **The tadpole's prompt** researches a domain per helper, past any introductory book to the
   reference and specification, a text whole with a neutral translation and its commentary
   traditions, checks what is current, takes misconceptions from what learners really get wrong,
   and says what a text or tradition teaches rather than stating it as fact.

A run cut off between a call's end and its result is a harness fix of the same review: the next
run's opening message carries the logged results that never reached the transcript (System
Design's first tadpole lost a fetched page this way and cited another for it).

### Amended after the first rerun (2026-10-14)

Points 3 to 6 were tightened after the three topics were run again on these rules at Gemini's low
thinking. Rust's tadpole settled 104 of the auditor's 126 findings as kept, most with "standard
syntax; kept" on a claim its cited passage doesn't make, and toad_sage said go on because "the
kept audit findings are sound": a reason the tadpole writes is the same evidence as its note, so
kept is gone for the maps. The System Design and Gita tadpoles made 105 and 60 web calls
themselves, one after another, System Design's an hour of them with no map A and no helper, hunting
page numbers of books it couldn't fetch; Rust's, which left the web to its helpers, made 15. Two
Cloudflare bot checks were stored as pages. The Gita's tadpole wrote 18 claims for 450 cards and
was told it needed 150 only at the audit.

## Alternatives considered

**Ask for honesty in the prompt.** Rejected: the old prompt already asked for claims "labelled
honestly" and sources "of a fitting tier", and toad_sage was asked to check it. A rule only stated
in a prompt is a wish (CLAUDE.md, "the generator is trusted for taste, never for constraints").

**Let toad_sage audit the evidence.** Rejected for the same reason ADR-0100 gives: the reviewer that
reads the tadpole's description of its maps is the same class of evidence as the maps. The auditor
reads the passages, not the author's reasoning.

**Let the tadpole keep a finding, for toad_sage to judge.** Tried first, and toad_sage went on
from the tadpole's reasons. A finding the auditor got wrong is cheap to answer in the item itself:
cite the passage that says it, and the next audit reads it again.

**Require two sources for every claim.** Rejected: an official documentation page alone is enough
for a claim it states, and two blogs repeating each other are not two sources. Two sources per
domain, and two experts for a high confidence without a primary source, ask for corroboration
where it carries weight.

**Size the maps by the documents' rule alone.** Rejected: the documents are written from the maps,
so a corpus of 234 sections built on 31 claims fills the rest from the writer's own knowledge, the
very thing ADR-0100 exists to stop.

## Consequences

The maps cost more: research fans out to helpers, map C is ten times bigger, and the auditor makes
a call per 15 items. A map that can't be backed says so in map I instead of being filled, so a
thin field finishes with honest gaps rather than confident prose.

The tier-to-confidence rules are code's judgment of the source hierarchy, and a mislabelled tier
still passes them; that is the auditor's and toad_sage's to catch.

## Revisit when

- A topic's maps pass every check and the documents built on them still teach a claim that is
  confidently wrong: trace which check let it through.
- The owner's stage reviews show the floors too high for a field's real evidence, or too low for
  its cards.
