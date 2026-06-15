# cron-clean-restore

Two Bash scripts that automate MongoDB Atlas database maintenance via `cron`:

| Script | Purpose |
|---|---|
| `drop_stage_databases.sh` | Drops every database on an Atlas cluster whose name starts with `stage` |
| `restore_databases.sh` | Restores multiple databases in parallel using `mongorestore` / `nohup` |

---

## Prerequisites

| Tool | Minimum version | Install guide |
|---|---|---|
| `mongosh` | 1.x | <https://www.mongodb.com/docs/mongodb-shell/install/> |
| `mongorestore` | 100.x (mongo-database-tools) | <https://www.mongodb.com/docs/database-tools/installation/> |
| Bash | 4.x | Pre-installed on most Linux/macOS systems |

Verify installations:

```bash
mongosh --version
mongorestore --version
```

---

## Configuration

Both scripts accept configuration through **environment variables** or **positional arguments**.

| Variable | Description | Default | Script |
|---|---|---|---|
| `ATLAS_URI` | Full MongoDB Atlas SRV connection string | *(required)* | both |
| `BACKUP_DIR` | Root directory containing one sub-folder per database dump | *(required)* | restore only |
| `DRY_RUN` | Set to `1` to list matching databases without dropping them | `0` | drop only |
| `DROP_EXISTING` | Set to `1` to pass `--drop` to `mongorestore` (destroys existing data before restoring) | `0` | restore only |

> **Security tip:** Store the connection string in a restricted file (e.g. `/etc/cron-mongo.env`, mode `0600`) and source it from cron rather than embedding credentials in the crontab.

---

## drop_stage_databases.sh

### What it does

1. Connects to the Atlas cluster with `mongosh`.
2. Lists all databases whose names match `/^stage/i`.
3. Validates each name (alphanumeric, `-`, `_`, `.` only) before use.
4. Drops each matching database and logs the result.

### Running manually

```bash
# Using environment variable
export ATLAS_URI="******cluster0.abcde.mongodb.net"
bash drop_stage_databases.sh

# Dry run – lists matching databases without dropping them
DRY_RUN=1 ATLAS_URI="..." bash drop_stage_databases.sh

# Or pass the URI directly
bash drop_stage_databases.sh "******cluster0.abcde.mongodb.net"
```

### Logs

Written to `logs/drop_stage_databases.log` (created automatically next to the script).

---

## restore_databases.sh

### What it does

1. Scans every sub-directory of `BACKUP_DIR`; each sub-directory must be named after the target database (the default layout produced by `mongodump`).
2. Starts one `mongorestore` process per database wrapped in `nohup` so all restores run in parallel and survive terminal/session closure.
3. Verifies each process actually started before recording its PID.
4. Each restore writes its own log file to `logs/restore_<dbname>.log`.

> **⚠️ DROP mode:** Setting `DROP_EXISTING=1` adds the `--drop` flag to every `mongorestore` call. This **permanently deletes** all existing documents in every restored collection before writing the backup data. Only enable this when you are certain you want to replace existing data.

### Expected backup layout

```
/var/backups/mongo/dump/
├── stageapp1/          ← restored as database "stageapp1"
│   ├── users.bson
│   └── orders.bson
├── stageapp2/
│   └── products.bson
└── stageapp3/
    └── catalog.bson
```

Create this layout with `mongodump`:

```bash
mongodump \
  --uri="$ATLAS_URI" \
  --out=/var/backups/mongo/dump
```

### Running manually

```bash
# Using environment variables
export ATLAS_URI="******cluster0.abcde.mongodb.net"
export BACKUP_DIR="/var/backups/mongo/dump"
bash restore_databases.sh

# Enable drop mode (destroys existing data before restoring)
DROP_EXISTING=1 ATLAS_URI="..." BACKUP_DIR="..." bash restore_databases.sh

# Or pass both values directly
bash restore_databases.sh \
  "******cluster0.abcde.mongodb.net" \
  "/var/backups/mongo/dump"
```

### Logs

- Master log (launch events): `logs/restore_databases.log`
- Per-database restore output: `logs/restore_<dbname>.log`

---

## Setting up cron

### 1. Make scripts executable

```bash
chmod +x /path/to/drop_stage_databases.sh
chmod +x /path/to/restore_databases.sh
```

### 2. Create a credentials file

```bash
sudo tee /etc/cron-mongo.env > /dev/null <<'EOF'
ATLAS_URI=******cluster0.abcde.mongodb.net
BACKUP_DIR=/var/backups/mongo/dump
EOF
sudo chmod 600 /etc/cron-mongo.env
```

### 3. Edit the crontab

```bash
crontab -e
```

Add the following lines (adjust times to suit your schedule):

```cron
# ┌──────────── minute  (0–59)
# │  ┌─────────── hour    (0–23)
# │  │  ┌──────────── day of month (1–31)
# │  │  │  ┌─────────── month (1–12)
# │  │  │  │  ┌──────────── day of week (0–7, 0 and 7 = Sunday)
# │  │  │  │  │
# *  *  *  *  *  command

# Drop all "stage*" databases every night at 02:00 UTC
0 2 * * *  . /etc/cron-mongo.env && /path/to/drop_stage_databases.sh

# Restore all databases every night at 03:00 UTC (after drop finishes)
0 3 * * *  . /etc/cron-mongo.env && /path/to/restore_databases.sh
```

> **Note:** The `. /etc/cron-mongo.env &&` prefix sources the credentials file before running each script, so no secrets appear in the crontab itself.
>
> Each script writes its own timestamped log to `logs/` next to the script file. You do **not** need to redirect cron output to a separate file unless you also want to capture stdout from the cron daemon itself.

### 4. Verify the crontab

```bash
crontab -l
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `mongosh: command not found` | `mongosh` not in `PATH` | Add its install location to `PATH` in the cron environment (e.g. `PATH=/usr/local/bin:/usr/bin:/bin`) at the top of the crontab |
| `mongorestore: command not found` | Database tools not installed | Install `mongodb-database-tools` package |
| No databases dropped / restored | Wrong `ATLAS_URI` or network ACL | Verify the URI and ensure the cron host's IP is in the Atlas IP allow-list |
| Restore fails with auth error | Incorrect credentials | Check username/password and database user roles in Atlas |
| `WARNING: … failed to start` | mongorestore crashed immediately | Check the per-database log in `logs/restore_<dbname>.log` for details |
| Logs not created | Permissions issue | Ensure the user running cron can write to the `logs/` directory |

---

## Directory structure

```
cron-clean-restore/
├── drop_stage_databases.sh   # Drop stage* databases
├── restore_databases.sh      # Restore databases in parallel via nohup
├── logs/                     # Created automatically at runtime
│   ├── drop_stage_databases.log
│   ├── restore_databases.log
│   └── restore_<dbname>.log
└── README.md
```
