# Fulfillment and returns

All four tables include the [common audit columns](conventions.md), full-load + I/U/D CDC, and restricted-delete FKs. Line bridges are necessary for split fulfillment and partial returns.

## shipments

Grain: one consignment from one origin to one destination, or one store pickup/carryout handover. An order can have many shipments from multiple locations.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| shipment_id | bigint | No | PK |
| shipment_number | varchar(40) | No | Unique business/idempotency number |
| order_id | bigint | No | FK -> orders.order_id |
| fulfillment_type | varchar(15) | No | `ship`, `pickup`, `carryout` |
| origin_store_id | bigint | Yes | FK -> stores.store_id |
| origin_warehouse_id | bigint | Yes | FK -> warehouses.warehouse_id |
| shipping_address_id | bigint | Yes | Order shipping snapshot; composite FK below |
| shipping_address_role | varchar(10) | Yes | `shipping` when address present; otherwise null |
| carrier | varchar(50) | Yes | Carrier identifier |
| tracking_number | varchar(100) | Yes | Carrier tracking reference |
| shipment_status | varchar(20) | No | `planned`, `allocated`, `ready`, `handed_over`, `delivered`, `cancelled` |
| planned_at | timestamp with time zone | No | Business consignment creation |
| ready_at | timestamp with time zone | Yes | Packed/ready instant |
| handed_over_at | timestamp with time zone | Yes | Carrier/customer handover; physical stock leaves here |
| delivered_at | timestamp with time zone | Yes | Delivery completion; pickup/carryout completion equals handover |
| cancelled_at | timestamp with time zone | Yes | Required exactly for cancelled state |
| expected_delivery_on | date | Yes | Promise date; may differ from actual delivery |

Row checks: exactly one of origin_store_id/origin_warehouse_id is non-null in every state; reject both-null and both-populated pairs; pickup/carryout must originate at store. Ship requires address_id + address_role = shipping; non-ship has neither. Composite FK (shipping_address_id, order_id, shipping_address_role) -> order_addresses(order_address_id, order_id, address_role) rejects billing/foreign-order destinations. carrier and tracking_number are both absent or both present; required for handed-over/delivered ship consignments and absent for pickup/carryout. Ready/handed-over/delivered timestamps required once their milestones are reached; handed_over_at >= planned_at and >= ready_at if present; delivered_at >= handed_over_at; cancelled_at >= planned_at. Cancelled consignment has no handover/delivery; planned/allocated/ready have no handover/delivery. Enforce timestamp ordering for all present milestones.

Indexes: unique(shipment_number); unique(shipment_id, order_id); partial unique(carrier, tracking_number) where tracking_number is not null; (order_id, planned_at); (origin_store_id, shipment_status); (origin_warehouse_id, shipment_status); (shipping_address_id, order_id, shipping_address_role); (shipment_status, planned_at).

Transactional rules: nonplanned/noncancelled shipments have at least one line; allocation checks capabilities and stock, pickup origin matches requested pickup store, carryout origin matches order origin. Handover posts sales movements atomically and can occur only once; pickup/carryout handover immediately transitions to delivered. A delivered order can subsequently have return activity without changing the original shipment. Failed/lost parcel claims and replacement orders are outside Phase 1.

## shipment_items

Grain: one order item allocated to one shipment. Multiple shipments may fulfill the same line, but each line appears only once within a given shipment.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| shipment_item_id | bigint | No | PK |
| shipment_id | bigint | No | Parent shipment |
| order_id | bigint | No | Ownership key carried for composite FK enforcement |
| order_item_id | bigint | No | Parent order line |
| quantity | integer | No | > 0; allocated units; frozen at handover |

FKs: (shipment_id, order_id) -> shipments(shipment_id, order_id); (order_item_id, order_id) -> order_items(order_item_id, order_id). These FKs enforce same-order allocation; no separate independent order_id FK is needed. Unique(shipment_id, order_item_id); unique(shipment_item_id, order_item_id, order_id) supports return provenance.

Indexes: unique keys above; (shipment_id, order_id); (order_item_id, order_id); (order_id, shipment_item_id). Transactional checks: fulfillment_type matches line requested_fulfillment; cumulative allocations exclude cancelled shipments and cannot exceed uncancelled ordered units. On cancellation, release reservations and preserve allocation rows; on handover, consume applicable reservations and post one idempotent sale leg per allocation. Product comes from order_items; never duplicate a mutable product FK here.

## returns

Grain: one return authorization (RMA) against an original order. There can be many partial returns per order, including ecommerce returns accepted at a store.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| return_id | bigint | No | PK |
| return_number | varchar(40) | No | Unique business/idempotency number |
| order_id | bigint | No | FK -> orders.order_id |
| return_status | varchar(20) | No | `requested`, `authorized`, `partially_received`, `received`, `rejected`, `cancelled`, `closed` |
| return_channel | varchar(15) | No | `store`, `mail` |
| receiving_store_id | bigint | Yes | FK -> stores.store_id |
| receiving_warehouse_id | bigint | Yes | FK -> warehouses.warehouse_id |
| currency_code | char(3) | No | Original order currency |
| merchandise_refund_amount | numeric(18,2) | No | >= 0; sum of approved line net merchandise refunds |
| tax_refund_amount | numeric(18,2) | No | >= 0; sum of approved line tax refunds |
| shipping_refund_amount | numeric(18,2) | No | >= 0; explicit original shipping fee refund |
| shipping_tax_refund_amount | numeric(18,2) | No | >= 0 |
| refund_total | numeric(18,2) | No | Sum of the four components; approved entitlement, not actual paid refund |
| requested_at | timestamp with time zone | No | Business request |
| authorized_at | timestamp with time zone | Yes | Approval instant |
| first_received_at | timestamp with time zone | Yes | First physical receipt |
| fully_received_at | timestamp with time zone | Yes | All authorized units received |
| resolved_at | timestamp with time zone | Yes | Required exactly for rejected/cancelled/closed |

Row checks: exactly one of receiving_store_id/receiving_warehouse_id is non-null in every state, including requested/rejected/cancelled; reject both-null and both-populated pairs. Select the intended receiving facility when creating the RMA and retain it on rejection/cancellation; this reference is a routing decision, not proof of receipt. Assigned store-channel location must be store; mail may route to warehouse or store. Authorized/partially_received/received/closed require authorized_at; partially_received/received/closed require first_received_at; received/closed require fully_received_at. requested/rejected/cancelled cannot have receipt timestamps; rejection applies before authorization, cancellation before receipt. Present timestamps follow requested <= authorized <= first_received <= fully_received <= resolved, omitting absent milestones. Zero entitlement is allowed for replacements handled as separate new orders or nonrefundable goods; no exchange table is proposed.

Indexes: unique(return_number); unique(return_id, order_id); (order_id, requested_at); (receiving_store_id, return_status); (receiving_warehouse_id, return_status); (return_status, requested_at).

Application rules: authorization requires at least one item, a valid receiving facility, and fulfillment provenance. Cancellation/rejection releases authorized return capacity. Closed requires receipt/inspection complete and approved entitlement settled via successful linked payment refunds (or zero entitlement); post-authorization entitlement amendments are audited, with no reduction below amounts already refunded. Refunds may be multiple operations against multiple original captures. Header totals reconcile to lines, and currency matches order.

## return_items

Grain: one RMA line for one fulfilled shipment-item allocation. A return spanning several shipments creates several rows, even for the same original order item.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| return_item_id | bigint | No | PK |
| return_id | bigint | No | Parent return |
| order_id | bigint | No | Ownership key for composite FKs |
| order_item_id | bigint | No | Original sold line |
| shipment_item_id | bigint | No | Exact fulfilled allocation; mandatory provenance |
| quantity_requested | integer | No | > 0 |
| quantity_authorized | integer | No | 0..quantity_requested |
| quantity_received | integer | No | 0..quantity_authorized |
| quantity_restocked | integer | No | 0..quantity_received; sellable units only |
| quantity_disposed | integer | No | >= 0; restocked + disposed <= received |
| reason_code | varchar(25) | No | `changed_mind`, `wrong_size`, `damaged`, `defective`, `wrong_item`, `other` |
| disposition | varchar(20) | No | `pending`, `restock`, `dispose`, `mixed` |
| merchandise_refund_amount | numeric(18,2) | No | >= 0; net of original discount |
| tax_refund_amount | numeric(18,2) | No | >= 0; original allocated tax |
| last_received_at | timestamp with time zone | Yes | Latest receipt business instant; required exactly when received > 0 |
| inspected_at | timestamp with time zone | Yes | Final inspection instant; required for nonpending disposition |

FKs: (return_id, order_id) -> returns(return_id, order_id); (order_item_id, order_id) -> order_items(order_item_id, order_id); (shipment_item_id, order_item_id, order_id) -> shipment_items(shipment_item_id, order_item_id, order_id). Together these prevent cross-order/cross-product return associations. Unique(return_id, shipment_item_id); unique(return_item_id, return_id, order_item_id, order_id) supports exact refund-allocation ownership.

Indexes: unique key above; (return_id, order_id); (order_item_id, order_id); (shipment_item_id, order_item_id, order_id); (order_id, return_item_id). Row checks: inspected_at >= last_received_at when present; pending has no inspected_at; final disposition requires restocked + disposed = received > 0; restock has disposed = 0, dispose has restocked = 0, mixed requires both positive. Refund amounts are zero if quantity_authorized = 0.

Transactional checks: only handed-over/delivered allocations are returnable. Sum of authorized units on noncancelled/nonrejected RMAs per allocation <= shipped units; lock allocation before authorizing. Sum of received units cannot exceed shipped units. Partial receipts post idempotent stock legs (movement_key includes return item and receipt operation ID); quarantine pending-inspection units, release on restock or dispose by appropriate ledger legs. Inspection and balance updates are atomic; final inspection follows all receipts for that item. For pending items, received - restocked - disposed is inspection/quarantine stock, not available stock.

Refund allocation uses original discounted line amounts and taxes, capped across **all** returns at original line net and tax amounts. Allocate cents proportionally by unit, with the final returnable unit taking any rounding residual; never refund current catalog price. Shipping/shipping-tax refunds across RMAs cannot exceed original header amounts. Cancellation refunds and return refunds share capture limits and order-level entitlement checks, so one cancelled/returned unit cannot be refunded twice. Rejected/cancelled return rows preserve proposed amounts but confer no payable entitlement.
