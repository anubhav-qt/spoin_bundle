# Task 0046: In development, the feed's first page is served and thrown away

- **Status:** Open, found 2026-10-11 while verifying Phase 10 of [task 0045](0045-hono-port.md)
- **Scope:** development only. Production builds do not double-invoke effects.
- **Related:** [ADR-0010](../adr/0010-feed-serving.md) (pagination as one integer into the plan)

## The problem

`next.config.ts` sets `reactStrictMode: true`, so in `next dev` React mounts every
component, unmounts it and mounts it again. Two effects that call a stateful endpoint on
mount therefore call it twice:

- **The feed.** `Feed.tsx`'s mount effect runs `loadPage(true)` twice, so `GET /feed` goes
  out twice with no position. The server's `page()` (`apps/server/src/feed/service.ts`)
  advances `feed_plan.position` and every `feed_slate.position` on each call. The web keeps
  only the second response (`loadRequestId`), so the cards the first call served are never
  shown and the slates have already moved past them. They are not lost for good: they stay
  UNSEEN and come back when the slate is rebuilt. But the first page a reader sees is
  really page two.
- **The quiz.** `QuizModal.tsx` runs `startQuiz` on mount, so `POST /topics/{id}/quiz/start`
  creates two attempts and the first one is never submitted.

Seen in the browser: a tierless topic's slate was built easy first (beginner 0-3, then
intermediate, then advanced), yet its first visible page started at intermediate. That is
the bug, not the feed's ordering.

## Why it matters

Every feed and quiz change is checked in `next dev`, and a check that shows page two as
page one makes the ordering rules (ADR-0010, a tierless topic's easy-first slate) look
broken when they are not. The next person to test the feed will chase it again.

## What to do

The owner picks the fix. Cancelling the first request in the browser is **not** enough:
by the time it is cancelled the server has already moved the positions. Candidates:

1. **A guard in the web.** A ref that marks the first load as started. React keeps refs
   across Strict Mode's remount, so the second mount sees it and skips. Same for the quiz
   start. Smallest change; touches only `apps/web`.
2. **An idempotent first page on the server.** For example, a request key the client sends
   with a reset load, so a repeat gets the same page back instead of the next one. Fixes it
   for every client, including a flaky mobile retry, at the cost of a contract change.
3. **Turn `reactStrictMode` off.** Loses the checks it exists for.

Also check whether an abandoned, unsubmitted quiz attempt counts against anything (a daily
limit, a cooldown, progress); if it does, the quiz half is not development-only.

## Hand back

The chosen fix, and a run in `next dev` (`npm run stack`, http://localhost:3001) showing
one `GET /feed` and one `quiz/start` on mount, with a tierless topic's first page starting
at its easiest cards.

## Timebox

Half a day for option 1; a day for option 2 with its tests.
