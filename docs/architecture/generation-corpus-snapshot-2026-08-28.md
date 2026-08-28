# Generation Corpus Snapshot — 2026-08-28

## Snapshot Metadata

- **Date:** 2026-08-28
- **Source Database:** `spoin_db` (PostgreSQL 17 with pgvector)
- **Backup File Path:** `e:\spoin_backups\spoin_db_corpus_2026-08-28.dump`
- **File Size:** 21,395,150 bytes (~21.4 MB)
- **SHA-256:** `5C88F8CFD7CC2A8A8FD83B13F454C1E22E16312BEA9D359C1B32272457D24DC5`
- **Format:** Custom (`--format=custom --compress=9`)

## Verified Row Counts

Restored and verified against scratch database `spoin_db_v1_verify`:

| Table | Row Count |
|---|---|
| `topic` | 75 |
| `card` | 14,470 |
| `question` | 14,182 |
| `app_user` | 27 |
| `engagement_event` | 10,056 |

## Prompt Version Distribution in Snapshot

- `gen_meta->>'prompt_version' IS NULL` (v1): 9,002 cards
- `gen_meta->>'prompt_version' = '2'` (v2): 2,259 cards
- `gen_meta->>'prompt_version' = '3'` (v3): 3,209 cards
