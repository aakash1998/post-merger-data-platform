# Continuous relational changes — KAN-25

The simulator applies business commands over a KAN-24 baseline rather than replacing the seed repeatedly. Both sources produce inserts, updates and controlled deletes with their approved columns and source-qualified identities. No source schema, architecture, DMS configuration or Kafka contract changes are included.

## Run and resume

Python 3.11+ and POSIX file locks (macOS/Linux) are required for durable local mode. There are no runtime dependencies or cloud connections. From the repository root:

```sh
# Create an immutable seed if one is not already available.
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator \
  --config source-simulator/config/small.json \
  --output source-simulator/generated/dev/seed-24

# Initialize a separate, mutable local source state; run for 30 seconds.
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator.continuous \
  --snapshot source-simulator/generated/dev/seed-24 \
  --state-dir source-simulator/generated/dev/live-25 \
  --duration 30 --rate 5

# Resume committed state without loading or replaying the seed as new source writes.
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator.continuous \
  --state-dir source-simulator/generated/dev/live-25 \
  --duration 30 --rate 5

PYTHONPATH=source-simulator/src python3 -m unittest discover -s source-simulator/tests -v
```

An optional editable installation exposes `pmdp-change`. `PMDP_ENV` must be dev/test and match the seed/local state. The seed's checksums and table/type contracts are validated before initial import. A source baseline whose RMRG audit clock lies in the future is rejected rather than silently backdating updates.

| Option | Default | Meaning |
| --- | --- | --- |
| `--state-dir` | Required | Durable local source state, separate from the immutable seed |
| `--snapshot` | Required only on initialization | Complete KAN-24 snapshot; later runs resume the copied baseline and journal |
| `--duration` | 60 seconds | Monotonic run limit, starting after state recovery |
| `--forever` | Off | Run until SIGINT/SIGTERM; mutually exclusive with duration |
| `--rate` | 2 | Maximum **transaction attempts** per second, not row changes or a throughput guarantee |
| `--max-transactions` | Unlimited | Optional cap on commits during this invocation |
| `--rmrg-weight`, `--scc-weight` | 3, 1 | Relative source activity rates; both must be positive |
| `--workload-config` | KAN-24 defaults | Optional KAN-24 JSON profile supplying max_lines, guest_fraction and messy_fraction; current master counts/keys come from committed state, order counts/date window are not re-generated |

Business activity selection uses weighted commands: more new orders, payment and fulfillment work than customer creation or deletion. A command with no eligible record is skipped and counted without modifying audit fields. Slow validation/persistence applies backpressure; there is no queued backlog of uncommitted commands or burst to recover missed rate slots. The rate controls business transactions, each of which can change several source rows. A short random run need not exercise every command; the acceptance tests cover required lifecycles directly, without introducing a scenario framework.

SIGINT/SIGTERM stops scheduling, lets an already-started transaction finish, and closes the state lock. A duration is also a scheduling limit; an in-flight commit can finish after the deadline. Logs expose sequence, company, activity, row-change counts and summary I/U/D/skip counts, not source customer rows. Validation/persistence failures stop the process with a structured error rather than continuing from uncertain state.

## Business behavior

RMRG reuses KAN-24's structured customer/address contracts, weighted baskets, snapshotted pricing/tax, shipment allocations and stock-ledger helpers. New orders start in processing with reservations and a pending capture; card authorization is represented as confirmed by the synthetic provider. Capture confirmation, shipment readiness, handover, carrier delivery, return request, authorization, receipt/quarantine, inspection/refund request and refund confirmation are separate transactions. Pickup/carryout completes delivery at handover. Shipment progress updates line/header fulfillment state, and handover consumes reserved and physical units once. Returns identify actual fulfilled shipment items and refund original discounted merchandise/tax with exact return-item allocations. Damaged returns are disposed; others restock. Stock receipts and shortage replenishment append ledger entries and update balances atomically.

Cancellation is intentionally limited to wholly unfulfilled, uncaptured orders. The simulated provider definitively confirms failure of an outstanding capture before a successful authorization is voided, reservations released, allocations cancelled, and line quantities cancelled. It does not infer failure from a timeout. Accepted order totals and prices remain unchanged. Post-capture partial cancellation is not claimed as current command coverage.

RMRG deletes only unaccepted drafts (children first). It retains fulfilled commercial, payment and inventory history. Customer contact/loyalty changes preserve source identity and existing order snapshots. Every changed RMRG row increments row_version once per transaction's final source update, retains creation audit values, and gets UTC update/actor metadata. New registration timestamps precede or tie subsequent order placement. SQL persistence leaves RMRG database-owned timestamps/version counters to the approved future source implementation.

SCC retains the smaller seven-table source: new customers, OPEN invoice/line inserts, cashbook postings, mutable invoice/posting corrections, stock observations and raw account changes. Paid_amount remains a cache; correction commands do not manufacture settlement proof. Typed discrepancies, signed quantities/balances and loose customer/item references remain quality evidence. Some invoice/posting corrections intentionally leave old audit timestamps unchanged; all newly entered DATETIME values have local Edmonton wall time and whole-second precision. Enforced order, stock-item and location FKs remain valid. Abandoned OPEN invoices without linked cash postings are removed child-first; inactive non-WALKIN customer records can be physically removed, leaving permitted logical customer references unresolved. The simulator does not automatically select a winner for duplicate business records, delete shared WALKIN identities, or invent SCC shipment/return tables.

This is a demonstration workload, not real provider/carrier integration. Workflow progression occurs on later eligible ticks, without waiting real shipping days. The initial Alberta/CAD assortment, tax/pricing assumptions and SCC messiness remain KAN-24's documented assumptions. One-unit, one-RMA-per-order returns are supported; multi-capture/split-tender refunds, exchanges, transfers, reversals, partial receipts and every possible lifecycle transition are not claimed as current coverage.

## Persistence and consistency

`Activity` plans a company-scoped `Transaction` of `Change` objects with before/after images and durable PK highwaters. `Persistence` defines the state/commit boundary; MemoryStore is for tests and FileStore is the durable local implementation. Source row shapes never gain journal sequence, operation, matching, SCD or ingestion columns. These objects and files are simulator control metadata, **not** DMS envelopes or enterprise events.

Before publication, validation checks exact source columns/types, enforced/composite FKs, unique keys, audit/version progression, protected commercial/terminal-payment evidence, monetary/payment/refund caps, fulfillment ownership/units, return quarantine/disposition and complete inventory ledger balances. SCC logical orphan references and approved quality problems are allowed. Validation extends KAN-24's existing rules for intermediate states without relaxing the source contracts or rewriting the seed CLI. An exact replay of the last committed transaction has no additional effect; a competing/stale before-image or unexpected sequence is rejected.

FileStore copies the validated baseline into `baseline.json` once, then publishes one complete `transactions/<sequence>.json` file per commit. The file contains the final per-row changes and highwaters; temporary files, flush/fsync and same-directory rename prevent partial publication. Memory advances only after durable publication. On restart it replays contiguous validated journal files, recovering even a commit whose acknowledgment was lost. Deleted IDs remain reserved by persisted highwaters. The lifetime file lock prevents two processes from writing the same state directory. A failed or corrupt committed journal stops recovery; pending temporary files do not count as committed transactions. Source operation history is retained for inspection.

Local mode stores source rows in memory and retains the journal without compaction. State, validation work, disk usage and restart time grow with source history; it targets local demonstrations and acceptance testing, not production database scale. Keep runs bounded when using large seeds. There is no architecture change to a local database or claim that the journal is a CDC pipeline.

## PostgreSQL/MySQL integration boundary

`DBAPIWriter` accepts an injected DB-API connection and explicit source namespace. It writes approved PostgreSQL/MySQL tables using parameterized values, allowlisted identifiers, before-image checks with row locks, parent-before-child inserts, child-before-parent deletes, and a single company transaction with rollback on failure. No driver, credential, connection string, resource target or DDL is embedded. Unit tests verify both dialects' transaction boundaries, parameters, source audit ownership and rollback.

The CLI currently exposes the local implementation. The SQL writer is a deployment building block, not a distributed coordinator between FileStore and a remote database. Database-backed runtime integration must supply transaction-capable connections with autocommit disabled, already-provisioned approved schemas, authoritative source state/readback, database-owned audit/version handling, controlled identity allocation/sequence advancement, and recovery for uncertain remote commit outcomes. Use validated transactions and exclusively controlled dev/test source targets; reload and replan on a source conflict rather than guessing. Do not automatically retry an ambiguous SCC insert: its legacy source lacks business idempotency keys. Do not publish the local journal and remote transaction as though they were one atomic commit.

Those deployment-specific checks require the actual source DDL and services and have not been integration-tested here. No cloud databases are contacted in KAN-25 validation. This boundary lets future integration reuse the same business commands and transaction records rather than build a second generator.

KAN-26 Kafka event generation, KAN-27 deterministic scenario framework, cloud provisioning, DMS/CDC setup, legacy-file generation, matching algorithms and source-schema/architecture redesign remain out of scope. Existing architecture and decisions need no edits; AGENTS.md already supplies the ticket workflow. KAN-24's component README is updated to point to this implementation guide.
