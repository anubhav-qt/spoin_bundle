# Curating the ASCII reference library — batch review instructions

**Read this whole file before starting.** This is the manual review
[Task 0030](../../../docs/tasks/0030-manual-review-curated-ascii-library.md) asks for.
Entries `0`–`188` are already done as the worked reference
(`decisions/0000-0188.tsv`) — match their style. Your job is entries **189–2486**.

## Why this exists (read this or you will do the wrong job)

The library's own header claims every entry has a *"100% DISTINCT, rich,
search-friendly descriptive TITLE."* That claim is **false**, and understanding
exactly how it is false is the whole point of this task:

- **80% of gag titles and 91% of informative titles end in a `(WxH)` size suffix** —
  they are the original scraped asciiart.eu captions with dimensions appended. `Web
  (21x10)`, `Gard (34x5)`, `Olfo (26x7)`, `Obasciililthingy (39x17)`, `Nice (34x6)`.
- **77% of entries (1,938) share a title with another entry** once that suffix is
  stripped. The suffix is the *only* thing making them "distinct." Actual counts:
  50 entries titled `geometric decorative graphic design pattern`, 40 titled `little
  mouse with round ears and curly tail`, 40 `medieval knight longsword with ornate
  crossguard and pommel`, 33 `domestic cat sitting in graceful silhouette with curved
  tail`. Titles were applied **per subcategory**, not per artwork.

This matters because of what the titles are *for*. `apps/api/src/spoin/content/
ascii_library.py` embeds every title and ranks candidates by cosine similarity against
the card planner's `asset_direction`. Forty mice with the same title all embed to
nearly the same vector, so a mouse-ish query burns its entire 10-candidate budget on
one subject and the generator never sees the other 2,447 pieces. **A title that does
not distinguish its artwork from its neighbours is worse than useless — it actively
hides the rest of the library.**

## Setup

```bash
cd /e/spoin_bundle
python apps/helpers/curation/prep.py /tmp/entries.json
```

`entries.json` is the parsed, index-ordered union of both files (2,487 entries;
indexes `0`–`2486`; gags are `0`–`887`, informative `888`–`2486`). **Indexes are
stable** as long as the two source `.txt` files are untouched — do not edit them while
reviewing.

## The loop

```bash
# dump a batch (start index, art-line budget ~470 keeps a batch readable)
python apps/helpers/curation/dump.py /tmp/entries.json 189 470
```

It prints each entry as `#<index> [src/category/subcategory] <id> :: <current title>`
followed by the art, and finishes with `NEXT=<index>` — the start of your next batch.

**Look at every single artwork.** Then write one decision line per index into a new
file `apps/helpers/curation/decisions/<start>-<end>.tsv`, tab-separated:

```
189	RETITLE	Owl perched on a branch with wide round eyes
190	KEEP
191	DELETE	unclear
192	ASK	Mild innuendo — keep or drop?
```

Commit a decisions file per batch as you go. Never edit the two `.txt` files by hand;
`apply.py` regenerates them at the end.

## The four actions

### `RETITLE` — the default, expect ~75% of entries

Write what the artwork **actually shows**, as if describing it to someone who cannot
see it. Rules:

1. **Lead with the subject noun.** "Owl perched on…", not "An image of an owl…"
2. **6–14 words.** Under 4 words fails `verify.py`.
3. **Include what distinguishes it from its siblings** — pose, orientation, count,
   viewing angle, notable features. When you are on the 40th mouse, that is the entire
   job: `Mouse standing upright nibbling a crumb`, `Mouse curled asleep with its tail
   wrapped around it`, `Mouse seen head-on with large round ears`, `Two mice facing
   each other on their hind legs`.
4. **No dimensions, no artist names, no `(WxH)`.** `apply.py` rejects these.
5. **No filler.** `verify.py` rejects `in distinct wildlife posture`, `expressive
   pose`, `practical tool utility everyday object`, `apparel wardrobe fashion garment
   accessory`, `pop culture television and cinema character`, `geometric decorative
   graphic design pattern`. These phrases describe nothing.
6. **Name a recognisable character when you are confident** — the project explicitly
   wants pop-culture hooks (`TODO_GENERATOR_PROMPTS.md`), so `Scooby-Doo sitting with
   floppy ears and a long snout` beats `Cartoon dog sitting`. But still describe the
   visual, so the title works for a model that does not know the character.
7. **Write it as a retrieval target.** The question to ask is: *if a planner wrote
   "a scene showing X", would this title be the nearest match?*

### `KEEP` — expect ~15%

Only when the existing title already satisfies every rule above. Most one-line kaomoji
entries (indexes 0–20) qualify. **A title ending in `(WxH)` can never be KEEP** —
`apply.py` hard-fails on it.

### `DELETE` — expect ~5-10%. Reason must be one of:

- `nsfw` — sexual or suggestive. **Delete every entry in these subcategories
  outright:** `naughty`, `sexual/other`, `sexual/women`, `playboy`, `bikinis`,
  `underwear`, `nightwears`. Also the entry titled `Nude Beach Volley Ball! ;)`
  (index 1414) and the middle-finger gesture (index 868).
- `unclear` — **you cannot confidently say what it depicts.** This is the most
  important delete rule and you should use it without hesitation. If you have to
  squint or guess, a reader on a phone has no chance. Deleting is correct here;
  do NOT use `ASK` to avoid making this call.
- `broken` — truncated, a fragment, or mostly an artist signature rather than art.
- `duplicate` — pixel-identical to an entry you already kept (there are 2 such pairs).
- `unsuitable` — clear and safe but has no plausible use illustrating a learning
  concept.

### `ASK` — use sparingly, expect well under 50 across the whole library

Only for **genuine judgment calls about suitability**, not for "I can't tell what this
is" (that is `unclear`). Legitimate examples: alcohol/tobacco imagery, mild innuendo,
religious iconography, real-world weapons, anything politically loaded. Put the actual
question in the payload. `apply.py` refuses to run while any `ASK` remains, so these
must be resolved by a human before the library can be rebuilt.

## Known systematic issues — apply consistently

| Issue | Count | What to do |
|---|---|---|
| `(WxH)` suffix in title | ~2,187 | Always strip; rewrite the title underneath it |
| Shared per-subcategory titles | 1,938 | Rewrite each to distinguish it from its siblings |
| NSFW subcategories | 33 flagged | `DELETE nsfw` per the list above |
| Duplicate IDs | 18 | `apply.py` auto-suffixes them; no action needed |
| `U+00A0` NO-BREAK SPACE in art | 12 entries | `apply.py` strips them; no action needed |
| Artist signature inside the art (`jgs`, `snd`, `hjw`, `ejm97`, `mrf`, `b'ger`) | many | Leave it — it is small and part of the artwork. Only `DELETE broken` if the signature IS most of the art |
| Legitimate Latin-1 shading chars (`°`, `·`, `¯`, `´`) | 21 entries | **Not corruption.** Leave alone. They may render as `?` in a Windows terminal — that is a display artifact, not a file problem |

## Finishing

```bash
python apps/helpers/curation/apply.py /tmp/entries.json \
    apps/helpers/curation/decisions \
    apps/helpers/use_for_gags.txt \
    apps/helpers/use_for_informative_visualization.txt

python apps/helpers/curation/verify.py \
    apps/helpers/use_for_gags.txt \
    apps/helpers/use_for_informative_visualization.txt
```

`apply.py` refuses to write unless **every one of the 2,487 indexes has a decision**
and no `ASK` remains. `verify.py` then enforces the 40-column budget, title
uniqueness, near-duplicate titles (same words reordered), no leftover `(WxH)`, no
filler phrases, no duplicate IDs, no NBSP, and a 4-word minimum.

**Then sync the packaged runtime copy** — generation reads this one, not
`apps/helpers/`:

```bash
cp apps/helpers/use_for_gags.txt \
   apps/helpers/use_for_informative_visualization.txt \
   apps/api/src/spoin/content/ascii_library_data/
cd apps/api && python -m pytest tests/test_ascii_library.py -q
```

That test asserts the width budget and non-empty titles/art across the whole packaged
library, so it is the last gate before the curated library goes live.
