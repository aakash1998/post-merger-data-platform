# Deterministic scenarios — KAN-27

Named local recipes orchestrate the existing KAN-24 seed exporter, KAN-25 Activity/FileStore business commands and KAN-26 event plan/producer. No second generator, new schema/domain, database/Kafka connection, provisioning or ingestion is introduced. Python 3.11+ with IANA timezone data and POSIX locks (macOS/Linux) is required. All code/tests use the standard library.

## Run, compare and replay

From the repository root:

```sh
PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios --list

PMDP_ENV=test PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --scenario returns_refunds --seed 27 \
  --output source-simulator/generated/test/returns-a

# A separate run produces identical artifact bytes, not just similar counts.
PMDP_ENV=test PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --scenario returns_refunds --seed 27 \
  --output source-simulator/generated/test/returns-b

# Reads the original saved configuration automatically.
PMDP_ENV=test PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --output source-simulator/generated/test/returns-a --replay
```

Installed entry point: `pmdp-scenario`. Required PMDP_ENV is dev/test; prod is rejected. `--list` is read-only and needs no environment. Select dedicated directories under the existing ignored generated/ tree. A scenario output is an immutable bundle; do not mutate its database journal with the continuous CLI or add files. An identical invocation verifies/reuses it. Changed config, environment, Python version or simulator implementation requires a new output; there is no overwrite flag.

## Named recipes

| Name | Scripted source behavior / event controls |
| --- | --- |
| normal | New customers in both companies; RMRG order/payment/fulfillment/delivery; SCC invoice/payment; both inventory changes. No injected delivery edges |
| duplicate_replay | Fulfilled RMRG order and paid SCC invoice; exact last-transaction replay in each source has no second effect. Each original Kafka record has one identical duplicate delivery |
| late_out_of_order | RMRG fulfillment and complete return/refund, SCC invoice/payment; seeded late/reorder sampling (50% each, shifts 15/4 slots) |
| customer_updates | Register and update customers in both sources, preserving PKs and source audits/quality behavior |
| cancellations | New uncaptured RMRG order followed by cancellation, capture failure confirmation, authorization void when applicable, reservation release |
| returns_refunds | RMRG order/payment/complete fulfillment, return request/authorization/receipt/quarantine/inspection/refund request/confirmation |
| inventory_changes | RMRG stock receipts with ledger legs; SCC mutable reported balance observations |
| scc_messy | Seed messy_fraction forced to 1; legacy customer changes, invoice correction, cashbook posting and stale-audit flag correction, inventory observation, abandoned invoice/child-line deletion |

Recipes repeat `rounds` times. Fulfillment progresses eligible consignments using the existing command implementation until delivery, with a bounded convergence guard. Return progression uses the existing four post-request stages. A command with no eligible/changed entity fails explicitly rather than silently skipping the requested scenario. Recipes do not select arbitrary source PKs or modify business rules; seeded selection within eligible entities remains KAN-25 behavior. Some custom seeds/configs can produce a no-op update; that is a reproducible failure, not a claimed successful scenario.

SCC logical orphans, duplicate codes/balances, raw units/currency and imperfect audits remain permitted; enforced FKs remain intact. No SCC shipment/return data is fabricated. Refund/disposal outcomes vary with the selected seed but repeat exactly for that seed. Existing one-unit/one-RMA-per-order and cancellation coverage limits are unchanged. The default late recipe is tested to invert event time within an aggregate; very small event counts or other seeds need not include every business milestone or edge case.

## Configuration

```sh
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --config source-simulator/config/scenario-small.json \
  --scenario customer_updates --seed 42 \
  --output source-simulator/generated/dev/customers-42
```

`--scenario` and `--seed` override JSON fields. All other controls are JSON:

| Field | Default | Meaning |
| --- | --- | --- |
| name | normal | Built-in recipe name |
| seed | 27 | Integer, including zero; shared root seed supplied to independent seed/activity/event PRNGs |
| clock_start | 2025-04-01T12:00:00+00:00 | Fixed UTC logical start; must be on/after seed snapshot boundary |
| step_seconds | 60 | Positive integer logical clock increment for each command, including source replay |
| rounds | 1 | Positive recipe repeat count |
| event_count | 200 | Positive original event count; duplicate recipe emits twice this many deliveries |
| seed_config | {} | KAN-24 Config overrides; root seed is set only at scenario level |

Resolved seed defaults: start_date 2025-01-01, days 30, RMRG/SCC customers 24/16, products 16/12, both order counts zero, RMRG stores/warehouses 2/1, SCC locations 2, max_lines 3. Remaining KAN-24 defaults (including cross-company overlap) apply. Changing the seed date window may require moving clock_start forward. Recipes require a **masters-only baseline with zero initial orders** so prerequisite selection and lifecycle coverage remain controlled; source changes create the transaction facts. For general historical datasets use the existing seed CLI. `scc_messy` intentionally overrides a supplied messy_fraction to 1 and records the resolved value in the manifest.

## KAN-31 topic routing

All eight recipes use the same five-domain routing as KAN-26. Tests validate each generated delivery against its company/event_type domain while comparing exact artifact bytes across independent runs and different Python hash seeds. Event types, payload semantics, source mutations and delivery edge behavior are preserved. Use new output directories after this implementation change: the implementation fingerprint rejects previous bundles, and legacy topic routes fail validation. Real Aiven provisioning and smoke validation are separate from these local recipes; see the [runbook](../../infrastructure/kafka/README.md).

## Exact reproduction boundary

There are no wall-clock business timestamps or fresh UUIDs in scenario artifacts. Seeds go to local PRNGs, commands use the fixed virtual clock, and the event run ID derives from the canonical scenario fingerprint. Every event plan uses KAN-26's shared create_plan function. Events draw from the **final scenario source state**, so cancellation/return/refund milestones are available. Its snapshot_fingerprint represents the final-state hash rather than the initial seed export; seed provenance remains separately recorded. produced_at is one logical step after the last script command. Existing KAN-26 historical-fact versus simulated-session semantics remain intact.

Fingerprint inputs include scenario version, complete requested/resolved config, environment, simulator Python/schema file hashes and exact Python version. Output paths, wall-clock time and Python hash randomization do not participate. Exact reproduction requires the same implementation, Python version, configuration/environment and IANA timezone rules; pin the runtime/timezone data for comparisons across machines. This is not a promise of identical output across future code, Python/PRNG or timezone-rule changes. The standalone continuous/event CLIs retain their current live clock/random-run defaults; use this runner when exact reproduction is required.

Generation runs by finite command/event counts as fast as local validation/persistence allows, without real shipping delays or elapsed-time cutoffs. Real-time execution speed and logs/temporary paths are not part of the reproducibility contract. For later paced delivery, the saved plan can be supplied to the existing events.run producer API; delivery rate affects transport timing, not saved bytes or logical business times. There is no cross-system distributed transaction or live change-to-event capture claim.

## Artifacts, failure and recovery

| Artifact | Purpose |
| --- | --- |
| seed/ | Complete KAN-24 baseline and matching truth/manifest |
| database/baseline.json and transactions/ | KAN-25 durable source baseline and contiguous I/U/D journal with PK highwaters |
| commands.json | Company, command, sequence, logical timestamp and commit/replay outcome; no customer rows in logs |
| final-state.json | Final approved relational rows for inspection/reconciliation |
| events/plan.json and deliveries/ | KAN-26 ordered Kafka-shaped records, injection annotations and acknowledged local deliveries |
| scenario.json | Version/config/implementation identity, fingerprints, command/transaction/delivery counts, final-state hash, file checksums/sizes and manifest checksum |

The output is built in a temporary sibling directory and renamed only after every phase completes. Files and publication directory are fsynced; a per-output parent lock excludes another builder. Exceptions discard staging; no partial completed output is published. These are local simulator control artifacts, not source columns, CDC contracts or ingestion formats.

Optional failure control for demos/tests:

```sh
# Expected exit 1 after the third command, with no published bundle.
PMDP_ENV=test PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --scenario normal --output source-simulator/generated/test/failure-demo \
  --fail-after-commands 3

# Omit the failure control to regenerate the same intended run from the start.
PMDP_ENV=test PYTHONPATH=source-simulator/src python3 -m retail_simulator.scenarios \
  --scenario normal --output source-simulator/generated/test/failure-demo
```

Failure control is an execution fault, excluded from business identity. It applies only to new builds and is rejected with --replay; a completed output is verified/reused without reexecuting commands. A threshold beyond the recipe's command count does not fire. Exception failures clean staging; SIGKILL/power loss can leave a hidden temporary sibling directory that is never accepted as completed output. There is no mid-script resume/checkpoint: interrupted builds regenerate deterministically from the start.

`--replay` checks all artifact/manifest hashes, reconstructs source state from the KAN-25 journal, compares the recovered state hash, replays the **last** source transaction with no new effect, and verifies every existing local event acknowledgement against exact plan bytes. It does not treat a much older transaction as eligible source replay or append more events. Any corruption/missing/extra file or configuration/implementation mismatch fails closed. Replaying existing local deliveries is distinct from injected duplicate business events, which already occupy separate sequences. Existing state/producer locks still exclude competing writers.

Local memory, journal recovery work and delivery-file count grow with source size/rounds/event_count. Keep fixtures bounded. No real PostgreSQL/MySQL/Kafka/cloud integration is tested or performed.

## Validation and documentation review

```sh
PYTHONPATH=source-simulator/src python3 -m unittest discover -s source-simulator/tests -v
```

Tests compare every artifact byte for all eight recipes, repeat runs in separate CLI processes with different PYTHONHASHSEED values, change seeds/configs, inspect business/quality outcomes, validate exact replay without extra effects, and exercise command/disk failures, restart, configuration/environment/corruption/implementation rejection. Existing seed/change/event tests remain regression coverage.

README links to this runner; the continuous/event guides distinguish standalone execution from deterministic orchestration. KAN-26 plan construction is extracted into a shared helper without changing its standalone defaults. Approved source docs, architecture, naming conventions and AGENTS.md require no edits.
