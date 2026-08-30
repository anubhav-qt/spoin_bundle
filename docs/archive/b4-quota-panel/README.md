# Archived: the B4 quota read surface

**Removed from the live tree 2026-08-30 (session 6).** Owner's call: a whole page
(and an API endpoint behind it) is not worth maintaining when the same
information is one SQL query away, and the quota tables are already the source of
truth every process reads.

This directory is the verbatim code as it was mounted, kept so bringing it back
is copy-paste + re-wire, not reconstruction from history.

## What was here

| File | Was at | What it did |
|---|---|---|
| `admin.py` | `apps/api/src/spoin/api/routers/admin.py` | `GET /admin/quota` router, `env != "production"` gated |
| `quota_report.py` | `apps/api/src/spoin/generation/quota_report.py` | `read_quota_status()` — read-only assembly of one row per `(key, model)` cell from `quota_ledger` / `quota_request` / `model_unavailable` |
| `page.tsx` | `apps/web/app/admin/quota/page.tsx` | dev-only Next route: three ADR-0065 rollup tiles, a 33-square key strip, the parked-models list |
| `test_admin_quota.py` | `apps/api/tests/` | 4 API tests |

Also removed when this was pulled: `QuotaCellOut` / `ParkedModelOut` /
`QuotaStatusOut` from `apps/api/src/spoin/api/schemas.py`, the `QuotaCell` /
`ParkedModel` / `QuotaStatus` interfaces and `api.adminQuota()` from
`apps/web/lib/api.ts`, and the `admin.router` mount + import in
`apps/api/src/spoin/api/main.py`.

## Checking quota state with SQL instead

The three ADR-0065 conditions, kept separate (never OR them into "exhausted"):

```sql
-- today's per-cell daily spend, and which cells hit their ceiling
select backend, requests_spent, exhausted_at, cooldown_until
from quota_ledger
where day = date_trunc('day', now() at time zone 'utc')
order by backend;

-- cells throttled per-minute right now (transient, daily budget still has room)
select backend, count(*) as reqs_last_min
from quota_request
where sent_at > now() - interval '1 minute'
group by backend
order by reqs_last_min desc;

-- models parked by a provider outage
select model, excluded_at, expires_at, reason from model_unavailable;
```

## If you want it back

Task [0035](../../tasks/0035-admin-role-and-production-admin-surface.md) (real
admin-role gate) is the prerequisite for running any of this in production. To
restore: move the three code files back to their original paths, re-add the
schemas and the `lib/api.ts` block, re-mount `admin.router` in `main.py`, and
move `test_admin_quota.py` back to `apps/api/tests/`.
