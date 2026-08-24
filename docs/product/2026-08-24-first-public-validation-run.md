# First public validation run: Reddit, 2026-08-24

Not an ADR (no decision made here) and not a task (nothing here is yet scoped as work) --
this is raw external signal, captured because it's the first real feedback from outside the
project, and the instinct with feedback like this is to let it evaporate in a chat log
instead of writing it down. If any of the "worth acting on" items below turn into real work,
they should get a proper task doc under `docs/tasks/` at that point, linking back here for
the "why."

## What went out

The same underlying pitch, posted as three separate threads with different framing, across
three subreddits:

- **r/sideprojects** -- "Would you like an app where..." framing
- **r/SideProject** -- "I'm building an app for replacing [doomscrolling]..." framing
- **r/ProductivityHQ** -- posted under a `ProductivityHQ DEV` community-dev flair

All three linked back to the same product (Spoin): swipeable learning cards, gated by
difficulty-tiered quizzes, AI-generated content pipeline with human review during cold
start.

## What came back

### 1. "How is the content generated, and can users post it themselves?" (r/sideprojects, bitterchocolate26)

Asked directly how content generation works and whether it's purely one-directional (app owner
-> users) or whether users can contribute. Answered in-thread: content today is AI-generated
via the pipeline, grounded against real facts, with human review (currently just the
founder) checking the majority of cards for each newly-generated topic -- explicitly framed
as the cold-start solution while there's no user base yet to source content from. Once
there's a user base, the plan is to open content submission per-topic, verified by the
system before going live -- same shape as [ADR-0004](../adr/0004-topic-canonicalization.md)'s
existing topic-request flow, just extended to card-level content, not just topic requests.

### 2. Quiz-gating is friction that competes directly with the zero-friction alternative (r/SideProject, Neat-Ad-4224)

The most substantive critique of the batch. Paraphrased: if passing a quiz is the only way
to unlock more content, that's homework with extra steps, and doomscrolling wins by default
because it asks nothing of the user. Suggested the feed itself should feel more scroll-native
-- short cards, one swipe at a time -- with the quiz as a lightweight periodic check rather
than a wall blocking progress. Warned that gating too hard means people bounce back to actual
doomscrolling the moment they hit a question they don't feel like answering.

Answered in-thread: quiz-gating is real but is 10 questions (9 MCQ + 1 free-text, 80% to
pass) and is **not** a hard wall on scrolling itself -- it's required only to *advance
difficulty*, not to keep swiping within a tier. A wrong answer links back to the specific
card that taught it. Reaching 100% progress on a topic requires clearing all three
difficulty-tier quizzes at least once, but nothing stops a user from staying at one
difficulty and scrolling indefinitely without ever taking a quiz.

**Worth noting as a possible gap between what the product does and what the pitch
communicated:** the critique reads as though the commenter believed quiz-gating blocks
scrolling itself, not just difficulty advancement. If that's a common first impression from
the pitch/landing copy rather than a one-off misread, that's a messaging problem worth
checking, independent of whether the actual gating mechanic (ADR-0009) needs to change.

### 3. Topic suggestions (r/SideProject, Neat-Ad-4224)

Explicitly asked for topics that are "genuinely bite-sized and not already better served by
YouTube": psychology/cognitive biases, how everyday things actually work (their examples:
wifi, car engines), and history deep-dives on specific weird events rather than broad
subjects. Founder's reply committed to adding history deep-dives on specific weird events.
(Separately, "how everyday things work" was generated as a real topic the same day this
feedback came in -- see the generation run logged in this session's conversation history,
not otherwise documented here.)

### 4. "It needs to be community-based, not just app-owner content" (r/ProductivityHQ, ashraf_bashir)

Same underlying ask as (1), phrased as a requirement rather than a question. Answered with
the same long-term-goal explanation: the shared topic-request pool already works today (any
user can request a topic and see others' requests, per the current `custom_topic_limit`-free
flow -- [task 0024](../tasks/0024-reintroduce-custom-topic-limit.md)); user-authored
*card* content, verified by the system before going live, is the next step once there's a
user base to draw from.

### 5. "Where can I download the app?" (r/ProductivityHQ, s-ai-d)

Direct download interest with no caveats -- the simplest possible positive signal. Answered
honestly: no app yet, currently focused on getting 50-100 good preset topics ready and
testing on web first; app is a dedicated near-term commitment, not a maybe. Offered to notify
on web launch.

### Passing signal, not yet engaged in-thread

- **Know-Your-Self** (r/sideprojects): wants to learn philosophy on the platform -- another
  topic-suggestion data point, same shape as (3).
- **Neat-Ad-4224** (follow-up): asked what recorder/screen-capture app was used for the demo
  video in the post -- meta question about the pitch material itself, not the product.

## Aggregate read

Three threads, cross-posted same day: 5 upvotes on the ProductivityHQ post at last check,
active replies within 1-4 hours on every thread, zero hostile or dismissive responses. Every
substantive comment either asked a clarifying question that had a real answer ready (content
generation, community content, download timing) or offered a specific, actionable critique
(quiz-gating friction) or specific, actionable requests (topic suggestions). No comment
suggested the core premise (swipeable cards + gated quizzes) was a bad idea outright.

## Worth acting on, if this pattern holds up

Nothing here is scoped as a task yet -- flagging only what a second data point might turn
into work:

- The quiz-gating friction critique (item 2) suggests checking whether onboarding/pitch copy
  makes "gates difficulty tier, not scroll" clear enough on first contact.
- Topic-suggestion pattern (items 3, and Know-Your-Self's philosophy ask) points toward
  "bite-sized, not already well-served by YouTube" as a real curation heuristic worth writing
  down somewhere durable if it keeps recurring across future feedback -- candidate for
  `content-model.md` or a topic-curation doc, not decided here.
- Community/user-generated content (items 1 and 4) came up unprompted in 2 of 3 threads --
  worth treating as the actual signal for how strongly discovered users want the long-term
  content-sharing plan already described in `content-model.md`'s "Custom topics" section,
  not just a hypothetical.

## Founder's log, unfiltered

s-ai-d asked "Where can I download the app? It does seem interesting!" and produced zero
caveats, zero snark, zero "cool idea but." A stranger, on the actual internet, wanted the
actual thing. `n=1`, no confidence interval, no p-value, does not clear any statistical
bar whatsoever -- and it is, currently, the single best metric in this entire project,
`spoin_db`'s 753-active-card Bhagavad Gita topic included. The gate that rejects "too basic
for advanced" nine times in a row has nothing on one (1) human wanting to download an app
that does not yet exist.

Logged here under the same "why, not what" discipline as every other doc in this repo,
except the "why" this time is just: it felt really good, actually, and future-me deserves
to remember that this is what day one of real users looked like.
