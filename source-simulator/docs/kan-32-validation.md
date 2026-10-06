# KAN-32 development load evidence

Executed 2026-10-05 against `pmdp-dev-rmrg-postgres` (PostgreSQL 18.6) and
`pmdp-dev-scc-mysql` (MySQL 8.4.8), with certificate/hostname-verified TLS.
Connection variables came from an untracked local environment file; no credentials
or CA contents are recorded here.

The existing KAN-24 artifact was located at
`/Users/aakashpatel/Desktop/post-merger-data-platform-1/source-simulator/generated/dev/seed-24`.
It was reused unchanged, not regenerated. Its fingerprint is
`752684fba610a0ba6b9400d04414ebc4159a533f85f119502f141bc19d09ca05`;
configuration is the existing small seed-24 profile (180 RMRG orders, 60 SCC orders).
Both services initially had their `defaultdb` connection database. The approved
`rmrg` schema and `scc` database were absent and were created by the loader.

| RMRG table | Rows | SCC table | Rows |
| --- | ---: | --- | ---: |
| customers | 60 | customer_master | 24 |
| customer_addresses | 59 | item_master | 16 |
| product_categories | 4 | locations | 3 |
| products | 30 | sales_orders | 60 |
| stores | 4 | sales_order_lines | 96 |
| warehouses | 2 | payment_transactions | 65 |
| inventory | 180 | stock_balance | 56 |
| orders | 180 | | |
| order_addresses | 247 | | |
| order_items | 362 | | |
| shipments | 183 | | |
| shipment_items | 353 | | |
| returns | 15 | | |
| return_items | 15 | | |
| payments | 349 | | |
| payment_allocations | 844 | | |
| stock_movements | 911 | | |
| **Total** | **3,798** | **Total** | **320** |

Both sources committed successfully. Live full-column/PK readback equaled the
snapshot exactly, all enforced FK/business relationships validated, final inventory
matched its complete movement ledger without reapplying deltas, and every next-ID
counter exceeded the imported maximum. The second load reported `exact_replay` for
both sources without inserts. A separate `--company all --check` reported `checked`
for both, revalidating deployed definitions, every row/count, relationships and
counters.

Validation also included the complete offline test suite: 64 tests discovered,
62 passed, two opt-in engine tests skipped in the normal run. The PostgreSQL engine
test was run separately on a temporary PostgreSQL 14 instance and passed: real DDL,
load, exact replay, next generated ID, audit defaults/updates/no-op versioning,
PK/FK/location rejection and schema-drift detection. MySQL's isolated test-service
suite was not run (the installed local MySQL is 5.7); real Aiven MySQL 8.4.8 schema
creation, seed import, complete readback, auto-increment checks and replay/check
validation all passed. `git diff --check` passed and environment/CA files are ignored.

Use [the execution guide](database-seed-load.md) for repeat loads and recovery.
The two sources commit independently; MySQL bootstrap DDL can leave a partial empty
namespace on failure; source endpoints must be copied from the intended Aiven
service; and the initial validator retains the whole seed in memory. No Kafka,
DMS, S3, lakehouse, CDC configuration or schema redesign was performed.
