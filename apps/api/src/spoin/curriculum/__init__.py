"""Projecting authored curricula from `the_spoin_universe` into `Topic`/`Subtopic`.

Deterministic, no model call anywhere (docs/architecture/authored-curriculum.md §8).
The curriculum file is the truth; `make curriculum-ingest` parses it into the universe
tables; this package makes `spoin_db_2` follow them.
"""
