# Spoin Helpers & Tools

This directory contains standalone tools, scrapers, and curated reference libraries that support Spoin's development and content generation pipelines.

---

## 🎨 ASCII Art Reference Library

### 1. Curated & 100% Distinctly Titled Spoin Reference Files
Every artwork in these collections has been individually analyzed, given a **100% DISTINCT, unique, descriptive one-liner `TITLE`**, deduplicated, and verified for instant visual comprehension:

- [`use_for_gags.txt`](./use_for_gags.txt) (**888 high-clarity curated artworks, 888 unique titles**):
  - Expressive character reactions, funny animals, comic figures, reaction faces (`(o_o)`, `(-_-)`, `(>_<)`, `t(o.o)t`, `\o/`, `(9'-')9`), memes, caricatures, and comedic props.
  - Best for: Scroll-stopping card hooks, character dialogues, and visual jokes that dramatize an idea.
- [`use_for_informative_visualization.txt`](./use_for_informative_visualization.txt) (**1,599 high-clarity curated artworks, 1,599 unique titles**):
  - Computers & hardware (monitors, disks, servers, consoles), books, scrolls, checklists, tools, everyday objects, nature/space, scales, clocks, and technical symbols.
  - Best for: Concrete concept illustrations, process diagrams, hardware comparisons, and informative visual anchors.
- [`examples.txt`](./ascii_art_library/examples.txt) (**42 Worked Few-Shot Generation Prompt Examples**):
  - **21 Gag Card Examples** covering all 21 live database topics.
  - **21 Informative Card Examples** covering all 21 live database topics.
  - Designed for direct injection into Spoin's flashcard generator prompts.

### 2. Generator Rule: Sourcing & Minor Adaptations
As documented in [`TODO_GENERATOR_PROMPTS.md`](./TODO_GENERATOR_PROMPTS.md):
1. **Base Sourcing**: The generator LLM must fetch its base ASCII art strictly from `use_for_gags.txt` or `use_for_informative_visualization.txt`.
2. **Permitted Minor Changes**: The generator LLM is allowed to make minor, tasteful adaptations to fit the specific card:
   - **Trimming irrelevant side items** (e.g. trimming off extraneous darts or a scoreboard from a circular target to leave a pristine 10m target).
   - **Adding labels / text annotations** (e.g. `[SUB-SIX HOLD]`, `[PUB KEY]`, `[PRIV KEY]`, `TTL: 60s`).
   - **Adding simple direction arrows or speech callouts**.
   - **Strict $\le 40$ width limit** on every single line of the final adapted artwork.

### 3. The 40-Column Width & High-Clarity Rules
Per [ADR-0021](../../docs/adr/0021-ascii-scene-library.md) and `_ASCII_MAX_WIDTH = 40` in [langchain_impl.py](../api/src/spoin/generation/langchain_impl.py#L509):
- Mobile displays render approximately 38–42 monospace columns.
- **Strict Width Limit**: Every single line of stored artwork is $\le 40$ characters wide.
- **High-Clarity Filtering**: Ambiguous, cryptic, or visually noisy cards (e.g. obscure Usenet doodles, repetitive text strings, unreadable character soup) are excluded.
- **Zero 90-Degree Sideways Emotes**: Sideways smileys (`:-)`, `:-(`, `;-P`, etc.) are eliminated in favor of upright kaomoji and multi-line upright drawings.
- **100% Unique Titles**: 0 duplicate titles exist across either curated file.

### 4. Output Format
Each artwork card is formatted with a metadata header containing an explicit descriptive title and fenced in triple-backticks (```` ``` ````) so the LLM generation prompt can unambiguously reference and copy pieces:

```text
=== ID: 4281fd4f37a99519 | TITLE: Mermaid sitting on rock ledge surrounded by sea foam | ARTIST: Joan G. Stark (Spunk) | CATEGORY: mythology | SUBCATEGORY: mermaids | SIZE: 36x13 ===
```
                          _.._
                     ___.'    '.
                    (  (____/`\ \
 ,     ,`\           \(' |')' )  )
/ \   /`  |           /  _\= _/  (
|' `-'  ^ /   ___.-. (_.'  )  \   )
 \: ^    /  ,;   |/-'(  \     `\  (
  '-.:.^<  /:   ^/    `--`_     ;  )
      `|:\ |  ^ / .     (` \,-| |_(
       |.:/:.   `\__.---'`-'  '_|
        \':' ^   /-'         / ,'
    jgs  `.^:. ^/           ( \
           `'--`            '\/
```
```

---

## 📁 Library Directory Structure (`ascii_art_library/`)

- `examples.txt`: 42 worked few-shot prompt examples across all 21 live DB topics (21 gags + 21 informative).
- `use_for_gags.txt`: Curated, distinctly titled gag collection (888 cards, 888 unique titles).
- `use_for_informative_visualization.txt`: Curated, distinctly titled informative collection (1,599 cards, 1,599 unique titles).
- `_all_categories_library.txt`: Consolidated master reference file containing all 3,505 valid raw artworks.
- `_summary.txt`: Summary of total artworks and per-category breakdown.
- `_library_manifest.json`: Machine-readable JSON manifest of all categories and card counts.
- `<category>.txt`: 32 individual category-specific reference files.

---

## 🚀 Running the Tools

### 1. Scrape the entire archive:
```bash
python apps/helpers/scrape_ascii_art.py
```

### 2. Run visual analyzer, generate titles, and converge curated files:
```bash
python apps/helpers/curate_spoin_art.py
```

### 3. Generate DB topic few-shot prompting examples:
```bash
python apps/helpers/generate_db_topic_examples.py
```
