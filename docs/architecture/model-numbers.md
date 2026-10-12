# What breader and Seelie learned about Gemini and NIM

Gathered on 2026-10-13 so spoin builds on what breader and Seelie found out rather than probing
again (task 0045, "No provider probes before building"):

- **breader:** `origin/dev` at `60dfeaf`. The files are `ai/tools/nim.ts`, `balancer.ts`,
  `kimi.ts`, `proxy.ts` and `harness.ts`, plus `shared/src/accounts.ts`, their tests and their
  commits.
- **Seelie:** `E:\oms`. The files are `src/lib/seelie/`, `tmp/seelie-handoff.md` and
  `tmp/product-studio-plan.md`.

Neither repo keeps its call log in git. breader's `ai/work/_calls.jsonl` is on the Mac. So what
follows is what their code, notes and commits say. The raw calls aren't here.

## NIM (breader)

- **Limits:** NVIDIA publishes none and sends no limit headers. Nobody has seen a daily cap. Forums
  put the limit at 40 to 60 requests a minute per model, and breader's marker never reached it.
- **What goes wrong:**
  - queues, sometimes minutes before the first token;
  - "overloaded";
  - a 504 from the gateway after 300 s with nothing sent;
  - outages that last hours, such as Kimi K3's from 9 to 11 September 2026.
- **Calls at once:** Kimi K3 (reasoning high) and Nemotron 3 Ultra take 24 each in breader's
  marker.
- **`max_tokens`:**
  - On 10 October, Kimi K3 refused anything over 1,048,576 and counted the prompt in that limit.
    Nemotron took any number.
  - On 11 October, NVIDIA capped Kimi at 131,072 without notice.
  - spoin asks for 130,000 and asks again for what a refusal allows. This is ported.
- **Empty answers:** Kimi sometimes answers one prompt empty while answering others.
  - breader moves to the next model after 3 empty answers.
  - A part Kimi answered empty 6 times keeps Nemotron's marks.
- **Smaller calls:** Kimi answers a smaller version of a call it kept refusing whole. breader cuts
  the book by fifths before it moves to another model.
- **Garbage mid-answer:** Kimi can drift into gibberish halfway through an answer. breader judges
  the stream every 1,000 characters and hangs up.
- **One strike per cooldown:** calls that fail together in one cooldown count as one strike.
  Otherwise they all go to Nemotron at once.
- **DeepSeek V4.1 Flash** was dropped on 5 October for taking about 5 minutes to its first token.
- **Forced tool choice** (spoin's own finding, Phase 8): Kimi K3 refuses a forced `tool_choice`
  while it thinks, with a 400.

In spoin, the balancer, its cooldowns, the token cap and the re-ask after a refusal are ported
(`apps/server/src/models`). The stream judge and the smaller calls are not ported. Both are
specific to marking books.

## Gemini through Antigravity (breader, Seelie, spoin)

- **The model:** `gemini-3.8-flash-high` is the only name served. Each call picks low, medium or
  high thinking. breader and Seelie run it at high, and spoin at medium.
- **Account limits:**
  - Each Antigravity account has a 5-hour limit and a weekly limit for its Gemini models. They
    can be read through the proxy's management `api-call` (breader's `shared/src/accounts.ts`,
    Seelie's `limits.ts`).
  - When every account is used up, breader's harness waits for the first one to fill again.
  - While the proxy or the network is down, it looks again every minute.
- **breader's fallback:**
  - Flash goes first. If Flash has been cooling for longer than 120 s, or has failed twice in a
    row, the next Gemini model that isn't cooling takes the call: the newest version first, the
    bigger model first.
  - Waits double with each failure in a row, with jitter: a rate failure from 60 s up to 30 min,
    a busy one from 30 s up to 10 min.
  - A sign-in that is turned away ends the run.
- **A hidden cap:** the image model (`gemini-3.1-flash-image`) stopped after about 9 images with a
  429, "resets after 2h12m", and the quota APIs didn't change. No hidden cap has been seen on the
  text models.
- **Tools:**
  - `googleSearch` can't share a request with function tools: it answers 400. So Seelie searches
    in a separate call.
  - `urlContext` answers 200 but fetches nothing. spoin uses SearXNG and its own fetch.
- **Input:** all of these work on `gemini-3.8-flash-high`:
  - images;
  - inline mp4, in a user turn and in a tool result, sound included;
  - YouTube links as `fileData`.
- **Today's date:** without it in the prompt, the model searches as if it were an older year.
- **Speed:**
  - spoin's grader takes about 4.7 s a call, with about 1.1k tokens in and 240 to 390 out, at
    medium thinking.
  - Seelie's image model takes 9 to 14 s at 1K and 34 s at 4K.
- **Compaction:**
  - Seelie compacts at 60% of the window and keeps the last 3 runs word for word.
  - breader compacts at 400k tokens and keeps the latest turns, up to 20% of the chat, word for
    word.
  - spoin uses Trotter's: 400k tokens or 60% of the window, whichever is smaller, with no runs
    kept word for word.
- **Tool calls:** Seelie starts every tool call in a reply at once. Reads run in parallel, and
  changes run one at a time in the order asked. Trotter runs every call one at a time.

## breader's tests, against spoin's

spoin's `models.test.ts` and `model-grader.test.ts` cover:

- a 429 cooling its model;
- a refused key dropping the model;
- a refusal for asking too much;
- empty and cut answers as a single call sees them;
- the call log.

breader also tests these, which spoin's balancer does but no spoin test checks:

- jitter;
- waits doubling up to their cap;
- a patient call never giving up, and one that isn't patient stopping after its tries;
- three empty answers sending the call to the next model;
- a patient process asking a refused key again an hour later.

breader tests these, which spoin has no code for yet:

- a limit or quota is a rate failure however it's worded;
- a sign-in turned away stops the run;
- falling back across Gemini models;
- reading each account's limits, and waiting for one to fill again.
