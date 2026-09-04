# Corpus Authoring & Curation Rules

These rules govern how Antigravity authors, curates, and maintains `the_spoin_universe` corpus under the project owner's supervision.

---

## 1. The "Tips & Tricks" Requirement for Every Topic / Survey
- For every subject authored (survey or topic), Antigravity must author a dedicated **`tips-and-tricks.md`** file alongside the conceptual and architecture files.
- **Sourcing:** Actively research experienced practitioners' hard-learned lessons, operational traps, edge cases, postmortems, and field rules of thumb from **StackOverflow**, **Reddit** (e.g. `r/ExperiencedDevs`, domain-specific subreddits), and **GitHub** engineering discussions/postmortems.
- **Tone & Value:** Avoid textbook generalities. Capture the exact bugs, anti-patterns, and configuration gotchas that take production systems down (e.g. holding DB transactions across external HTTP calls, AWS NAT 350-second idle TCP drops, 64-bit ID truncation in JavaScript JSON, Redis `KEYS *` event-loop stalls, Redlock vs. fencing token realities).

---

## 2. ASCII Box Rule & Degradation Contract
- **The 40-Column Invariant:** Monospace width must strictly remain $\le 40$ columns across every single line.
- **Degradation Decision (Owner Policy):**
  - If any single line in the ASCII block exceeds 40 characters, or contains prohibited syntax (embedded backticks, malformed line endings), **the card is removed and discarded entirely**.
  - The card is **not** kept or published as a plain prose card. It must be regenerated so that the subtopic receives high-quality visual art.

---

## 3. Schema & Hierarchy Invariants (ADR-0091)
- **`topic_source`:**
  - Mandatory front matter: `category`, `scope` (`survey` or `topic`), `kind: topic_source`, `title`, `source`.
  - Optional: `sub_category`, `source_date`, `topic_tags`.
- **`spoin_canon`:**
  - Must omit `category`, `sub_category`, and `scope` (enforced by database CHECK constraint `ck_document_topic_source_has_category_and_scope`).
  - Mandatory front matter: `kind: spoin_canon`, `title`, `source`.
  - Sits under `docs/the_spoin_universe/corpus/_canon/`.

---

## 4. Editorial & Writing Style Invariants
- **Hook Layer Separation:** Silliness and charm live exclusively in the hook layer (`title`, `summary`, ASCII art). The `body` is strictly dry, factual technical truth that users are tested on and that quality gates verify.
- **Dual Titles:** `title` is the playful feed display title; `canonical_title` is the literal descriptive name read by search, quizzes, remediation, and generation already-covered lists.
- **Compositional Reuse:** Always write for cross-topic retrieval (e.g. *what is true about B-trees*), never narrating toward the specific topic that triggered the run.
