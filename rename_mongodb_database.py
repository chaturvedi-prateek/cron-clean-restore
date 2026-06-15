#!/usr/bin/env python3
"""
rename_mongodb_database.py

Renames a MongoDB database by using renameCollection on each collection
in the source database, moving them to the target database.

MongoDB has no native "renameDatabase" command, so this iterates all
collections in the source DB and calls the admin renameCollection command
for each one.

Usage:
    python rename_mongodb_database.py --source <src_db> --target <tgt_db> [options]

Environment variables (override CLI flags):
    MONGODB_URI       MongoDB connection string (default: mongodb://localhost:27017)
    SRC_DATABASE      Source database name
    TGT_DATABASE      Target database name

Cron example (daily at 2am):
    0 2 * * * /usr/bin/python3 /path/to/rename_mongodb_database.py \
        --source old_db --target new_db >> /var/log/mongo_rename.log 2>&1
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

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
    Rename `src` database to `tgt` by moving all collections via renameCollection.
    Returns True on full success, False if any collection failed.
    """
    all_dbs = list_databases(client)
    log.info("Databases found: %s", all_dbs)

    if src not in all_dbs:
        log.error("Source database '%s' does not exist. Aborting.", src)
        return False

    if tgt in all_dbs:
        log.warning("Target database '%s' already exists; collections will merge.", tgt)

    src_db = client[src]
    collections = src_db.list_collection_names()

    if not collections:
        log.warning("Source database '%s' has no collections.", src)
        return True

    log.info(
        "Renaming database '%s' -> '%s' (%d collection(s))%s",
        src,
        tgt,
        len(collections),
        " [DRY RUN]" if dry_run else "",
    )

    failed: list[str] = []

    for coll in collections:
        src_ns = f"{src}.{coll}"
        tgt_ns = f"{tgt}.{coll}"
        log.info("  renameCollection: %s -> %s", src_ns, tgt_ns)

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
            log.error("  FAILED %s -> %s: %s", src_ns, tgt_ns, exc)
            failed.append(coll)

    if failed:
        log.error("Failed collections: %s", failed)
        return False

    if drop_source and not dry_run:
        remaining = client[src].list_collection_names()
        if remaining:
            log.warning(
                "Not dropping source '%s': %d collection(s) still present: %s",
                src,
                len(remaining),
                remaining,
            )
        else:
            client.drop_database(src)
            log.info("Dropped empty source database '%s'.", src)

    log.info("Done.")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rename a MongoDB database via renameCollection.")
    parser.add_argument(
        "--uri",
        default=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI (env: MONGODB_URI)",
    )
    parser.add_argument(
        "--source",
        default=os.environ.get("SRC_DATABASE"),
        required=not os.environ.get("SRC_DATABASE"),
        help="Source database name (env: SRC_DATABASE)",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("TGT_DATABASE"),
        required=not os.environ.get("TGT_DATABASE"),
        help="Target database name (env: TGT_DATABASE)",
    )
    parser.add_argument(
        "--drop-source",
        action="store_true",
        default=False,
        help="Drop the source database after all collections are moved",
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
        help="Just list databases and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log.info("Connecting to MongoDB: %s", args.uri)
    try:
        client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
        # Force connection check
        client.admin.command("ping")
    except ConnectionFailure as exc:
        log.error("Cannot connect to MongoDB: %s", exc)
        sys.exit(1)

    if args.list_dbs:
        dbs = list_databases(client)
        log.info("Databases (%d): %s", len(dbs), dbs)
        client.close()
        return

    success = rename_database(
        client,
        src=args.source,
        tgt=args.target,
        drop_source=args.drop_source,
        dry_run=args.dry_run,
    )
    client.close()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
