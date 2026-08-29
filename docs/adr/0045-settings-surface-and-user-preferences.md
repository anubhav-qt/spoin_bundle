# ADR-0045: A Settings surface, with preferences on the user row and no parallel system

- **Status:** Accepted (partially superseded — see note)
- **Date:** 2026-08-21
- **Deciders:** mayanks0ni

> **Partially superseded by [ADR-0070](0070-server-side-appearance-preferences.md)
> (2026-08-30).** The "rendering preferences stay client-side" half of the Decision no
> longer holds for the **palette** and the **font**: F4/F5 turn those into user-authored
> content (named saved themes, an imported font file), which moves to the server with
> `localStorage` demoted to a pre-paint cache. ADR-0070 is the case this ADR's "Revisit
> when" anticipated ("both pre-paint *and* cross-device"). Everything else here stands —
> `daily_card_goal` on `app_user`, reduced-motion in `localStorage`, no `/preferences`
> router, the export endpoint, the four unbuilt sections.

## Context

"Settings" had been a stub in the left rail since the shell was built — rendered,
`aria-disabled`, no handler. Building it raised a question the codebase had never had to
answer: **where does a user preference live?**

Two answers already existed, neither written down. The palette and font pickers
(ADR-0012, ADR-0023/0037) persist to `localStorage` and apply themselves via a `<body>`
attribute set by a pre-hydration script. Everything else about a user — display name,
age, avatar — is a column on `app_user`, written through `PATCH /profile/me`.

The obvious third answer, a `/preferences` router with its own table, would have been a
parallel system: a second place a client asks "what is true about this user," and a
second write path to keep consistent with the first.

A second question came from the template this surface was specified against, which
assumed sections this product has no machinery for. Deciding what *not* to build was the
larger part of the work.

## Decision

**A preference is stored where its blast radius is.**

- **Learning data goes on the user row**, through the existing `PATCH /profile/me`.
  `daily_card_goal` is a column on `app_user` and rides along on `UserOut`, so the client
  reads it from the `/auth/me` payload `AuthProvider` already fetches on every
  navigation — no request of its own, no new router, one write path.
- **Rendering preferences stay client-side**, in `localStorage` behind a `<body>`
  attribute, exactly like the palette and the font. They change how *this browser* draws
  the page; putting them behind a network round trip would make the app render wrong for
  one frame on every load to gain nothing.

**Reduced motion needs both halves to be real.** A CSS rule
(`body[data-reduced-motion="1"] *`) covers transitions and keyframes. It cannot touch
Framer Motion, which animates by writing inline styles every frame — inline style beats
any stylesheet rule — so `AppShell` also passes the preference to `<MotionConfig
reducedMotion>`. The switch can only turn motion **off**: `prefers-reduced-motion: reduce`
is honoured independently and always, so this is an opt-in for someone whose OS says
otherwise, never an opt-out of the OS setting.

**`GET /profile/me/export` is a real endpoint, not a button.** Six indexed queries
returning the user's own topics, notes, likes, saves and daily activity. It deliberately
returns no card *bodies*: the corpus is shared content, the user's relationship to it is
what is theirs to take. The client turns the JSON into a download; the endpoint stays
usable from a script or the API docs.

**Four sections were specified and not built**, because building them would have meant
inventing the functionality they front:

| Not built | Why |
|---|---|
| Notification toggles | There is no delivery system in the codebase — no scheduler, no push registration, no mail transport. Every toggle would be wired to nothing. |
| Change password | `password_hash` exists; no endpoint changes it. Adding one is authentication work (ADR-0033's territory), not a settings row. |
| Global difficulty | Difficulty is per-topic and progression-driven (`DIFFICULTY_MIX`, ADR-0010; each topic's own tier, ADR-0027). A global override is a rewrite of feed selection wearing a settings-row costume. Surfaced as a per-topic pointer instead. |
| Delete account | No endpoint, and CLAUDE.md gates destructive capabilities behind explicit owner approval. |

"Light / Dark / System" was likewise not added: this product's theming is five committed
palettes plus a custom one (ADR-0012, ADR-0016), and a parallel mode system would have
been a second theme mechanism, not an exposure of the existing one.

## Consequences

**Easier**

- Adding a learning preference is a column plus a field on two Pydantic models. No new
  router, no new client fetch.
- Settings reuses `ThemePicker`, `FontPicker` and `TopicDiscoveryModal` unchanged, so
  there is exactly one topic-management surface and one palette picker in the product.
- Reduced motion is now honest: the setting visibly does what it says, including to the
  `AnimatePresence` transitions in Saved.

**Harder**

- `UserOut` grows with every learning preference, and it is fetched on every navigation.
  That is fine for scalars and would not be for anything large — the same reasoning that
  made `avatar_image` a deferred column with a denormalised `has_avatar_image` flag
  beside it.
- Preferences now live in two places by design, so "where is this stored" is a question
  with a rule rather than an answer. The rule is the Decision's first line.
- Client-side preferences do not follow the user to a second device. Accepted: a palette
  that follows you across devices is a smaller win than a palette that never flashes.

**Committed to**

- No `/preferences` router and no preferences table. A learning preference is a column on
  `app_user`; a rendering preference is `localStorage` plus a `<body>` attribute.
- The export endpoint returns the user's own rows only, never shared corpus content.
- No settings row is shipped for functionality that does not exist behind it.

## Alternatives considered

**A `user_preference` key/value table.** Flexible, no migration per preference. Rejected:
it trades a typed column and Pydantic validation for stringly-typed values validated
nowhere, and it is the parallel system the Decision exists to avoid. With a handful of
scalars, the migration cost it saves is roughly zero.

**Reduced motion as a server-stored preference.** Consistent with the daily goal, and
rejected for the same reason the palette is not server-stored: it must apply before the
first paint. Reading it from an API response means the page animates once, then stops.

**Building notification toggles against a stub.** Considered because the section was
explicitly specified. Rejected — a switch that persists a boolean nothing reads is worse
than an absent section, because it makes a promise to the user.

## Revisit when

- A real notification system exists. Then the section is built against it, and this ADR's
  table is the record of why it waited.
- A preference needs to be both pre-paint *and* cross-device. That is the case this split
  does not handle, and it would need a cookie or a server-rendered attribute — a genuinely
  different mechanism, not a tweak to either half.
- `UserOut` starts carrying something a navigation-time fetch should not.
