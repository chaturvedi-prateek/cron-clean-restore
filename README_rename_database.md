# rename_mongodb_database.py

Renames one or more MongoDB databases by moving all their collections using the `renameCollection` admin command. MongoDB has no native `renameDatabase` command, so this script iterates every collection in each source database and relocates it to a new database named with a configurable prefix and/or suffix.

Designed to run as a cron job.

---

## How it works

For each source database, the script:

1. Connects to MongoDB and lists all databases.
2. Iterates every collection in the source database.
3. Calls `db.adminCommand({ renameCollection: "src.coll", to: "tgt.coll" })` for each one.
4. Optionally drops the (now empty) source database with `--drop-source`.

Target database name = `<prefix><source_db_name><suffix>`

---

## Requirements

- Python 3.10+
- `pymongo`

```bash
pip install pymongo
```

---

## Usage

```
python3 rename_mongodb_database.py [options]
```

### Options

| Flag | Env variable | Default | Description |
|---|---|---|---|
| `--uri` | `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `--databases DB [DB ...]` | `DATABASES` | — | One or more source database names |
| `--prefix PREFIX` | `DB_PREFIX` | `""` | String prepended to each target name |
| `--suffix SUFFIX` | `DB_SUFFIX` | `""` | String appended to each target name |
| `--drop-source` | — | `false` | Drop source DB after all collections are moved |
| `--dry-run` | — | `false` | Preview the rename plan without making changes |
| `--list-dbs` | — | `false` | List all databases on the server and exit |

At least one of `--prefix` or `--suffix` is required. `DATABASES` env var accepts a comma-separated list.

---

## Examples

### List all databases
```bash
python3 rename_mongodb_database.py \
  --uri "mongodb://localhost:27017" \
  --list-dbs
```

### Dry run — preview what would happen
```bash
python3 rename_mongodb_database.py \
  --databases db1 db2 db3 \
  --prefix "archived_" \
  --dry-run
```

### Prefix only
Renames `db1` → `archived_db1`, `db2` → `archived_db2`
```bash
python3 rename_mongodb_database.py \
  --databases db1 db2 \
  --prefix "archived_"
```

### Suffix only
Renames `db1` → `db1_2026`, `db2` → `db2_2026`
```bash
python3 rename_mongodb_database.py \
  --databases db1 db2 \
  --suffix "_2026"
```

### Prefix + suffix
Renames `db1` → `bak_db1_2026`
```bash
python3 rename_mongodb_database.py \
  --databases db1 db2 \
  --prefix "bak_" \
  --suffix "_2026"
```

### Drop source databases after rename
```bash
python3 rename_mongodb_database.py \
  --databases db1 db2 \
  --prefix "archived_" \
  --drop-source
```

---

## Running as a cron job

Prefer environment variables in cron to avoid exposing credentials in the process list.

### crontab entry — daily at 2am
```cron
0 2 * * * MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net" DATABASES="db1,db2,db3" DB_PREFIX="archived_" /usr/bin/python3 /path/to/rename_mongodb_database.py --drop-source >> /var/log/mongo_rename.log 2>&1
```

### Using a wrapper script (recommended)
Create `/etc/cron.d/mongo_rename` or a wrapper shell script to keep credentials in a sourced env file:

```bash
#!/bin/bash
set -a
source /etc/mongo_rename.env   # contains MONGODB_URI, DATABASES, DB_PREFIX, etc.
set +a
exec python3 /path/to/rename_mongodb_database.py --drop-source
```

```cron
0 2 * * * /path/to/run_mongo_rename.sh >> /var/log/mongo_rename.log 2>&1
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All databases renamed successfully |
| `1` | One or more databases failed, or invalid arguments |

Failures are logged per-database so the log shows exactly which source databases or collections did not complete.

---

## Notes

- **Merge behaviour**: if the target database already exists, collections are merged into it. The script logs a warning when this occurs.
- **Safe drop**: `--drop-source` only drops a source database if it is completely empty after the rename. If any collection failed to move, the source is left intact.
- **Same-server only**: `renameCollection` cannot move collections across MongoDB deployments. Source and target must be on the same server/replica set.
- **Permissions**: the connecting user needs the `dbAdminAnyDatabase` or `clusterAdmin` role (or equivalent) to call `renameCollection` on the admin database.
