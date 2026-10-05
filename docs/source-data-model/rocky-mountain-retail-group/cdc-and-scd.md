# CDC scope and future analytical history

This document specifies requirements for later contracts, not an ingestion implementation. The locked path remains PostgreSQL on Aiven -> AWS DMS -> S3 -> Databricks/Delta -> Snowflake/dbt. CDC and event contracts remain pending agreement.

## Complete proposed CDC allowlist

Every table needs an initial consistent baseline plus ongoing inserts, updates, and deletes. No table is insert-only at the capture layer, even where normal business writes are append-only.

| Source table | Capture | Reason |
| --- | --- | --- |
| rmrg.customers | Full load + I/U/D | Identity, lifecycle, contact/privacy changes |
| rmrg.customer_addresses | Full load + I/U/D | Current addresses/defaults and retirements |
| rmrg.product_categories | Full load + I/U/D | Classification and hierarchy changes |
| rmrg.products | Full load + I/U/D | Catalog, price/cost, lifecycle |
| rmrg.stores | Full load + I/U/D | Retail geography/capabilities/lifecycle |
| rmrg.warehouses | Full load + I/U/D | Facility geography/capabilities/lifecycle |
| rmrg.inventory | Full load + I/U/D | Current balances and replenishment settings |
| rmrg.stock_movements | Full load + I/U/D | Ledger and explicit reversals; controlled maintenance deletes |
| rmrg.orders | Full load + I/U/D | Sale lifecycle and fixed original totals |
| rmrg.order_addresses | Full load + I/U/D | Historical destination and approved amendments/privacy changes |
| rmrg.order_items | Full load + I/U/D | Sale line, snapshots and cancellation changes |
| rmrg.payments | Full load + I/U/D | Attempt settlement and refund chains |
| rmrg.payment_allocations | Full load + I/U/D | Capture/refund attribution and component reconciliation |
| rmrg.shipments | Full load + I/U/D | Allocation, handover, delivery lifecycle |
| rmrg.shipment_items | Full load + I/U/D | Allocation details and split fulfillment |
| rmrg.returns | Full load + I/U/D | Authorization, receipt, refund entitlement |
| rmrg.return_items | Full load + I/U/D | Partial receipt, disposition, unit/refund allocation |

All tables have a stable non-null single-column PK; consumers use `(source_system = 'rmrg', source_schema, source_table, primary_key)` as the source identity. Local bigint values must never be assumed unique across companies or tables. Global identity resolution is future integration work, not a source key change.

Logical replication permissions/settings, source-version support, replication slots, WAL retention, selected decoding plugin, and replica identity need verification against the actual Aiven/DMS environment before implementation. PostgreSQL source CDC limitations and replica-identity behavior are described in the [AWS DMS PostgreSQL source documentation](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Source.PostgreSQL.html). Do not assume complete before-images on update/delete or prescribe REPLICA IDENTITY FULL as a universal solution. The later CDC contract must prove exact emitted fields with insert/update/delete fixtures.

## Deletes, replay, ordering, and schema changes

- Business retirement/discontinuation/anonymization normally emits updates. Transaction facts and ledger rows are retained; no application cascade deletes. Controlled physical deletes of unreferenced drafts/test rows and approved maintenance must still yield keyed CDC delete records. Referential cleanup happens child-first when explicitly authorized.
- Delete payloads may carry only keys. Downstream code must delete/tombstone by source key using the prior materialized state; deleted_at cannot be recovered from a vanished source row. There is no common source deleted_at column pretending otherwise.
- created_at/updated_at and row_version are preserved, but **none is the global CDC cursor**. Capture operation, source transaction/commit ordering, sequence within a transaction where available, baseline boundary, and ingestion/file provenance must be agreed in the DMS-to-S3 contract. An event time cannot override a newer committed update.
- Replay should converge to one current row per source key. Determine a stable CDC event identity/order from actual DMS output before building deduplication. Repeated business requests are prevented by source request/number keys; repeated CDC delivery must not be deduplicated solely on business number or updated_at.
- Foreign-key parents and children can land at different times/files. Bronze preserves raw changes, while later Silver reconciliation waits/retries/quarantines unresolved associations; source consistency does not guarantee ingestion arrival order. Aggregates spanning payments/stock/order updates must respect complete transaction boundaries or a reconciliation watermark.
- The baseline must include zero-stock rows, draft records, retired dimensions and historical facts needed for reconciliation. Agree full-load/CDC boundary and retention explicitly. No filtering only to active records at capture time.
- Immutable PKs simplify updates/deletes. Schema changes are reviewed/versioned; add nullable columns first when appropriate, populate safely, then tighten constraints. Renames, type changes, destructive drops, key changes, and new status values require consumer compatibility review and CDC validation before deployment.
- Late business activity retains occurred_at/attempted_at/requested_at and source audit timestamps separately. Backdated business time does not mean backdated database commit time.
- PII updates also require downstream privacy handling. Retaining old address/customer values in SCD2 forever is not a privacy strategy; approved erasure must apply to current, historical, raw, and exported copies under the eventual retention policy.

## Proposed downstream analytical SCD candidates

SCD Type 1 (overwrite analytical attributes) and Type 2 (version analytical attributes) are downstream analytics behaviors, not source-table behaviors. Operational updates continue to follow the source contracts; do not add dimensional surrogate keys, valid_from/valid_to, or is_current to operational tables. The rules below are recommendations pending agreement, especially whether a changed value is a correction or a real business change.

| Source table feeding analytics | Downstream Type 1 candidates | Downstream Type 2 candidates | Downstream fact/snapshot treatment and source invariants |
| --- | --- | --- | --- |
| customers | first_name, last_name spelling corrections; email, phone, preferred_language current contact view | loyalty_tier, lifecycle_status for segmentation; marketing_opt_in only if approved historical consent analysis | IDs/number immutable; anonymization overrides historical retention; audit times are source evidence |
| customer_addresses | recipient/address/phone typo corrections, address_label | Genuine move: address_line1/2, city, region, postal_code, country_code; default roles if historical attribution needed | archived_at marks retirement; order snapshots remain independent |
| product_categories | category_name/description spelling, sort_order cosmetic changes | parent_category_id, is_active, substantive category meaning/name changes | IDs/code stable; analytical hierarchy history needs cycle-free point-in-time joins |
| products | product_name/description typo correction, barcode correction | category_id, brand, substantive name/style/size/color changes, list_price, standard_cost, currency_code, lifecycle_status | IDs/SKU stable; sales use order-time price/name/cost snapshots rather than current dimension values |
| stores | Contact/name/address typo corrections, phone | Genuine relocation (address fields), timezone_name, store_type, supports_pickup, supports_ship_from_store, lifecycle_status | opened_on/closed_on are business milestones, not effective timestamps by themselves |
| warehouses | Contact/name/address typo corrections, phone | Genuine relocation, timezone_name, warehouse_type, accepts_returns, lifecycle_status | Facility keys remain stable; opening/closing milestones preserved |
| inventory | Corrections to current configuration when explicitly classified as errors | reorder_point, target_stock_level if replenishment-policy history is needed | quantity_on_hand/reserved/unavailable: balance facts/periodic snapshots plus ledger, not a dimension version per movement |
| stock_movements | None for posted business fields | None | Append-only ledger with reversal facts; audit corrections must not rewrite quantities |
| orders | Approved pre-handover contact correction | None in a customer/product dimension | Transaction fact/lifecycle history; original totals freeze; do not model every status as a dimension version |
| order_addresses | Approved pre-handover correction; privacy erasure | None by default | Historical transaction snapshot; separate amendment history only if business requires it |
| order_items | Pre-placement description correction only | None | Original price/cost/name snapshots and cancellation changes are transaction facts |
| payments | Sanitized failure-code correction on nonsettled data, if authorized | None | Successful terminal operations immutable; capture/refund are separate facts |
| payment_allocations | Pending-operation administrative correction only | None | Capture/refund component fact; immutable once parent operation is terminal |
| shipments | Pre-handover tracking/plan correction | None | Fulfillment lifecycle and milestone facts |
| shipment_items | Pre-handover allocation correction | None | Fulfilled unit allocation fact; frozen at handover |
| returns | Approved administrative correction before resolution | None | Return authorization/receipt/entitlement facts |
| return_items | Reason-code correction before resolution | None | Returned quantity, disposition, and refund facts |

A literal column cannot simultaneously follow Type 1 and Type 2 without a rule distinguishing corrections from real changes. Initially classify ambiguous master-data changes as Type 2 for traceability, subject to privacy controls; authorized correction workflows can explicitly request Type 1. Different reporting dimensions may expose a current-contact view alongside historical segmentation without duplicating operational truth.

Default analytical SCD2 validity is based on agreed **source commit order/time**, with half-open intervals and deterministic handling of tied timestamps. Business-effective backdating requires a separate agreed effective-time/change-reason contract; updated_at alone cannot distinguish a typo, real move, or historical correction. Customer registration and facility dates are not automatically SCD validity boundaries. Current-state tables alone cannot reconstruct history predating the baseline. Category reparenting must define whether descendant analytical paths also get recomputed/versioned; do not infer this from a leaf product update.
