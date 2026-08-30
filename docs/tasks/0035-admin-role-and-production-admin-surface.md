# Task 0035: A real admin-role gate for `/admin/*` (and `/dev/*`)

**Owner:** unassigned
**Blocked on:** nothing (but low priority until there's a reason to run `/admin/*` in production)

## The problem

`GET /admin/quota` (B4, `feat/v1-finish-line`) and `/dev/reset` are both mounted
only when `settings.env != "production"` (`api/main.py`). That gate is a
placeholder: it works because nobody needs these in production *yet*, not
because non-production access is the right boundary.

There is no admin/role concept in the system. `deps.py` resolves a JWT to a
`UUID`; every authenticated user is equal. So the moment `/admin/quota` needs to
be reachable in production (to actually watch quota on the deployed stack — the
thing B4 exists for), the `env` gate has to come off, and then every signed-in
user can read the key count, the model ladder and daily spend patterns.

## What to build

- An `is_admin` (or a small role enum) on `User`, plus a migration. Seed the
  owner account.
- An `AdminUserDep` in `deps.py` — same as `UserDep` but 403s a non-admin.
- Move `/admin/*` (and reconsider `/dev/*`) to that dependency, and drop the
  `env != "production"` special-case in `api/main.py` for `/admin` once the role
  check is the real boundary.
- The Phase 4 deploy checklist item "`routers/dev.py` disabled in production,
  verified by a test" stays true for `/dev/*`; `/admin/*` becomes
  "role-gated, verified by a test" instead.

## Why it's separate

B4's endpoint is useful now on the local/staging stack behind the `env` gate.
Building a role system is a bigger, orthogonal piece that shouldn't block a
read-only quota view. This is the follow-up that makes `/admin/*` a real
production surface.
