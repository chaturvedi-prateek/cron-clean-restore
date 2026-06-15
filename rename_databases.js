// rename_databases.js
// Renames a list of MongoDB databases by moving all collections via renameCollection.
//
// Usage:
//   mongosh "mongodb://localhost:27017" rename_databases.js
//
// Edit the config block below before running.

// ── config ────────────────────────────────────────────────────────────────────
const DATABASES = ["db1", "db2", "db3"];   // source databases to rename
const PREFIX    = "archived_";              // prepended to each target name
const SUFFIX    = "";                       // appended  to each target name  (can be empty)
const DROP_SOURCE = false;                  // set true to drop source DB after move
const DRY_RUN     = false;                  // set true to preview without changes
// ─────────────────────────────────────────────────────────────────────────────

const existingDbs = db.adminCommand({ listDatabases: 1 })
    .databases.map(d => d.name);

print(`Databases on server: ${existingDbs.join(", ")}\n`);

let passed = 0, failed = 0;

for (const src of DATABASES) {
    const tgt = `${PREFIX}${src}${SUFFIX}`;

    if (!existingDbs.includes(src)) {
        print(`SKIP  ${src} — not found`);
        failed++;
        continue;
    }

    const collections = db.getSiblingDB(src).getCollectionNames();

    if (collections.length === 0) {
        print(`SKIP  ${src} — no collections`);
        continue;
    }

    print(`\n${src} -> ${tgt}  (${collections.length} collection(s))${DRY_RUN ? " [DRY RUN]" : ""}`);

    let dbFailed = false;

    for (const coll of collections) {
        const srcNs = `${src}.${coll}`;
        const tgtNs = `${tgt}.${coll}`;
        print(`  renameCollection: ${srcNs} -> ${tgtNs}`);

        if (DRY_RUN) continue;

        const result = db.adminCommand({ renameCollection: srcNs, to: tgtNs, dropTarget: false });
        if (!result.ok) {
            print(`  FAILED: ${JSON.stringify(result)}`);
            dbFailed = true;
        }
    }

    if (dbFailed) {
        failed++;
        continue;
    }

    if (DROP_SOURCE && !DRY_RUN) {
        const remaining = db.getSiblingDB(src).getCollectionNames();
        if (remaining.length === 0) {
            db.getSiblingDB(src).dropDatabase();
            print(`  Dropped empty source database '${src}'.`);
        } else {
            print(`  WARNING: not dropping '${src}', ${remaining.length} collection(s) still present.`);
        }
    }

    passed++;
}

print(`\nSummary: ${passed} succeeded, ${failed} failed.`);
