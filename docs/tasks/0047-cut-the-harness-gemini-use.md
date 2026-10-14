# Task 0047: Cut the harness's Gemini use

- **Status:** Open, written 2026-10-14, when the owner's weekly Gemini limit was nearly spent
  during the stage-by-stage review of [task 0045](0045-hono-port.md)'s harness
- **Scope:** the authoring harness (`apps/server/src/agents/`, `apps/server/src/harness/`) and
  its prompts. Every chat runs on Gemini 3.8 Flash through CLIProxyAPI's Antigravity accounts,
  so one weekly limit covers the whole harness.
- **Related:** [ADR-0108](../adr/0108-nim-is-a-tool-the-writer-calls.md) (what NIM writes),
  [ADR-0110](../adr/0110-the-maps-are-checked-in-code-and-audited.md) (maps and their audit), task 0045's "Decided during the port"

## The problem

C++ for Monke's research stage (stage 2) took 51 million input tokens in 47 minutes, and the
three-topic run before it 81 million in 52 minutes. A few such runs nearly spent the owner's
weekly limit, and stage 2 is only the start of a topic: documents, cards, questions and art
follow. Most of it is one chat, the tadpole, sending its whole chat again with every turn.

## How to read the numbers

- **Uncached** is pi-ai's `usage.input`; **cached** is its `usage.cacheRead`. Both are on each
  assistant message in `chat_message`. `model_call.prompt_tokens` holds only the uncached part,
  so the run monitor's "prompt tokens" column understates a chat's real size.
- We don't yet know how Antigravity's weekly limit counts cached tokens (see open item 1).
  Until we do, treat both as cost: a cached token is cheaper for Google, but it may still count.
- Times are UTC unless marked IST.

## What the runs measured

| Run | Length | Tadpole uncached / cached / out | Helpers uncached / cached / out | toad_sage uncached / cached |
|---|---|---|---|---|
| Stage 2, three topics (`spoin_stage2`, 2026-10-14 08:30 to 09:22, stopped by the owner for waste) | 52 min | 3.79M / 69.2M / 119k (Rust alone 1.95M / 50.3M) | 2.24M / 5.1M / 77k | 224k / 184k |
| Stage 2, C++ for Monke (`spoin_cpp`, 09:30 to 10:19) | 47 min | 3.76M / 37.0M / 109k | 1.56M / 8.8M / 34k | 62k / 0 |
| C++ widened to mastery (`spoin_cpp`, 11:01 to 11:27, stopped at the weekly limit) | 26 min | 0.91M / 29.5M / 58k | 0.74M / 2.6M / 11k | 93k / 0 |

The tadpole sent 80 to 90% of all input in each run. A tadpole turn carried about 148k tokens
in the first C++ run, 195k in the widening and 248k for Rust; a helper turn carried about 41k.
The audit itself is cheap: the first C++ run's 31 auditor calls took 216k tokens in and 18k
out, and its 85 web searches 11k in and 62k out. What costs is the tadpole turns each audit
round leads to.

Earlier runs, from the session's reports:

- **The first live run, Rust (2026-10-13, live database), from 16:12 IST:** Gemini made 1,292
  calls with 18.7M uncached in and 2.64M out; NIM made 76 calls with 2.0M in and 328k out.
  Gemini's output went to the correctors (753k, more than twice everything NIM wrote), the tier
  writers (510k), the verifiers (416k), the document writers (343k over 288 calls) and the main
  chats (about 500k). Every Antigravity account ran out of Gemini at 20:19 IST with Rust
  unfinished.
- **designer_toad's redraws (night of 2026-10-13):** 82 calls averaged 121k uncached plus 126k
  cached. Some missed the cache entirely, at 262k to 274k uncached each. Its prompts had grown
  to 412k tokens because every screenshot was sent again with every call.
- **The first live run, System Design (2026-10-13 morning):** started with no NIM key, so every
  writer ran on Gemini (235 calls, none on NIM).

## Done

| What the runs showed | What changed | Commit |
|---|---|---|
| Writers ran on Gemini when the NIM key was missing | The worker refuses to start without `NVIDIA_NIM_API_KEY` | task 0045, "NIM writes, Gemini orchestrates" |
| NIM was waited on for small fixes: 900 tokens took five minutes | NIM writes the big first try; a writer's follow-up calls go to Gemini | 0c3579a, 9898ffc |
| Nine NIM writes were cut at the 240 s silence limit, paid for and lost | A NIM call gets 900 s of silence, and NIM writes in text | 261d255, 26438b9 |
| Gemini wrote first drafts | A tier's first cards and questions are NIM's alone | 989d886 |
| The correctors wrote 753k of Gemini's 2.64M output | Each draft's pass-1 correction moved to NIM | 6a7d054 |
| One bad item refused a whole batch, so the batch was written again | Passing items are kept and only faulty ones go back; a refused document's sections are kept as its try | ea8903b, 3361a06 |
| A rewrite resent every section to fix one sentence | A rewrite sends only the sections it changes | e0c0bb9 |
| A 4-minute stop threw away 19 NIM writes in flight | A stop drains: each chat finishes and stores the step in flight | d6e7a63 |
| Chats carried every stage before into the next | A chat at 100k tokens or more compacts while it waits for others | 3e6d060 |
| designer_toad's prompts reached 412k tokens of resent screenshots | Each screenshot is shown once, and the designer's chat was started over by hand with an owner-written summary | 25ec23a |
| designer_toad spent turns reading records instead of drawing | Its record tools were taken away | 37a2a4f |
| The art ran on Gemini | designer_toad draws on Claude Opus 5.5, five pieces a call, off the Gemini limit | ebd4eb3, 69bf629 |
| System Design's tadpole researched alone for an hour at 200k+ tokens a turn, hunting ISBNs for books it couldn't fetch | The tadpole has no web tools; helpers, at about 41k a turn, do the web | f4e58e8 |
| Bot-check pages ("Just a moment...") were stored as content | fetch refuses them | f4e58e8 |
| Five runs failed at once on a 5-second database queue, each losing an answer already paid for | The worker's pool is bigger and waits up to a minute | 283953c |
| The embedder blocked the main thread, so fetches took 10 to 170 s and some timed out | The embedder runs in its own thread | ce7e435 |
| A compaction cut the tool list, which broke the cache: about 1.2M uncached tokens for each one, plus turns spent on refused calls | A compaction run is sent the same tools, and code refuses the ones that don't save. The widening run's compaction read about 400k tokens from cache | 298e2a3 |
| A claim naming a domain that isn't in map A cost a whole audit round to find, twice | write_map and change_map refuse it when it is written | 298e2a3 |
| The Core Guidelines page was cut at 400,000 characters with nothing to say so, so its later sections needed a new fetch | fetch keeps up to 2,000,000 characters and says when it cuts | 3c84cbc |

## Open

Ordered by how much each could save, as far as the numbers show. None of these is decided:
each is the owner's call.

1. **Find out what the weekly limit counts.** If cached tokens count in full, the size of the
   tadpole's context is the cost, and items 2 and 3 matter most. If only uncached tokens and
   requests count, the number of turns matters more. To find out, read the proxy's quota before
   and after a measured run.
2. **A smaller tadpole context.** At 148k to 248k tokens a turn, each tadpole turn costs as much
   as several helper runs. A chat compacts at 400k tokens while running and at 100k only when it
   ends a turn waiting, so through a long stage it runs near its peak. Options: compact sooner
   while running, have big reads (a whole map C of 243 claims, every audit finding) return less
   or only what changed, or keep finding-fixing out of the tadpole's chat (open item 3).
3. **Fewer audit rounds in the tadpole's chat.** The first C++ run took nine audits (79, 9, 3,
   1, 0, 20, 2, 1 and 0 findings). About a third of the fixes swapped in another passage that
   still didn't say the claim, so the auditor flagged it again (`misc_smart_pointers_are_slow`
   was flagged four times). The 20-finding round came from items changed while fixing the first
   round. Options: a helper, with its small chat, fixes a round's findings against the stored
   passages and reports back; or the auditor's finding names the passage that would settle it.
4. **designer_toad starts each batch fresh.** Each batch (list, draw, render, attach) stands
   alone, so it needs no history: a call would carry about 15k to 30k tokens instead of about
   250k. Proposed 2026-10-14 and never decided. It now costs the Claude subscription rather than
   Gemini, but the saving holds.
5. **Low or medium thinking.** The owner's standing rule is medium for every Gemini call; the
   stage 2 review ran at low (`GEMINI_THINKING=low`) to save tokens. Whether low holds quality
   is not settled: the first C++ run passed inflated source tiers and 169 of 170 claims at high
   confidence, but there is no medium run of the same topic to compare against.
6. **Model calls record the cached part.** `model_call` keeps only uncached tokens, so the
   monitor and any weekly sum from it leave out most of the input. It should store cache reads
   too.
7. **A compaction keeps the ids its next steps need.** Right after the widening run's compaction,
   the tadpole made up ten page ids in one big change_map. Code refused it and nothing was
   stored, but the call and its retry were paid for. The summary could keep the ids of the
   records and pages it was working on.
8. **Stale wakes.** On the widening rerun, the tadpole woke first for its old go-on review and
   spent a turn learning there was nothing to do (12 s, one turn at full context). Small, and
   it happens only when a run is restarted by hand.
9. **NIM's balancer is per writer.** When NIM refuses one writer with a 429, the others don't
   learn it and keep asking. Harmless at three writers, and NIM isn't the Gemini limit, but it
   wastes NIM's queue time at more.

## What to hand back

For each open item taken on: the change, and one run's numbers beside the matching run above
(same topic and stage, same thinking level), so the saving is measured rather than assumed.

## Timebox

Item 1 first, within a day, since it decides the order of the rest. Then one item per run.
