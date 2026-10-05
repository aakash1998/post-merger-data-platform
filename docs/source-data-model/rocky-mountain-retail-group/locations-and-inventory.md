# Locations and inventory

All four tables include the [common audit columns](conventions.md) and participate in full-load + I/U/D CDC.

## stores

Grain: one physical retail store. Ecommerce is an order channel, not a fictitious store.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| store_id | bigint | No | PK |
| store_code | varchar(30) | No | Unique business code |
| store_name | varchar(150) | No | Display name |
| store_type | varchar(20) | No | `full_service`, `outlet`, `popup` |
| address_line1 | varchar(200) | No | Street |
| address_line2 | varchar(200) | Yes | Additional line |
| city | varchar(100) | No | City |
| region | varchar(100) | Yes | Province/state |
| postal_code | varchar(20) | Yes | Country-aware requirement |
| country_code | char(2) | No | Country |
| timezone_name | varchar(64) | No | IANA zone |
| phone | varchar(25) | Yes | Contact |
| supports_pickup | boolean | No | Whether new pickup fulfillment is accepted |
| supports_ship_from_store | boolean | No | Whether new shipping fulfillment is accepted |
| lifecycle_status | varchar(20) | No | `planned`, `open`, `temporarily_closed`, `closed` |
| opened_on | date | Yes | Required for open/temporarily_closed/closed |
| closed_on | date | Yes | Required exactly for closed state |

Constraints: closed_on >= opened_on when present. Closure disables new allocations via application rules; historical orders and inventory remain valid. Temporary closure is not permanent closure.

Indexes: unique(store_code); (lifecycle_status, country_code, region). FKs: none.

## warehouses

Grain: one distribution/fulfillment facility.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| warehouse_id | bigint | No | PK |
| warehouse_code | varchar(30) | No | Unique business code |
| warehouse_name | varchar(150) | No | Display name |
| warehouse_type | varchar(20) | No | `distribution`, `fulfillment`, `returns` |
| address_line1 | varchar(200) | No | Street |
| address_line2 | varchar(200) | Yes | Additional line |
| city | varchar(100) | No | City |
| region | varchar(100) | Yes | Province/state |
| postal_code | varchar(20) | Yes | Country-aware requirement |
| country_code | char(2) | No | Country |
| timezone_name | varchar(64) | No | IANA zone |
| phone | varchar(25) | Yes | Contact |
| accepts_returns | boolean | No | Current capability |
| lifecycle_status | varchar(20) | No | `planned`, `active`, `temporarily_closed`, `closed` |
| opened_on | date | Yes | Required for active/temporarily_closed/closed |
| closed_on | date | Yes | Required exactly for closed state |

Constraints: closed_on >= opened_on when present; a returns-only warehouse cannot originate new sales fulfillment (application rule). Indexes: unique(warehouse_code); (lifecycle_status, warehouse_type). FKs: none. Store and warehouse IDs are distinct namespaces.

## inventory

Grain: one product's stock balance at exactly one store or warehouse, including zero-stock rows.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| inventory_id | bigint | No | PK |
| product_id | bigint | No | FK -> products.product_id |
| store_id | bigint | Yes | FK -> stores.store_id |
| warehouse_id | bigint | Yes | FK -> warehouses.warehouse_id |
| quantity_on_hand | integer | No | >= 0; all physically held units, including unavailable/damaged |
| quantity_reserved | integer | No | >= 0; held for fulfillment |
| quantity_unavailable | integer | No | >= 0; damaged/quarantined stock |
| reorder_point | integer | No | >= 0 |
| target_stock_level | integer | No | >= reorder_point |
| last_counted_at | timestamp with time zone | Yes | Physical count event time |

Row-local database invariant: exactly one of store_id/warehouse_id is non-null on every row; reject both-null and both-populated pairs; quantity_reserved + quantity_unavailable <= quantity_on_hand (evaluate sum with bigint arithmetic to avoid integer overflow). Available-to-promise is derived as on_hand - reserved - unavailable, not a separately mutable column. No negative stock/backorders in Phase 1. Product and location FKs are immutable after row creation.

Indexes: partial unique(product_id, store_id) where store_id is not null; partial unique(product_id, warehouse_id) where warehouse_id is not null; (store_id, product_id) where store_id is not null; (warehouse_id, product_id) where warehouse_id is not null. The first pair also supports product lookup. Preserve rows rather than deleting/recreating stock identities.

## stock_movements

Grain: one signed inventory ledger leg. Both physical and stock-state changes are ledgered; this is not a periodically overwritten snapshot.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| stock_movement_id | bigint | No | PK |
| inventory_id | bigint | No | FK -> inventory.inventory_id |
| movement_key | varchar(100) | No | Unique source operation/leg idempotency key |
| movement_type | varchar(25) | No | `opening`, `receipt`, `sale`, `return`, `transfer_out`, `transfer_in`, `adjustment`, `reserve`, `release`, `quarantine`, `unquarantine`, `reversal` |
| quantity_delta | integer | No | Signed change to on_hand |
| reserved_delta | integer | No | Signed change to reserved |
| unavailable_delta | integer | No | Signed change to unavailable |
| occurred_at | timestamp with time zone | No | Physical/business instant; may precede created_at |
| reason_code | varchar(30) | No | `initial_load`, `purchase_receipt`, `fulfillment`, `customer_return`, `location_transfer`, `cycle_count`, `damage`, `allocation`, `allocation_release`, `quality_release`, `correction` |
| reference_number | varchar(100) | Yes | External receipt/count/damage document identifier; descriptive, not an FK; scoped by source_document_type |
| source_document_type | varchar(25) | Yes | `purchase_receipt`, `cycle_count`, `damage_report`, `adjustment`; paired with reference_number for external documents |
| transfer_id | uuid | Yes | Correlation key shared by outgoing/incoming legs |
| shipment_item_id | bigint | Yes | FK -> shipment_items.shipment_item_id; sale lineage |
| return_item_id | bigint | Yes | FK -> return_items.return_item_id; receipt lineage |
| reverses_movement_id | bigint | Yes | Self FK -> stock_movements.stock_movement_id |
| notes | varchar(500) | Yes | Restricted operational note; no customer/payment secrets |

Row checks: at least one delta differs from zero; transfer_id required exactly for transfer_in/out; reverses_movement_id required exactly for reversal and cannot equal self. At most one of shipment_item_id/return_item_id is populated. Sale requires shipment_item_id; return requires return_item_id. Other movement types may retain one optional shipment_item_id or return_item_id for related reservation, quarantine, inspection, disposal, damage, adjustment, or reversal provenance. Shipment/return references remain mutually exclusive. source_document_type and reference_number are both present or both absent; external receipt/count/damage/adjustment documents have no FK because their tables are outside this model. Opening/receipt/return/transfer_in have positive on_hand delta and zero other deltas; transfer_out has negative on_hand delta and zero other deltas. Sale has negative on_hand, zero unavailable, and nonpositive reserved delta bounded in magnitude by units sold. Reserve/release change only reserved positively/negatively; quarantine/unquarantine change only unavailable positively/negatively. Adjustment changes only on_hand, nonzero; reversal negates the original vector by transactional validation. Widen arithmetic before negation/sums.

Indexes: unique(movement_key); (inventory_id, occurred_at, stock_movement_id); partial unique(transfer_id, movement_type) where transfer_id is not null; partial unique(reverses_movement_id) where reverses_movement_id is not null; indexes on shipment_item_id and return_item_id when present. One full reversal per leg; partial corrections use new adjustment legs with references.

Operation coverage: receiving uses receipt/purchase_receipt; stock corrections use adjustment/correction; transfers use paired transfer_out/transfer_in with location_transfer; shipments use sale/fulfillment; returns use return/customer_return plus inspection state legs; reversals use reversal/correction. Damage retained physically uses quarantine/damage; disposal uses atomic unquarantine plus negative adjustment/damage when unavailable, or negative adjustment/damage for available stock. Cycle counts use adjustment/cycle_count for a nonzero variance and update last_counted_at; zero variance updates last_counted_at without a fabricated zero-delta ledger entry. External document references provide provenance without adding receipt, count, or damage tables.

Transactional rules:

- Start every inventory row at zero with an opening movement for nonzero initial stock; update the balance and insert ledger legs atomically. At all times each balance component equals the sum of its ledger deltas. Reversals never edit the original leg. Created/audit values reflect posting time even for late physical events.
- A transfer is two legs for the same product and units at different locations, posted together. This model treats transfer receipt as instantaneous; in-transit ownership and transit shrinkage are outside scope. Lock both balances. Reversing a transfer reverses both legs in one transaction.
- Every optional shipment/return source-document FK must resolve to the same product and the relevant origin/receiving location as inventory, even on adjustment/quarantine/reversal legs. Sale/return movements must match product and location of the linked fulfillment/return receipt. Sales ledger units reconcile to fulfilled shipment items; return receipt ledger units reconcile to return_items.quantity_received. All returned units enter on_hand and unavailable stock together through receipt plus quarantine legs. Inspection releases sellable units from unavailable stock to match quantity_restocked; disposal removes on_hand, releasing unavailable first, to match quantity_disposed. These paired state changes are atomic.
- A late posting cannot force negative current availability; reconcile explicitly instead of bypassing checks. Ledger business fields are append-only after posting; corrections add reversals. Physical delete is a controlled maintenance/test exception, not a normal stock workflow.
