# `corpus/` — the curated source of truth

Authored by Antigravity under the owner's supervision, following
[`../procedure.md`](../procedure.md). Ingested into `the_spoin_universe` (ADR-0088)
and retrieved at generation time to ground both the card writer and the verifier
(ADR-0089).

Laid out by the hierarchy:

```
<category>/<sub_category>/<survey-or-topic>/<document>.md
```

The `sub_category` level is omitted entirely when a subject has none. The directory
is organisational convenience for humans — **the front matter is authoritative**, and
the ingester reads the fields, not the path. Keep them consistent anyway; a mismatch
is a review signal that something is misfiled.

Empty until the first authoring run lands.
