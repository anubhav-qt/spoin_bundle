# ADR-0070: Appearance preferences move to the server, with `localStorage` demoted to a pre-paint cache

- **Status:** Proposed
- **Date:** 2026-08-30
- **Deciders:** Anubhav
- **Amends:** [ADR-0045](0045-settings-surface-and-user-preferences.md) (reverses its
  "rendering preferences stay client-side" split for the palette and font)
- **Builds on:** [ADR-0012](0012-feed-visual-design.md),
  [ADR-0023](0023-reader-font-selection.md), [ADR-0037](0037-site-wide-font-picker.md),
  [ADR-0033](0033-jwt-auth-and-guest-identity.md)

## Context

The v1 finish line adds two things the current appearance pickers cannot hold
(`docs/handoff/v1-finish-line-plan.md`, items F4 and F5):

1. **F4** — an arbitrary number of *named, user-saved* themes listed beside the built-in
   presets, not the single `custom` slot `ThemePicker` has today.
2. **F5** — a font *imported by the user* (a `.woff2`/`.ttf`/`.otf` file) that persists in
   the picker across sessions.

Both are user-created content, not a single scalar choice. A saved theme is four colours
plus a name; an imported font is a binary file plus a name. Keeping either in
`localStorage` means:

- it does not follow the user to a second device or a second browser — a person who
  spends five minutes tuning a palette loses it the moment they open the app on their
  phone;
- the imported-font *bytes* live in `localStorage` (or IndexedDB) on exactly one machine,
  and there is no path to the future React Native client, which per CLAUDE.md must be able
  to do everything the web client can;
- it is business logic — "what themes has this user created" — living in `apps/web`, which
  the "no business logic in the web app" rule exists to prevent. The palette/font
  `localStorage` writes were the one place that rule was already being bent; F4/F5 would
  bend it much further.

**[ADR-0045](0045-settings-surface-and-user-preferences.md) decided the opposite.** Its
rule — "a preference is stored where its blast radius is" — put *learning* data
(`daily_card_goal`) on the `app_user` row and kept *rendering* preferences (palette, font,
reduced-motion) client-side, explicitly rejecting both a `/preferences` router and a
`user_preference` table. Its reasoning was sound for what it faced: a handful of scalars,
where a network round trip before first paint buys a cross-device win smaller than the
cost of a one-frame flash of the wrong theme. Its "Revisit when" names this exact moment:
*"A preference needs to be both pre-paint and cross-device. That is the case this split
does not handle."* F4/F5 is that case, and it also changes the shape of the data from
"a scalar" to "a list of user-authored records + a blob", which is past what a `<body>`
attribute can carry regardless.

One thing that is **not** a problem, contrary to an early reading in the finish-line plan:
a guest is a real `app_user` row (`/auth/guest`, ADR-0033), and `/auth/claim` attaches
email/password to that *same row* in place. So a guest can own a `user_preference` row
like anyone else, and claiming an account carries it over for free — there is no
guest→claimed data migration to write.

## Decision

**The palette, any user-saved palettes, the font choice, and any imported fonts move
to the server, keyed by `user_id`. `localStorage` stays — as a pre-paint cache that is
reconciled against the server, never as the source of truth.**

### Storage — one row per user, typed columns, not a key/value bag

A new `user_preference` table, one row per `app_user` (`user_id` PK + FK
`ON DELETE CASCADE`), created lazily on first write:

| Column | Type | Holds |
|---|---|---|
| `user_id` | uuid PK / FK | the owner |
| `palette` | text | the active palette key: a built-in (`notebook`…) or `custom:<uuid>` |
| `custom_palettes` | jsonb | `[{id, name, bg, fg, accent, accent2}]` — the user's saved themes |
| `font` | text | the active font key: a built-in (`literata`…) or `import:<uuid>` |
| (imported fonts) | own table | see below |

`custom_palettes` is `jsonb` and not its own table on purpose: it is a small
(realistically < 20 entries), always-read-and-written-whole list with no query needs of
its own — the same call that reads a user's preferences wants all of it. This is the one
place the ADR-0045 "typed column, not stringly-typed values" rule is relaxed, and it is
relaxed narrowly: the four colours and the name are validated by a Pydantic model on the
way in, so the `jsonb` is schema-checked at the boundary even though Postgres sees it as a
document.

Imported fonts get a real table, `user_font`, because they carry a **binary payload** and
a per-file lifecycle (uploaded, validated, referenced, deleted):

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | referenced as `import:<id>` from `user_preference.font` |
| `user_id` | uuid FK, `ON DELETE CASCADE` | owner; every read is scoped to the caller |
| `name` | text | the user's label for it |
| `format` | text enum | `woff2` \| `ttf` \| `otf` — sniffed from magic bytes, not the filename |
| `bytes` | bytea, **deferred** | the font file; deferred for the same reason `avatar_image` is (ADR-0045 "Harder") — the list endpoint must never pull payloads |
| `byte_size` | int | denormalised so "how big" needs no blob load |
| `created_at` | timestamptz | |

Size cap: **2 MB per file**, checked before the row is written. Type is validated by
magic number (`wOF2`, `\x00\x01\x00\x00`/`true`/`ttcf`, `OTTO`) — the file is arbitrary
binary handed to the browser's font parser, historically a memory-safety target, so the
extension is not trusted.

### API — a preferences pair on the existing profile surface, not a new router

Per ADR-0045's "no parallel system" instinct, which still holds: this goes under the
profile surface, not a `/preferences` router.

- `GET /profile/me/preferences` → `{palette, custom_palettes, font, imported_fonts: [{id, name, format, byte_size}]}`. No blobs.
- `PUT /profile/me/preferences` → replaces the scalar/JSON fields (`palette`, `custom_palettes`, `font`). Whole-object PUT, not PATCH: the client always holds the full picture and a partial write has no use here.
- `POST /profile/me/fonts` (multipart) → validates magic bytes + size, stores a `user_font`, returns its metadata.
- `GET /profile/me/fonts/{id}` → streams the bytes with `Content-Type: font/woff2` (etc.) and a long `Cache-Control` (the id is content-immutable). This is the `src:` the client's `@font-face` points at.
- `DELETE /profile/me/fonts/{id}` → removes it; if `user_preference.font` referenced it, the server resets `font` to the default in the same transaction so a load never dangles.

Every font route is `user_id`-scoped in the query itself — a font id belonging to another
user 404s, it is not merely hidden. This is wired the twice-enforced way (a router-level
dependency *and* an architecture test that the font query filters by caller) because it is
the first per-user binary the API serves.

`daily_card_goal` and reduced-motion **stay exactly where ADR-0045 put them**
(`app_user` / `localStorage` respectively). This ADR moves the palette and the font, and
nothing else — reduced-motion in particular is pure pre-paint with no cross-device value,
which is still ADR-0045's case, not this one.

### Pre-paint — `localStorage` is the cache the inline script paints from

The flash-of-wrong-theme is the whole risk, so the mechanism is explicit:

1. The inline script in `app/layout.tsx` runs before React and before any fetch can
   return. It paints from `localStorage["spoin-palette"]` / `["spoin-custom-colors"]` /
   `["spoin-font"]` exactly as today — this is the **last-known-good** value.
2. `AuthProvider` already fetches `/auth/me` on every navigation. Preferences ride **on
   that payload** (a `preferences` object on `UserOut`), so there is no extra request. The
   `imported_fonts` list is metadata only (id/name/format/size), so it stays a scalar-ish
   payload — the ADR-0045 "`UserOut` grows and is fetched every navigation" caution is
   respected; the blobs are never in it.
3. When that resolves, the client reconciles: if the server value differs from what the
   inline script painted, it applies the server value and rewrites the `localStorage`
   cache to match. A change made on another device shows up one navigation later, not
   instantly — accepted, and far better than painting it wrong every load.
4. A logged-out visitor and a brand-new guest before their first write have no server
   row; the inline script's `localStorage` read is authoritative for them, and the
   defaults (`notebook` / `literata`) apply when even that is empty. A guest's first
   preference write creates their row; `/auth/claim` keeps it.

Imported fonts need their bytes to render, and those are not in `localStorage`. The
client registers each imported font as an `@font-face` whose `src` is
`GET /profile/me/fonts/{id}` (with credentials); until that request returns, text in that
face falls back down the stack (`font-display: swap`). An imported font therefore *can*
FOUT on a cold load in a way a built-in cannot — this is the accepted cost of not putting
font blobs in `localStorage`.

### Writes are click-to-save, both pickers

Selecting a theme or a font applies it live **and** immediately `PUT`s the new
preferences (optimistic; the `localStorage` cache is updated in the same tick so a
reload during a failed request still shows the choice). This is already how `ThemePicker`
behaves; [ADR-0071](0071-drop-font-keep-revert.md) brings `FontPicker` to the same model
and retires its Keep/Revert step.

## Consequences

**Easier**

- The palette and every saved theme follow the user to any device and to the future
  mobile client, which gets them from the same `/profile/me/preferences` call.
- "What themes has this user made" is server state with a typed boundary, not logic in a
  component.
- The guest→claimed transition needs zero migration code: same row, `email` gets set,
  the `user_preference` row is untouched.

**Harder**

- `UserOut` grows by a `preferences` object and is fetched on every navigation. Mitigated
  by keeping blobs out of it (font list is metadata only), but it is strictly more than
  ADR-0045 wanted on that payload — if it ever needs to carry more, `preferences` moves
  to its own lazily-fetched call.
- A preference change on device A is visible on device B only after the next `/auth/me`,
  i.e. the next navigation — a real regression from `localStorage`'s instant local write,
  accepted because the alternative is a wrong first paint.
- Imported fonts can FOUT on a cold load (bytes come from an authenticated request, not
  `localStorage`). Built-in faces are unaffected.
- The API now serves user-uploaded binaries. That is a new security surface (size cap,
  magic-byte sniffing, per-user query scoping, `Content-Disposition`/`Content-Type`
  discipline) and Phase 3's security pass has to cover it.
- Two ADRs (this one, 0071) and back-pointers in 0045/0037 — the cost of reversing a
  deliberate decision out loud instead of quietly.

**Committed to**

- One `user_preference` row per user (typed columns + one validated `jsonb` list), a
  `user_font` table for imported binaries, and a preferences pair under `/profile/me` —
  **not** a `/preferences` router (ADR-0045's instinct there still stands).
- `localStorage` remains, as a pre-paint cache that is always reconciled against the
  server and never trusted over it.
- Reduced-motion and `daily_card_goal` do not move — ADR-0045's split still governs
  everything except the palette and the font.
- Per-user font reads are enforced twice (dependency + architecture test).

## Alternatives considered

**Leave it in `localStorage` (ADR-0045 unchanged), add IndexedDB for the font blob.**
Simplest, no migration, no endpoint. Rejected: it doubles down on device-local rendering
config at exactly the moment the data stops being a scalar and starts being
user-authored content, it strands the imported font on one machine, and it gives the
mobile client nothing. ADR-0045's own "Revisit when" points here.

**A generic `user_preference` key/value table** (the thing ADR-0045 rejected). Still
rejected, for ADR-0045's reason: stringly-typed values validated nowhere. This ADR uses
typed columns; the single `jsonb` list is schema-checked by Pydantic at the boundary.

**A `/preferences` router.** Rejected — ADR-0045's "second place a client asks what is
true about this user" argument is still correct. Preferences ride the `/auth/me` payload
for reads and sit under `/profile/me` for writes, next to `daily_card_goal`.

**Store imported fonts as base64 in the `user_preference` JSON.** Rejected: it puts
megabytes of binary on the `/auth/me` payload (ADR-0045's exact "not for anything large"
caution), defeats HTTP caching of the font file, and conflates "my settings" with "my
uploads" — which have different lifecycles (a font is validated, referenced, GC'd).

**Server-render the palette as an inline `<style>` / cookie so it is pre-paint AND
cross-device with no flash.** This is the mechanism ADR-0045's "Revisit when" gestures at.
Rejected for v1 as too big a change to the render path (the app is a client-rendered SPA
shell; making the palette server-authoritative at the HTML level is a Next middleware +
cookie design of its own). The `localStorage`-cache-then-reconcile approach accepts a
one-navigation lag on cross-device changes to avoid that. If that lag proves annoying,
this is the thing to build.

## Revisit when

- The `preferences` object on `UserOut` needs to carry something a navigation-time fetch
  should not — then it splits into its own lazily-fetched endpoint.
- The one-navigation lag on cross-device preference changes proves annoying in real use —
  then the server-rendered-cookie palette is the next step.
- A third client (mobile) ships and reveals an assumption baked into the web reconcile
  flow that should have been server-side.
- Imported-font storage in Postgres `bytea` becomes a size problem (many users, many
  fonts) — then it moves to blob storage (R2), the same call B7's study-material uploads
  will make.
