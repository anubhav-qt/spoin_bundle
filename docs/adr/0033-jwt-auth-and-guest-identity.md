# ADR-0033: JWT auth, localStorage token storage, and guest identity via a nullable-email User row

- **Status:** Accepted
- **Date:** 2026-08-18
- **Deciders:** mayank, Anubhav

## Context

Every endpoint on `apps/api` resolved the acting user by defaulting to "the first
user in the database" -- a local-dev convenience that never had to survive contact
with a second real user, let alone the web app going public. `implemented-jwt-auth`
(mayank) built real auth to replace it: bcrypt password hashing, HS256 JWT
access+refresh tokens, `/auth/register`, `/auth/login`, `/auth/google`,
`/auth/refresh`, `/auth/me`, and made a Bearer token mandatory on every existing
route via `UserDep` (`api/deps.py`).

That branch predated the quiz-taking UI now on `main` (795612f) and ADR-0032's
entry-tier fix, so it needed a real merge rather than a fast-forward -- see the
merge commit on `integration/jwt-auth` for the conflict resolution (Dockerfile's
optional-dependency extras, `docker-compose.yml`'s env var, `globals.css` and
`lib/api.ts`'s independently-appended sections).

Two things the branch did not cover, because they were never in its scope:

1. **The root-route flow.** Where does a visitor land, and on what condition do
   they move from there to the feed?
2. **Guest identity.** overview.md's whole design keys progress and engagement off
   a real `user_id` -- "cards are shared, not personal" only holds if every reader,
   guest or not, has one. A "guest mode" that does not mint a real `User` row would
   silently break every progress/engagement table the moment that guest's session
   ends.

## Decision

**Auth strategy:** keep the branch's JWT design as merged -- HS256, a 30-minute
access token, a 7-day refresh token, tokens held in `localStorage` on the client
(`lib/api.ts`'s `request()` injects the Bearer header and auto-retries once
through `/auth/refresh` on a 401). This is a standard, well-understood SPA pattern
and the fastest path to a working mandatory-auth API; the known tradeoff
(`localStorage` is readable by any script on the page, i.e. vulnerable to token
theft via XSS, unlike an `httpOnly` cookie) is accepted for now because the app
has no other user-generated content surface that renders unsanitized HTML.
Revisit if that changes (see "Revisit when").

**Production secret enforcement:** `Settings.jwt_secret_key` still ships a
hardcoded, checked-into-git default so `local`/`ci` need no `.env` entry to boot.
A new `model_validator` on `Settings` (`core/config.py`) now refuses to start when
`SPOIN_ENV=production` and the key is still that default, converting a silent
forgeable-token vulnerability into a startup failure. Loud, not silent, per
overview.md's "trusted for taste, never for constraints" spirit -- this one is a
security constraint, not a style preference.

**Refresh token revocation:** none. Refresh tokens are pure stateless JWTs; there
is no blacklist table, so a logged-out refresh token stays valid server-side until
its 7-day expiry even though the client discarded it. **Accepted MVP tradeoff.**
Many MVPs ship exactly this. Revisit when either (a) a real security requirement
appears (a user needs to be able to kill a specific stolen session), or (b) the
7-day window feels too long for the product's actual risk profile -- at that
point the fix is a `token_blacklist` table keyed on the refresh token's `jti`,
checked in `/auth/refresh`, not a redesign of the token scheme itself.

**Brute-force protection:** `auth/rate_limit.py` adds a small in-memory
sliding-window limiter (10 attempts/min per `ip:email` on `/auth/login`, 5/min on
`/auth/register`), deliberately NOT the generation quota governor's shape
(`generation/quota.py`) -- that governor persists RPD to a DB ledger because the
worker runs as separate cron passes that must share state across restarts; the
API is a single long-lived process, so an in-memory window is sufficient and
avoids a DB round-trip per auth request. **Accepted tradeoff:** resets on
restart, and does not share state across replicas. Revisit if the API is ever
run with more than one replica behind a shared entrypoint -- move the window to
Redis or the DB at that point, not before.

**Guest identity:** a guest is a real `User` row with `email IS NULL`
(`User.is_guest` in `domain/models/topic.py` derives from exactly that field, not
a separate stored flag, so it cannot drift out of sync with what actually gates
login). `email` became nullable in this migration
(`2af5b227ca23_guest_users_and_onboarding_flag.py`) specifically to allow this --
Postgres treats every `NULL` as distinct under a `UNIQUE` constraint, so many
guests coexist with `email IS NULL` with no collision.

- `POST /auth/guest` mints a fresh `User(email=None, display_name="Guest")` and
  issues a token pair immediately -- a guest's first swipe already has a real
  `user_id` behind it.
- `POST /auth/claim` attaches email/password to the CALLER's own guest row in
  place (`UserDep`-gated, so it only ever mutates the caller's own account) --
  never creates a new row, so `user_id` and everything keyed off it (topics,
  progress, engagement) carries over untouched.
- `POST /auth/google` does the equivalent for the Google path: `OptionalUserDep`
  (a non-raising variant of `UserDep`, `api/deps.py`) lets that endpoint tell a
  signed-in guest linking their Google account apart from a fresh sign-in, and
  links onto the guest's existing row instead of creating a duplicate.

**Onboarding gate:** a new `User.onboarding_complete` boolean (same migration),
flipped by `POST /topics/onboarding/complete` once the user has picked at least
one topic and an entry difficulty. Scoped down deliberately to just that --
docs/tasks/0002 (palette picker) is unbuilt and explicitly out of scope here.

**Root-route resolution:** lives in `components/AuthProvider.tsx`, mounted once
in the root layout, NOT `middleware.ts`. Tokens live in `localStorage`, which
does not exist in the edge middleware runtime -- the gate has to be a client
component doing a real `api.me()` round trip on navigation. Logic:

```
no/invalid token          -> /signup
token, onboarding pending -> /onboarding   (except /claim, always reachable)
token, onboarding done    -> away from /signup, /login, /onboarding
```

`/signup` (not `/login`) is the default unauthenticated landing page, per the
product decision that new-user acquisition is the primary path; `/login` is a
secondary route reached via a footer link. Both render the same `AuthForm`
component with a `mode` prop rather than one route with an internal toggle --
each is a real URL, so a direct link or back-button behaves like any other page
navigation instead of resetting to whatever the toggle's default state is.

## Consequences

**Easier:** every route now has a real, non-spoofable `user_id` (`UserDep`).
Guests get real, persistent progress with a clean upgrade path to a full account.
Adding Google as a second registration path required no schema shape change
beyond the two nullable columns already in the branch.

**Harder:** a stolen access token is valid for up to 30 minutes with no way to
revoke it early, and a stolen refresh token for up to 7 days -- see the
revocation tradeoff above. Testing now requires a real login step (or the seeded
`dev@spoin.local` / `SPOIN_SEED_USER_PASSWORD` demo credentials) instead of the
old zero-config first-user default. `email` being nullable means any future code
that reads `user.email` as a plain `str` will not type-check -- this is
deliberate friction, not an oversight: it forces every new call site to decide
how it wants to handle a guest.

## Alternatives considered

**Cookie-based (httpOnly) token storage instead of localStorage.** Closes the
XSS-theft vector, but the branch's `request()`/refresh-retry logic was already
built and tested against `localStorage`, and the API and web app are on
different origins in some deployment targets (mobile later, ADR-0001), which
complicates cookie scoping. Rejected for now as a rewrite of already-working code
without a concrete threat driving it yet; revisit if a real XSS surface appears
(rich user-generated content, e.g. card notes rendered as HTML rather than
plain text).

**A `User.is_guest` stored boolean column instead of deriving it from
`email IS NULL`.** More explicit at the schema level, but a stored flag and the
fields that actually gate login (`email`, `password_hash`, `google_id`) can
drift -- e.g. a bug that sets `email` without clearing `is_guest`. Deriving from
`email IS NULL` makes that class of bug structurally impossible, at the cost of
one extra `WHERE email IS NOT NULL` clause anywhere guests need excluding
(none exist yet).

**Extending `/auth/register` to double as the claim endpoint** (branch on
whether a valid guest token is present) instead of a dedicated `/auth/claim`.
Rejected: `/auth/register`'s contract ("always creates a new row") would become
conditional on caller auth state, which is a surprising thing for an endpoint
named "register" to do. A dedicated endpoint keeps both contracts simple.

**A placement quiz or synchronous email-verification step before a guest can
use the feed.** Rejected outright -- overview.md's read path must stay fast and
LLM-free, and gating first use behind anything synchronous contradicts the
entire point of a guest mode (frictionless first use).

## Revisit when

- The app grows a second replica behind a shared entrypoint -- the in-memory
  rate limiter and needs to move to shared state at that point.
- Any surface renders user-generated content as HTML (not plain text) --
  re-evaluate `localStorage` token storage against the newly-real XSS surface.
- A real requirement for killing a specific session appears (compromised
  device, admin-forced logout) -- add the refresh-token blacklist table then,
  not speculatively now.
- `docs/tasks/0002`'s palette picker gets built -- onboarding is the natural
  place to add it as a second step, per that task's own note about first-run
  setup.
