# Topic Generation Queue & Overnight Plan

### Completed Topics
- [x] **Financial Literacy & Investing Mechanics** (1,185 cards, 1,175 questions across 73 subtopics) — Exit Code 0
- [x] **Building a Game Engine using RayLib** (382 cards, 367 questions across 31 subtopics) — Exit Code 0
- [x] **Carl Jung's Philosophy** (589 cards, 589 questions across 30 subtopics) — Exit Code 0
- [x] **Philosophy** (706 cards, 699 questions across 40 subtopics) — Exit Code 0
  - *Note*: Evaluated by LLM topic matcher and minted as distinct from *Carl Jung's Philosophy*.
- [x] **Mathematics** (707 cards, 698 questions across 45 subtopics) — Exit Code 0
- [x] **Bhagvad Geeta in Easy Language** (655 cards, 650 questions across 44 subtopics) — Exit Code 0
  - *Database*: `spoin_db_2`

### In Progress
- [ ] **Rust (Programming Language)** — Running on `spoin_db_2`
  - 66 subtopics, targeting **1,354 cards** and **396 questions**
  - Task `task-1291` active; card planning pass completed, multi-round drafting in progress.

---

### Pipeline Status
- All overnight topics (*Financial Literacy*, *RayLib*, *Carl Jung's Philosophy*, *Philosophy*, *Mathematics*) completed 100% on `spoin_db`.
- *Bhagvad Geeta* completed 99.5% on `spoin_db_2` (655/658 target cards).
- *Rust* generation is actively running on `spoin_db_2`.

---

### Known Issues / Investigate Later

> **TODO**: One card in the *Bhagvad Geeta in Easy Language* topic contains a Python
> code snippet (a `code` archetype card with a Python fenced block). This should not
> happen for a non-technical, spiritual/philosophical topic. Possible causes to check:
>
> 1. The planner assigned a `code` archetype to a subtopic where it makes no sense.
> 2. The generator hallucinated a code example as a "practical exercise" or analogy.
> 3. The verification gate did not reject the card because the code was syntactically
>    valid Python, even though it was topically irrelevant.
>
> **Action**: Query the card from `spoin_db_2` (`SELECT * FROM card WHERE topic_id =
> <bhagvad_geeta_topic_id> AND 'code' = ANY(archetype)`), inspect its `body` and
> `visual_slots`, and trace its `prompt_version` back to the planning pass that
> assigned the archetype. If the planner is at fault, add a guard to
> `_card_matches_type` in `pipeline/state.py` that rejects code archetypes for topics
> whose canonical name does not match a known technical domain. If the generator is at
> fault, add a topical-relevance check to the verification gate.
