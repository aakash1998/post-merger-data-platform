# KAN-32 source deployment and seed load

This deploys the approved 17-table `rmrg` PostgreSQL schema and seven-table `scc`
MySQL database, then imports an **existing KAN-24 snapshot**. Targets for this ticket
are `pmdp-dev-rmrg-postgres` and `pmdp-dev-scc-mysql`. It does not configure CDC or
other platform services. Reviewable SQL is packaged in
[`rmrg.sql`](../src/retail_simulator/ddl/rmrg.sql) and
[`scc.sql`](../src/retail_simulator/ddl/scc.sql). The loader executes those same
statements through DBAPI; SQL files alone do not establish the loader's deployment
receipt. Do not apply them manually and then ask the loader to adopt the namespace.

## Prerequisites and connection variables

Use Python 3.11+, PostgreSQL 14+ (integration-tested on 14), and a supported Aiven
MySQL release >= 8.0.16 with enforced CHECK constraints and InnoDB. Install only
the optional database dependencies; offline simulator use stays dependency-free:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e './source-simulator[database]'
```

Set these variables **through the shell**, using the actual Aiven connection
information and downloaded service CA certificates. Never paste credentials into
chat, commit them, or enable shell tracing (`set -x`). An untracked `.env` shell
file can contain exports; `.env*` and PEM files are ignored by this repository.
There are no credential or connection target defaults.

| Variable | Required value |
| --- | --- |
| `PMDP_ENV` | `dev` for this ticket; `test` only with separate test services/snapshot |
| `PMDP_RMRG_POSTGRES_SERVICE` | `pmdp-dev-rmrg-postgres` |
| `PMDP_RMRG_POSTGRES_HOST` | Actual PostgreSQL Aiven hostname, without a URL/user/password |
| `PMDP_RMRG_POSTGRES_PORT` | Actual PostgreSQL service port |
| `PMDP_RMRG_POSTGRES_DATABASE` | Actual connection database from Aiven; `rmrg` is its schema |
| `PMDP_RMRG_POSTGRES_USER` | Database account |
| `PMDP_RMRG_POSTGRES_PASSWORD` | Database password |
| `PMDP_RMRG_POSTGRES_SSLROOTCERT` | Absolute path to PostgreSQL service CA PEM |
| `PMDP_SCC_MYSQL_SERVICE` | `pmdp-dev-scc-mysql` |
| `PMDP_SCC_MYSQL_HOST` | Actual MySQL Aiven hostname, without a URL/user/password |
| `PMDP_SCC_MYSQL_PORT` | Actual MySQL service port |
| `PMDP_SCC_MYSQL_DATABASE` | Existing Aiven `defaultdb` for bootstrap, or `scc` for subsequent use; source tables always live in `scc` |
| `PMDP_SCC_MYSQL_USER` | Database account |
| `PMDP_SCC_MYSQL_PASSWORD` | Database password |
| `PMDP_SCC_MYSQL_SSL_CA` | Absolute path to MySQL service CA PEM |

For `test`, service values must be `pmdp-test-rmrg-postgres` and
`pmdp-test-scc-mysql`. `prod` is rejected. TLS certificate **and hostname**
verification are mandatory (`verify-full` for PostgreSQL; verified identity for
MySQL). The declared service label validates configuration intent; it cannot prove
an Aiven hostname belongs to that service. The operator must copy each endpoint
from the named Aiven service and keep all application/simulator writers stopped
through bootstrap/load. No Aiven control-plane credentials are required.

PostgreSQL permissions: connect to the chosen database, create schema/functions/
tables/indexes/triggers, comment the schema, insert/select/lock rows and use/set its
identity sequences. MySQL permissions: create `scc`, tables/indexes/triggers, alter
the deployment receipt comment, insert/select, and access table/trigger metadata.
MySQL must allow `GET_LOCK` and session strict-mode settings. When configured with `defaultdb`, the loader connects there and creates `scc`
alongside it. When configured with `scc`, it initially connects without a selected
database so first-time creation remains possible. All SQL uses fully qualified
`scc` names; existing `defaultdb` tables are untouched.

## Execute from the repository root

Replace the snapshot path with the existing directory containing `manifest.json`.
The loader does not generate or silently replace a baseline. Preserve that snapshot
unchanged as load evidence. If using an environment file, first source it privately:

```sh
# Only if you use an untracked file containing exports:
set +x
source /absolute/path/to/.env

# Validate all checksums, types, IDs, enforced FKs and business/stock relationships offline:
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.deployment \
  --snapshot /absolute/path/to/seed-24 --validate-only

# Deploy/load one database at a time, making completion independently visible:
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.deployment \
  --snapshot /absolute/path/to/seed-24 --company rmrg
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.deployment \
  --snapshot /absolute/path/to/seed-24 --company scc

# Independently recheck deployed schema, every row, relationships and next IDs:
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.deployment \
  --snapshot /absolute/path/to/seed-24 --company all --check
```

`--company all` also deploys/loads both in one invocation (the default), but **there
is no distributed transaction** across PostgreSQL/MySQL. Each source commits
independently. A successful source is safe to replay if the other fails. Capture
JSON logs in an untracked generated directory if desired. Logs include fingerprint,
service label, per-table counts and `loaded` / `exact_replay` / `checked` outcomes;
they exclude connection credentials and source row contents. Failures exit nonzero.

## Safety, reconciliation and restart behavior

- Snapshot environment, source-instance names, fingerprint, exact file list, schema
  hash, approved load order, checksums, row counts, typed values and full business
  reconciliation must pass **before any connection**. Matching truth stays a file;
  no matching/ingestion columns or extra source tables are invented.
- DDL creates an absent namespace, never drops/replaces/adopts unexpected existing
  objects. Bootstrap stores a KAN-32 environment/DDL/catalog receipt in the schema
  comment (PostgreSQL) or `customer_master` table comment (MySQL). Every later run
  fingerprints live columns, constraints, indexes, triggers and PostgreSQL trigger
  function definitions. Changed/unmarked schemas fail. Receipts are drift checks,
  not protection against a privileged administrator deliberately rewriting them.
- All tables must be empty, or the **entire** target must match the snapshot exactly
  for a replay. Same counts with different IDs/values, partial rows, extra rows and
  a different snapshot fail without UPDATE, DELETE, UPSERT, TRUNCATE or overwrite.
  Empty per-table files remain empty tables. Columns retain source names/types/
  nullability, all explicit IDs, Decimal values, nulls/blanks and original audits.
- FK checks remain enabled. Import uses approved table order and topological order
  for category parents, payment parents and movement reversals. Missing/cyclic
  self-references fail. Composite FKs enforce customer/order/shipment/return
  ownership; SCC logical customer/item/reversal references remain unenforced.
- RMRG inventory is already final. Inventory rows and historical stock movements
  are inserted verbatim. **No movement trigger or loader update reapplies deltas.**
  Readback runs the simulator's complete ledger, order/line, payment/allocation,
  fulfillment and return reconciliation. Every stored column/PK and table row count
  must also match the baseline. SCC intentional negative/duplicate/orphan-logical/
  weak-audit evidence remains intact, and enforced structural relationships pass.
- PostgreSQL holds exclusive table locks during loading; MySQL uses SERIALIZABLE
  full-PK `FOR UPDATE` scans to lock rows and gaps. Session advisory locks exclude
  concurrent loaders. Keep other writers stopped, especially during schema creation.
  Lock contention or connection failure aborts; no partial data commit occurs.
- One DML transaction covers **all tables per source**, including readback and
  validation before commit. PostgreSQL sequences advance to at least imported
  maxima without moving an already higher sequence backward. Empty sequences start
  at one. InnoDB automatically advances AUTO_INCREMENT for explicit positive IDs;
  the loader verifies it exceeds every table's maximum. It deliberately avoids
  `ALTER TABLE ... AUTO_INCREMENT` during DML because that would implicitly commit.
  Counter values may advance on rollback, leaving harmless gaps.
- PostgreSQL DDL is transactional. MySQL DDL implicitly commits, so a failure
  midway through initial MySQL schema creation can leave a partial empty namespace.
  The loader rejects it instead of attempting an unreviewed repair. Inspect it and
  arrange an explicitly reviewed cleanup/recreation or use a fresh isolated service;
  there is no destructive reset option. A completed marked empty schema can retry
  DML normally. A lost connection around COMMIT can be resolved with `--check` or
  an exact replay, which compares every row before deciding what happened.

The import preserves controlled historical RMRG audit values. Normal future INSERTs
use database timestamp/version defaults; UPDATE triggers maintain timestamps and
increment row_version once for meaningful changes, preserve creation audit/PKs and
inventory grain, and avoid version increments for no-op updates. SCC only rejects
PK changes; its audits remain application-entered local DATETIME with no automatic
maintenance. Cross-row business transitions/cycles/capacities remain transactional
application responsibilities, as the approved source conventions specify; these DDL
files do not implement a new running business mutation service.

Validation retains the complete seed/readback in memory to reuse the existing
cross-order validator; this initial loader is sized for KAN-24 development seeds,
not arbitrary bulk migration. Inserts are batched at 500 rows. Large snapshots need
an explicitly reviewed streaming/reconciliation design before use.

## Tests

```sh
PYTHONPATH=source-simulator/src .venv/bin/python -m unittest discover \
  -s source-simulator/tests -v
```

`test_deployment.py` exercises corruption, environment mismatch, FK ordering,
self-reference cycles, exact replay, changed-target refusal, typed ID/money import,
no double inventory application and rollback. Existing dictionary tests compare
`schema.json` with approved Markdown columns. Packaged SQL must equal the renderer;
regenerate with `PYTHONPATH=source-simulator/src python3 -m retail_simulator.source_ddl`.

`test_deployment_integration.py` is opt-in and never drops schemas. For PostgreSQL,
set `PMDP_KAN32_TEST_POSTGRES_DSN` to a **disposable** database with absent `rmrg`.
For MySQL, set `PMDP_KAN32_TEST_MYSQL=1`, `PMDP_ENV=test` and the SCC variables above
to a separate test service with absent `scc`. Tests load/replay/check real tables,
verify generated next IDs and constraint rejection, and test PostgreSQL audit/drift
behavior. They leave the baseline available for inspection. Never run these tests
against the ticket's development baseline or an existing application database.
