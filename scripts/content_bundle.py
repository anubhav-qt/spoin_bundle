"""Move the generated corpus -- topics, subtopics, cards, questions -- between two
local `spoin_db` instances.

    python scripts/content_bundle.py export
    python scripts/content_bundle.py import spoin-content-bundle.json.gz

The corpus is expensive (every card cost real quota -- see
docs/architecture/generation-pipeline-run-2-benchmark.md) and it is *shared*:
cards are generated once and served to everyone who qualifies, so nothing in
these tables is personal to whoever generated them. That makes the corpus
exactly the kind of thing worth copying to a teammate's stack rather than
burning another day of quota regenerating there.

What moves -- the corpus tables, in FK order:

    topic -> topic_alias -> topic_edge -> subtopic -> card -> question

What deliberately does not move: everything user-scoped (app_user, user_topic,
card_stats, engagement, quiz_attempt, user_topic_progress, quota_ledger,
generation_job) and `rejected_card`, which is generation diagnostics rather than
content. The two corpus fields that *point* at user-scoped data are neutralised
on import -- `card.author_id` is nulled and `topic.subscriber_count` reset to 0
-- so the importing side is not left holding counters that describe users it has
never heard of.

Import is strictly additive: every insert is `ON CONFLICT DO NOTHING`, so it can
never overwrite or delete a row the target already has, and re-running it is a
no-op. That is a deliberate limit rather than an unfinished feature -- CLAUDE.md's
"The database" makes mutating existing `spoin_db` content something only its
owner can authorise, and a script run by someone else cannot stand in for that.
Primary keys are preserved, which is what makes the re-run safe and what lets two
stacks refer to the same card by id.

Both sides must be on the same schema. The bundle records the `alembic_version`
plus the full `format_type` of every exported column, and import aborts on any
difference (`--force` downgrades that to a warning). That is the "same main
branch, fully fetched" precondition -- checked, rather than assumed.

Runs on the host against the docker-compose `db` service's published port. The
only dependency is `asyncpg`, which the API already uses.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg

#: FK order. Import walks it forwards; any other order fails on a foreign key.
TABLES: tuple[str, ...] = (
    "topic",
    "topic_alias",
    "topic_edge",
    "subtopic",
    "card",
    "question",
)

#: Corpus columns that reference rows this bundle does not carry. Applied on
#: import only -- the export stays a faithful copy of the source.
IMPORT_OVERRIDES: dict[str, dict[str, Any]] = {
    "card": {"author_id": None},
    "topic": {"subscriber_count": 0},
}

DEFAULT_DSN = "postgresql://spoin:spoin@localhost:5432/spoin_db"
DEFAULT_PATH = "spoin-content-bundle.json.gz"
FORMAT_VERSION = 1

#: json_populate_recordset coerces every value through the target column's own
#: input function, so `vector` arrives back from its "[0.1,...]" text form, jsonb
#: and arrays as themselves, and enums as their labels -- no per-type ladder here.
_INSERT_SQL = (
    "INSERT INTO {table} SELECT * FROM json_populate_recordset(NULL::{table}, $1::json) "
    "ON CONFLICT DO NOTHING"
)


def _safe_dsn(dsn: str) -> str:
    """The DSN goes into the bundle for provenance; its password does not."""
    parts = urlsplit(dsn)
    if parts.password is None:
        return dsn
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = f"{parts.username}:***@" if parts.username else ""
    return urlunsplit((parts.scheme, f"{user}{host}", parts.path, "", ""))


async def _schema_fingerprint(conn: asyncpg.Connection) -> dict[str, dict[str, str]]:
    """Every exported column and its fully-qualified type, e.g. `vector(384)`.

    Comparing this rather than a bare column-name list is what turns an embedding
    dimension change -- the one drift that would otherwise import cleanly and then
    quietly poison similarity search -- into a hard failure.
    """
    rows = await conn.fetch(
        """
        SELECT c.relname AS table_name,
               a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS column_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = ANY($1::text[])
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY c.relname, a.attnum
        """,
        list(TABLES),
    )
    fingerprint: dict[str, dict[str, str]] = {}
    for row in rows:
        fingerprint.setdefault(row["table_name"], {})[row["column_name"]] = row["column_type"]
    missing = [table for table in TABLES if table not in fingerprint]
    if missing:
        raise SystemExit(
            f"error: {', '.join(missing)} not found in this database -- is it migrated "
            "(`docker compose up seed`), and is --dsn pointing at spoin_db?"
        )
    return fingerprint


async def _alembic_version(conn: asyncpg.Connection) -> str | None:
    revision = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    return str(revision) if revision is not None else None


def _compare_schemas(
    manifest: dict[str, Any],
    target_revision: str | None,
    target: dict[str, dict[str, str]],
) -> list[str]:
    problems: list[str] = []

    bundle_revision = manifest.get("alembic_version")
    if bundle_revision != target_revision:
        problems.append(
            f"alembic revision differs: bundle {bundle_revision!r}, "
            f"this database {target_revision!r}"
        )

    for table in TABLES:
        want: dict[str, str] = manifest["schema"][table]
        have = target[table]
        for column, column_type in want.items():
            if column not in have:
                problems.append(f"{table}.{column} is in the bundle but not in this database")
            elif have[column] != column_type:
                problems.append(
                    f"{table}.{column} type differs: bundle {column_type}, "
                    f"this database {have[column]}"
                )
        for column in have:
            if column not in want:
                problems.append(f"{table}.{column} exists here but is not in the bundle")
    return problems


def _open(path: str, mode: str) -> Any:
    return gzip.open(path, mode) if path.endswith(".gz") else open(path, mode)


# -- export -----------------------------------------------------------------


async def _export(dsn: str, path: str, drop_embeddings: bool) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        fingerprint = await _schema_fingerprint(conn)
        revision = await _alembic_version(conn)

        vector_columns = {
            table: [col for col, kind in cols.items() if kind.startswith("vector")]
            for table, cols in fingerprint.items()
        }
        if drop_embeddings:
            for table, columns in vector_columns.items():
                for column in columns:
                    fingerprint[table].pop(column, None)

        tables: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            records = await conn.fetch(f"SELECT to_jsonb(t) AS row FROM {table} t ORDER BY t.id")
            rows = [json.loads(record["row"]) for record in records]
            if drop_embeddings:
                for row in rows:
                    for column in vector_columns[table]:
                        row.pop(column, None)
            tables[table] = rows
            print(f"  {table:<12} {len(rows):>6} rows", file=sys.stderr)
    finally:
        await conn.close()

    counts = {table: len(rows) for table, rows in tables.items()}
    bundle = {
        "manifest": {
            "format_version": FORMAT_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": _safe_dsn(dsn),
            "alembic_version": revision,
            "tables": list(TABLES),
            "embeddings_included": not drop_embeddings,
            "schema": fingerprint,
            "counts": counts,
        },
        "tables": tables,
    }

    with _open(path, "wb") as handle:
        handle.write(json.dumps(bundle, ensure_ascii=False).encode("utf-8"))

    size_mb = os.path.getsize(path) / 1_000_000
    print(
        f"\nwrote {path} -- {sum(counts.values())} rows, {size_mb:.1f} MB, schema {revision}\n"
        f"hand this file over; on the other machine:\n"
        f"  python scripts/content_bundle.py import {os.path.basename(path)}",
        file=sys.stderr,
    )


# -- import -----------------------------------------------------------------


async def _import(dsn: str, path: str, force: bool, dry_run: bool, chunk: int) -> None:
    with _open(path, "rb") as handle:
        bundle = json.loads(handle.read().decode("utf-8"))

    manifest = bundle.get("manifest", {})
    if manifest.get("format_version") != FORMAT_VERSION:
        raise SystemExit(
            f"error: bundle format version {manifest.get('format_version')!r}, "
            f"this script speaks {FORMAT_VERSION}"
        )

    conn = await asyncpg.connect(dsn)
    try:
        fingerprint = await _schema_fingerprint(conn)
        problems = _compare_schemas(manifest, await _alembic_version(conn), fingerprint)
        if problems:
            for problem in problems:
                print(f"{'warning' if force else 'error'}: {problem}", file=sys.stderr)
            if not force:
                raise SystemExit(
                    "\nAborted: the two databases are not on the same schema. Fetch main, then "
                    "`docker compose up seed` to migrate, then retry. `--force` imports anyway."
                )

        if not manifest.get("embeddings_included", True):
            print(
                "warning: bundle was exported with --no-embeddings -- imported cards land with "
                "NULL embeddings, so dedup and similarity search will not see them",
                file=sys.stderr,
            )

        inserted: dict[str, int] = {}
        skipped: dict[str, int] = {}
        transaction = conn.transaction()
        await transaction.start()
        try:
            for table in TABLES:
                rows = bundle["tables"].get(table, [])
                overrides = IMPORT_OVERRIDES.get(table, {})
                count = 0
                for start in range(0, len(rows), chunk):
                    batch = [dict(row, **overrides) for row in rows[start : start + chunk]]
                    status = await conn.execute(
                        _INSERT_SQL.format(table=table),
                        json.dumps(batch, ensure_ascii=False),
                    )
                    count += int(status.rsplit(" ", 1)[1])
                inserted[table] = count
                skipped[table] = len(rows) - count
                print(
                    f"  {table:<12} +{count:<6} ({skipped[table]} already present)",
                    file=sys.stderr,
                )
        except BaseException:
            await transaction.rollback()
            raise
        if dry_run:
            await transaction.rollback()
        else:
            await transaction.commit()
    finally:
        await conn.close()

    print(
        f"\n{'would insert' if dry_run else 'inserted'} {sum(inserted.values())} rows "
        f"({sum(skipped.values())} skipped as already present)"
        + (" -- rolled back, nothing was written" if dry_run else ""),
        file=sys.stderr,
    )


# -- cli --------------------------------------------------------------------


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="content_bundle",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SPOIN_BUNDLE_DSN", DEFAULT_DSN),
        help="libpq DSN for the docker `db` service (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="write this database's corpus to a bundle file")
    export.add_argument("path", nargs="?", default=DEFAULT_PATH)
    export.add_argument(
        "--no-embeddings",
        action="store_true",
        help="omit vector columns: a much smaller file, but the imported corpus cannot be "
        "deduped or similarity-searched until they are recomputed",
    )

    load = sub.add_parser("import", help="add a bundle's rows to this database")
    load.add_argument("path", nargs="?", default=DEFAULT_PATH)
    load.add_argument("--force", action="store_true", help="import despite a schema mismatch")
    load.add_argument(
        "--dry-run",
        action="store_true",
        help="run the whole import in a transaction and roll it back, for the real counts",
    )
    load.add_argument(
        "--chunk", type=int, default=200, help="rows per INSERT (default: %(default)s)"
    )

    args = parser.parse_args(argv)
    if args.command == "export":
        asyncio.run(_export(args.dsn, args.path, args.no_embeddings))
    else:
        asyncio.run(_import(args.dsn, args.path, args.force, args.dry_run, args.chunk))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        raise SystemExit(130) from None
