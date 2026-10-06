# Kafka event generator — KAN-26

For exact independent-run reproduction (including stable run IDs/timestamps and scripted source context), use the [KAN-27 scenario runner](deterministic-scenarios.md). The standalone event CLI retains its fresh run UUID/time; both use the shared plan builder.

Produces business events for the locked Kafka -> Databricks path. Local mode requires Python 3.11+, IANA timezone data and a completed KAN-24 snapshot; no broker, credentials, cloud services or new dependencies. It never modifies relational data. KAN-25 owns database changes; CDC remains DMS -> S3.

This is a **simulator v1 event contract for review**, not approval/deployment of platform event contracts or Kafka topics. No approved event payload dictionary was found in the existing docs. Architecture and relational schemas are unchanged.

## Run and resume

Generate the seed using the [seed instructions](../README.md), then run from the repository root:

```sh
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator.events \
  --snapshot source-simulator/generated/dev/seed-24 \
  --config source-simulator/config/events-small.json \
  --output source-simulator/generated/dev/events-26 \
  --rate 10 --duration 30
```

Resume the saved plan without snapshot/config arguments:

```sh
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator.events \
  --output source-simulator/generated/dev/events-26 \
  --rate 20 --until-complete
```

Installed entry point: `pmdp-event`. Required `PMDP_ENV=dev|test` must match the seed/plan; prod is rejected. Output must be outside the immutable seed. A new output directory creates a new plan; existing plans reject snapshot/config arguments. SIGINT/SIGTERM stop between acknowledged records and flush before exit. `--until-complete` removes the duration limit, not the finite event count.

`plan.json` stores run UUID, config, snapshot fingerprint, checksum and ordered deliveries. `deliveries/000000000001.json`, etc., store sequence, environment and Kafka-shaped record (topic, key, JSON string value). Plan delivery annotations are simulation provenance, not business payload or Kafka offsets. Use the existing ignored `source-simulator/generated/` directory.

Rate limits new deliveries, including deliberate duplicates, per second. Slow acknowledgements apply backpressure without catch-up bursts. Duration uses a monotonic clock. Already acknowledged local prefix verification uses no rate slots. Rate can change on resume without changing identities/order.

## Workload and edge configuration

Optional JSON maps directly to `EventConfig`:

| Setting | Default | Meaning |
| --- | --- | --- |
| events | 1000 | Original events before duplicate injection; positive integer |
| seed | 26 | Local PRNG seed |
| duplicate_fraction | 0.05 | Probability of one extra identical delivery per original |
| late_fraction / reorder_fraction | 0.10 / 0.10 | Probabilities of shifting later by the corresponding slots |
| late_slots / reorder_slots | 120 / 5 | Positive scheduling-position shifts before delivery sorting |
| rmrg_weight / scc_weight | 3 / 1 | Company selection weights for new sessions |

Fractions must be finite in [0,1]; weights/shifts finite and positive. Shifts preserve event time, key, ID and exact bytes while allowing later-generated events to arrive first. Slots describe relative delivery ordering, **not guaranteed wall-clock delay durations**; the tail compresses after sorting. Applying the same shift to every event does not cause inversions; mixed fractions exercise disorder. Historical fact replay is inherently late relative to current delivery. No watermark logic is implemented.

Each original is selected once per plan, apart from explicit duplicate injection. Copies have identical topic/key/value, including event_id and timestamps; sequence is transport identity, not business identity. Probabilities do not guarantee every small plan contains every case. Same seed, snapshot, run ID and timestamp reproduce a plan; fresh invocations use a new run ID/time. This is ordinary configurable generation, not KAN-27's deterministic scenario framework.

While facts remain, generation selects the next chronological historical fact with probability 65%, otherwise a shopping session; exhausted facts give way to sessions. A small plan need not exhaust the source or cover every type. Recent sessions interleaved with historical facts can already overtake old facts. Baseline opening-stock legs are excluded to avoid dominating operational activity. Products reuse KAN-24's bestseller skew: the first 20% receive 65% of selections. About 35% of views add an item, quantities favor one unit, and sessions can abandon without conversion. Roughly 25% are guests; SCC WALKIN selections also remain anonymous. Source masters retain cross-company overlap and messy SCC codes.

## Envelope, identity and versions

JSON values contain `event_id`, `event_type`, `event_version=1`, `payload_version=1`, `environment`, `company`, `source_instance`, `aggregate_key`, UTC `occurred_at`, UTC `produced_at`, `producer`, `payload` and `provenance`.

`occurred_at` retains the source milestone for fact replay or a recent synthetic session instant. `produced_at` is the saved plan generation time, not actual broker/ingestion time; it is unchanged by delayed delivery/resume. Session times are virtual recent activity independent of delivery rate. Facts preserve raw source timestamp, source table/PK, nullable updated_at, fingerprint and timezone assumptions. They do not pretend historical sales are new sales today. SCC records with missing transaction instants are skipped; business_date alone never becomes fabricated midnight activity. Naive local instants use the documented America/Edmonton assumption with `timezone_assumed=true`; DST-ambiguous instants are not claimed as verified UTC evidence. Resolving legacy timezone ambiguity remains downstream contract work.

Key: `<company>:<company>-retail-<env>:<aggregate-type>:<id>`. Order milestones use order PK, never printed number, email, SKU, barcode or WALKIN code. Orderless SCC postings use payment PK; RMRG stock uses inventory PK; SCC stock uses stock_balance PK so duplicate item/location pairs retain distinct identity. Sessions use run-qualified session IDs independently of customer identity. Nullable/orphan SCC references remain raw. No source identity is replaced with an inferred enterprise key.

IDs are SHA-256 over qualified aggregate, event type, major version and occurrence identity. Fact identity includes snapshot fingerprint, source table/PK and milestone time; session identity includes run/session. Saved-plan replay preserves exact bytes. A fresh replay of the same snapshot preserves fact IDs/business payloads but can change produced_at; another snapshot changes fingerprint/IDs. This is **snapshot-qualified replay identity**, not a production application idempotency guarantee across arbitrary exports.

Decimals serialize as strings, dates as ISO strings, nulls as null. Source IDs remain JSON integers in payloads; consumers must parse BIGINT losslessly. Qualified keys/provenance PKs are strings. Payloads export no names, contacts, addresses, payment secrets or matching-truth labels. Raw SCC currency labels, signed amounts, codes, flags and discrepancies remain unnormalized.

Topic: `pmdp-<env>-<company>-<domain>-<event>-v1`, following KAN-18. Examples: `pmdp-dev-rmrg-orders-placed-v1`, `pmdp-test-scc-payments-posted-v1`. Incompatible envelope/payload changes require a new major topic/contract; compatible optional additions may stay v1. Consumers must check both versions; current validators reject unsupported versions. No schema registry or topics are provisioned.

## Event types and payload fields

The exact dictionary is [event_generation.py](../src/retail_simulator/event_generation.py); selected source field types/nullability follow the approved source dictionaries.

| Company / event_type | Evidence / payload |
| --- | --- |
| RMRG orders-placed / orders-cancelled | placed_at / cancelled_at; order_id, order_number, customer_id, channel, order_total, currency_code. Original totals, not net cancellation revenue |
| RMRG payments-resolved | processed_at, excluding pending; payment_id, order_id, parent_payment_id, return_id, operation_type, payment_method, payment_status, amount, currency_code, failure_code. Authorization/void/failure are not collected revenue |
| RMRG shipments-handed-over / shipments-delivered | Actual milestones; shipment_id, order_id, fulfillment_type, origin_store_id, origin_warehouse_id. Pickup/carryout may have equal milestone times |
| RMRG returns-requested / returns-received | requested_at / fully_received_at; return_id, order_id, return_channel, receiving_store_id, receiving_warehouse_id. Receipt is not refund settlement |
| RMRG inventory-moved | occurred_at; stock_movement_id, inventory_id, movement_type, quantity_delta, reserved_delta, unavailable_delta, reason_code. Preserve signs; exclude opening legs |
| SCC orders-entered | entered_at; sales_order_id, order_number, customer_id_ref, customer_code_ref, sales_channel, total_amount, currency_text, business_date. Reported document evidence, not a modern immutable accepted-order contract |
| SCC payments-posted | transaction_time; payment_transaction_id, sales_order_id, order_number_ref, transaction_type, tender_code, amount, currency_text, posted_flag. Observed cashbook posting, including uncertain flags/refunds, not guaranteed settlement |
| SCC inventory-observed | balance_as_of; stock_balance_id, item_id, location_id, quantity_on_hand, quantity_allocated, unit_code. Reported snapshot, not a stock movement or summable duplicate balance |
| Both shopping-viewed / shopping-added | session_id, nullable customer_id, product_id/sku (RMRG) or item_id/item_code (SCC), channel; added includes positive quantity. RMRG web / SCC assisted_store are simulated instrumentation, not new database capabilities |

No SCC shipment/return events are fabricated from nonexistent source tables; its legacy files remain separate. No transition history is reconstructed from mutable SCC current rows. Replay uses available snapshot milestones, not complete historical coverage, and does not subscribe to KAN-25 or emit a second CDC channel.

## Producer boundary, recovery and limits

`Producer.send(sequence, Record)` returns after acknowledgement or raises; `flush()` runs on normal stop and delivery failure. Local transport atomically publishes/fsyncs each delivery and its directory, with a lifetime POSIX writer lock. Restart replays/verifies the contiguous prefix against the saved plan without adding files, including publication-before-ack crashes. Conflicting bytes, checksum/environment mismatches and filename gaps fail closed. Deliberately duplicated events have separate delivery sequences; local retry identity is not Kafka partition/offset identity.

`KafkaProducerAdapter` accepts injected `submit(topic, key_bytes, value_bytes, headers)` and `flush()` callables. Submit returns an object with `result(timeout=...)` resolving **on broker acknowledgement**, not enqueue. Headers carry event_id and both versions. A future Aiven binding constructs a client using configured endpoints/auth/TLS (`PMDP_KAFKA_BOOTSTRAP_SERVERS` plus external secret configuration), translating client callbacks/futures into this interface. It must not auto-create topics. KAN-30/31 own provisioning/topics/retention. No real Kafka dependency or connection is introduced here.

Uncertain broker acknowledgement stops delivery. Replaying the saved plan retains identities but may redeliver acknowledged records: remote semantics are **at-least-once**, not exactly-once or a durable Kafka resume checkpoint. Consumers must deduplicate event_id. Client/TLS/auth binding, remote checkpoints, real partition behavior and broker failures require later integration tests. Keys support per-topic partition affinity; different milestone topics have no cross-topic order guarantee. Arrival order is never causal order.

Planning loads the seed/fact catalog and materializes a finite plan; memory grows with source size/event count. Local file count grows with deliveries. Tune batch size and use separate outputs for larger experiments; this is a local demo/test transport, not a production-scale event store. The generator samples representative sessions/replays, not a complete retail application.

## Validation and existing-documentation review

```sh
PYTHONPATH=source-simulator/src python3 -m unittest discover -s source-simulator/tests -v
```

Tests exercise source fidelity/no mutations, nullable SCC audit/missing instants, stable identities, anonymous session references, exact duplicates/reordering, version/environment/checksum rejection, rate/duration/stop, restart/lost acknowledgements, locking/disk failures, and injected Kafka bytes/headers/ack failures. Real broker integration remains untested.

Existing docs need the new run-guide link in source-simulator README and entry point in packaging. Architecture, approved source dictionaries, naming conventions and AGENTS.md require no correction. No deterministic scenario DSL, infrastructure, ingestion or database mutation changes are included.
