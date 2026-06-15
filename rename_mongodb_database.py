#!/usr/bin/env python3
"""
rename_mongodb_database.py

Renames one or more MongoDB databases by using renameCollection on each
collection, moving it to a new database named with a given prefix/suffix.

MongoDB has no native "renameDatabase" command, so this iterates all
collections in each source DB and calls the admin renameCollection command.

Usage:
    # Single database
    python rename_mongodb_database.py --databases mydb --prefix archived_

    # Multiple databases
    python rename_mongodb_database.py --databases db1 db2 db3 --prefix archived_

    # With a suffix instead
    python rename_mongodb_database.py --databases db1 db2 --suffix _bak

    # Both prefix and suffix
    python rename_mongodb_database.py --databases db1 db2 --prefix bak_ --suffix _2026

Environment variables:
    MONGODB_URI       MongoDB connection string (default: mongodb://localhost:27017)
    DATABASES         Comma-separated list of source database names
    DB_PREFIX         String to prepend to each target database name
    DB_SUFFIX         String to append to each target database name

Cron example (daily at 2am):
    0 2 * * * MONGODB_URI="mongodb://..." DATABASES="db1,db2,db3" DB_PREFIX="archived_" \\
      /usr/bin/python3 /path/to/rename_mongodb_database.py --drop-source >> /var/log/mongo_rename.log 2>&1
"""

import argparse
import logging
import os
import sys

try:
    from pymongo import MongoClient
    from pymongo.errors import OperationFailure, ConnectionFailure
except ImportError:
    print("ERROR: pymongo is required. Install with: pip install pymongo", file=sys.stderr)
    sys.exit(1)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def list_databases(client: MongoClient) -> list[str]:
    return [db["name"] for db in client.list_databases()]


def rename_database(
    client: MongoClient,
    src: str,
    tgt: str,
    drop_source: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Rename `src` to `tgt` by moving all collections via renameCollection.
    Returns True on full success, False if any collection failed.
    """
    if src == tgt:
        log.error("Source and target are identical ('%s'). Skipping.", src)
        return False

    src_db = client[src]
    collections = src_db.list_collection_names()

    if not collections:
        log.warning("Source database '%s' has no collections. Skipping.", src)
        return True

    all_dbs = list_databases(client)
    if tgt in all_dbs:
        log.warning("Target database '%s' already exists; collections will merge.", tgt)

    log.info(
        "  %s -> %s  (%d collection(s))%s",
        src,
        tgt,
        len(collections),
        " [DRY RUN]" if dry_run else "",
    )

    failed: list[str] = []

    for coll in collections:
        src_ns = f"{src}.{coll}"
        tgt_ns = f"{tgt}.{coll}"
        log.info("    renameCollection: %s -> %s", src_ns, tgt_ns)

        if dry_run:
            continue

        try:
            client.admin.command(
                "renameCollection",
                src_ns,
                to=tgt_ns,
                dropTarget=False,
            )
        except OperationFailure as exc:
            log.error("    FAILED %s -> %s: %s", src_ns, tgt_ns, exc)
            failed.append(coll)

    if failed:
        log.error("  Failed collections in '%s': %s", src, failed)
        return False

    if drop_source and not dry_run:
        remaining = client[src].list_collection_names()
        if remaining:
            log.warning(
                "  Not dropping '%s': %d collection(s) still present: %s",
                src,
                len(remaining),
                remaining,
            )
        else:
            client.drop_database(src)
            log.info("  Dropped empty source database '%s'.", src)

    return True


def parse_args() -> argparse.Namespace:
    env_databases = os.environ.get("DATABASES", "")

    parser = argparse.ArgumentParser(
        description="Rename MongoDB database(s) via renameCollection, adding a prefix/suffix."
    )
    parser.add_argument(
        "--uri",
        default=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI (env: MONGODB_URI)",
    )
    parser.add_argument(
        "--databases",
        nargs="+",
        default=[d.strip() for d in env_databases.split(",") if d.strip()] or None,
        metavar="DB",
        help="One or more source database names (env: DATABASES as comma-separated list)",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("DB_PREFIX", ""),
        help="String to prepend to each target database name (env: DB_PREFIX)",
    )
    parser.add_argument(
        "--suffix",
        default=os.environ.get("DB_SUFFIX", ""),
        help="String to append to each target database name (env: DB_SUFFIX)",
    )
    parser.add_argument(
        "--drop-source",
        action="store_true",
        default=False,
        help="Drop each source database after all its collections are moved",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would happen without making any changes",
    )
    parser.add_argument(
        "--list-dbs",
        action="store_true",
        default=False,
        help="List all databases and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log.info("Connecting to MongoDB: %s", args.uri)
    try:
        client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except ConnectionFailure as exc:
        log.error("Cannot connect to MongoDB: %s", exc)
        sys.exit(1)

    if args.list_dbs:
        dbs = list_databases(client)
        log.info("Databases (%d): %s", len(dbs), dbs)
        client.close()
        return

    if not args.databases:
        log.error("No databases specified. Use --databases or set DATABASES env var.")
        client.close()
        sys.exit(1)

    if not args.prefix and not args.suffix:
        log.error("No prefix or suffix specified. Use --prefix and/or --suffix.")
        client.close()
        sys.exit(1)

    all_dbs = list_databases(client)
    log.info("Databases on server: %s", all_dbs)

    # Build rename plan: source -> target
    plan: list[tuple[str, str]] = []
    for src in args.databases:
        tgt = f"{args.prefix}{src}{args.suffix}"
        plan.append((src, tgt))

    log.info(
        "Rename plan (%d database(s))%s:",
        len(plan),
        " [DRY RUN]" if args.dry_run else "",
    )
    for src, tgt in plan:
        exists = src in all_dbs
        log.info("  %s -> %s%s", src, tgt, "" if exists else "  [WARNING: source not found]")

    results: dict[str, bool] = {}
    for src, tgt in plan:
        if src not in all_dbs:
            log.error("Source database '%s' not found. Skipping.", src)
            results[src] = False
            continue
        results[src] = rename_database(
            client,
            src=src,
            tgt=tgt,
            drop_source=args.drop_source,
            dry_run=args.dry_run,
        )

    client.close()

    passed = [db for db, ok in results.items() if ok]
    failed = [db for db, ok in results.items() if not ok]

    log.info("Summary: %d succeeded, %d failed", len(passed), len(failed))
    if failed:
        log.error("Failed databases: %s", failed)
        sys.exit(1)

    log.info("All done.")


if __name__ == "__main__":
    main()
