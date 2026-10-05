# Orders and payments

All five tables include the [common audit columns](conventions.md) and participate in full-load + I/U/D CDC. Transactional rules below are mandatory future implementation requirements, not implied row CHECK constraints.

## orders

Grain: one commercial order, with multiple lines, fulfillment consignments, and payment operations permitted.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| order_id | bigint | No | PK |
| order_number | varchar(40) | No | Unique customer-facing business number |
| order_request_key | varchar(100) | No | Unique creation idempotency key, namespaced by calling application |
| customer_id | bigint | Yes | FK -> customers.customer_id; null for guest |
| channel | varchar(20) | No | `store`, `web`, `mobile`, `call_center` |
| origin_store_id | bigint | Yes | FK -> stores.store_id; required exactly for store channel |
| fulfillment_preference | varchar(20) | No | `ship`, `pickup`, `carryout`, `mixed` |
| order_status | varchar(25) | No | `draft`, `placed`, `processing`, `partially_fulfilled`, `fulfilled`, `cancelled`, `closed` |
| currency_code | char(3) | No | Single currency for this order, lines, payments and returns |
| contact_email | varchar(254) | Yes | Order-time contact snapshot, independent of current customer |
| contact_phone | varchar(25) | Yes | Order-time contact snapshot |
| merchandise_subtotal | numeric(18,2) | No | >= 0; sum of gross line amounts |
| discount_total | numeric(18,2) | No | >= 0; sum of line discounts |
| merchandise_tax_total | numeric(18,2) | No | >= 0; sum of line taxes |
| shipping_amount | numeric(18,2) | No | >= 0; header shipping fee before tax |
| shipping_tax_amount | numeric(18,2) | No | >= 0 |
| order_total | numeric(18,2) | No | >= 0; equation below |
| placed_at | timestamp with time zone | Yes | Required for every state other than draft |
| cancelled_at | timestamp with time zone | Yes | Required exactly for cancelled state |
| closed_at | timestamp with time zone | Yes | Required exactly for closed state |

Row checks: discount_total <= merchandise_subtotal; order_total = merchandise_subtotal - discount_total + merchandise_tax_total + shipping_amount + shipping_tax_amount; cancellation/closure >= placed_at; draft has no placement/cancellation/closure timestamps. A cancelled order is wholly unfulfilled; partial cancellations live on lines and do not make the entire order cancelled. Closed means post-sale workflow settled, not that return facts vanish.

Unique(order_id, customer_id) supports registered-address ownership. Indexes: unique(order_number); unique(order_request_key); (customer_id, placed_at, order_id); (origin_store_id, placed_at); (order_status, placed_at); (placed_at, order_id).

Placement requires at least one line, valid currency-aligned totals, and shipping snapshot if any shipping allocation is intended. Guest ecommerce requires at least one contact channel; store carryout can be anonymous. Header monetary values represent the original accepted sale and freeze at placement; line cancellation is accounted separately downstream, and returns do not reduce original sales totals. Discarded drafts remain draft or are removed through controlled unreferenced-draft cleanup; cancelled status is reserved for accepted orders. Do not invent placement solely to discard a draft.

## order_addresses

Grain: one order-time address snapshot for a billing or shipping role. Phase 1 supports at most one of each per order, with split packages all going to that shipping destination.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| order_address_id | bigint | No | PK |
| order_id | bigint | No | FK -> orders.order_id |
| address_role | varchar(10) | No | `billing`, `shipping` |
| source_customer_id | bigint | Yes | Registered owner of saved-address provenance |
| source_customer_address_id | bigint | Yes | Saved address used as provenance; optional even on registered orders |
| recipient_name | varchar(200) | No | Snapshot recipient |
| address_line1 | varchar(200) | No | Snapshot street |
| address_line2 | varchar(200) | Yes | Snapshot extra line |
| city | varchar(100) | No | Snapshot locality |
| region | varchar(100) | Yes | Country-aware requirement |
| postal_code | varchar(20) | Yes | Country-aware requirement |
| country_code | char(2) | No | Snapshot country |
| phone | varchar(25) | Yes | Snapshot contact |

Constraints: provenance fields are both null or both non-null. Composite FKs (order_id, source_customer_id) -> orders(order_id, customer_id) and (source_customer_address_id, source_customer_id) -> customer_addresses(customer_address_id, customer_id) enforce that a saved address belongs to the ordering customer. The ordinary order_id FK also enforces guest ownership when provenance is absent. Unique(order_id, address_role); unique(order_address_id, order_id, address_role) supports shipping-role enforcement from shipments.

Indexes: those unique keys cover order lookup; (source_customer_address_id, source_customer_id) for provenance; (order_id, source_customer_id) for its composite FK. Snapshots freeze at placement even if source address is edited/retired. An explicit authorized delivery-address amendment before handover changes the snapshot with audit/version evidence; no mutation after any shipment using it is handed over. Privacy erasure is a separately approved exception.

## order_items

Grain: one priced order line. The same SKU may occur more than once on an order at different prices/promotions; there is no unique(order_id, product_id).

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| order_item_id | bigint | No | PK |
| order_id | bigint | No | FK -> orders.order_id |
| line_number | integer | No | > 0; stable within order |
| product_id | bigint | No | FK -> products.product_id |
| sku_snapshot | varchar(50) | No | Order-time SKU |
| product_name_snapshot | varchar(200) | No | Order-time description |
| quantity_ordered | integer | No | > 0 |
| quantity_cancelled | integer | No | >= 0, <= quantity_ordered; default 0 |
| unit_price | numeric(18,2) | No | >= 0; accepted price in header currency |
| unit_cost_snapshot | numeric(18,2) | Yes | >= 0 when known, in header currency; unknown if no cost valuation available |
| gross_amount | numeric(18,2) | No | quantity_ordered * unit_price |
| discount_amount | numeric(18,2) | No | 0..gross_amount; all merchandise discounts allocated to lines |
| tax_rate_percent | numeric(5,2) | No | 0..100, combined effective line tax rate |
| tax_amount | numeric(18,2) | No | >= 0; rounded net merchandise tax |
| line_total | numeric(18,2) | No | gross_amount - discount_amount + tax_amount |
| line_status | varchar(25) | No | `open`, `partially_fulfilled`, `fulfilled`, `cancelled`, `closed` |
| requested_fulfillment | varchar(20) | No | `ship`, `pickup`, `carryout` |
| requested_pickup_store_id | bigint | Yes | FK -> stores.store_id; required exactly for pickup |

Row checks: tax_amount equals half-up rounding of (gross_amount - discount_amount) * tax_rate_percent / 100; cancelled state requires quantity_cancelled = quantity_ordered. Other states require quantity_cancelled < quantity_ordered. Header currency applies; product's current currency/price is not copied blindly. Single effective tax rate is an explicit simplification; compound tax jurisdiction detail is outside scope.

Indexes: unique(order_id, line_number); unique(order_item_id, order_id) for ownership FKs; (product_id, order_id); (requested_pickup_store_id) where not null. The line number is the retry key inside the idempotent order request.

Transactional checks: product snapshot matches SKU/name at acceptance; header totals equal sums of line values. Across noncancelled shipment allocations, allocated units + quantity_cancelled <= quantity_ordered. Fulfilled units come from handed-over/delivered shipment items, never line_status alone. Cancellations cannot cancel already handed-over units. At placement, freeze order_id, product_id, line_number, sku_snapshot, product_name_snapshot, quantity_ordered, unit_price, unit_cost_snapshot, gross_amount, discount_amount, tax_rate_percent, tax_amount, and line_total. The referenced orders.currency_code is immutable from placement, supplying the permanent currency context for every line; no duplicated line currency is needed. Later catalog, promotion, tax, or currency changes cannot rewrite these commercial snapshots. Cancellation and refund records account for subsequent changes separately. Fulfilled is reached when handed-over units equal quantity_ordered - quantity_cancelled.

## payments

Grain: one tender operation/attempt, not a mutable cumulative paid balance. Split tenders and retries create separate rows; retries of the same request reuse its key. Authorization, capture, refund, and void are separate operations linked to their predecessor.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| payment_id | bigint | No | PK |
| order_id | bigint | No | FK -> orders.order_id |
| payment_request_key | varchar(100) | No | Unique namespaced idempotency key |
| parent_payment_id | bigint | Yes | Prior operation; composite FK below |
| return_id | bigint | Yes | Optional FK to return authorization; permitted only when operation_type = refund; composite FK below |
| operation_type | varchar(15) | No | `authorization`, `capture`, `refund`, `void` |
| payment_method | varchar(20) | No | `card`, `cash`, `gift_card`, `wallet` |
| provider | varchar(50) | No | Gateway identifier or `internal_cash` |
| provider_transaction_id | varchar(100) | Yes | Provider result identifier; required for successful noncash operation |
| payment_status | varchar(15) | No | `pending`, `succeeded`, `failed` |
| amount | numeric(18,2) | No | > 0, including refund magnitude; direction is operation_type |
| currency_code | char(3) | No | Must equal order currency |
| failure_code | varchar(50) | Yes | Sanitized nonsecret code; required exactly for failed |
| attempted_at | timestamp with time zone | No | Business request instant |
| processed_at | timestamp with time zone | Yes | Required exactly for succeeded/failed; >= attempted_at |

Constraints: parent required for refund/void; forbidden for authorization; optional for capture (direct sale capture). Parent != self. return_id is nullable and must be null for authorization/capture/void; it is permitted only for refund. Merchandise-return refunds require the relevant RMA; cancellation or shipping-fee/service refunds unrelated to merchandise returns keep it null. Composite FK (parent_payment_id, order_id) -> payments(payment_id, order_id); (return_id, order_id) -> returns(return_id, order_id). Unique(payment_id, order_id) supports children. Indexes: unique(payment_request_key); partial unique(provider, provider_transaction_id, operation_type) where provider_transaction_id is not null; (order_id, attempted_at, payment_id); (parent_payment_id, order_id); (return_id, order_id); partial (attempted_at) where payment_status = pending.

Transactional validation: successful refund parent must be successful capture; void parent must be successful authorization; linked capture parent must be successful authorization. Same order, currency, method and provider across a chain. Direct cash captures/refunds are supported; cash authorization/void are forbidden by a row check. Refund never creates another authorization. Terminal operations are immutable; a failed retry is a new attempt with a new request key. Provider callback duplicates resolve to existing operations without doubling amounts. Provider adapters must supply an operation-unique transaction reference within provider and operation_type, using the original transaction plus a child-operation reference when needed; provider callbacks must not replace a distinct partial capture/refund with a reused reference.

Lock parent operation before checking totals: successful captures against an authorization plus successful voids cannot exceed authorized amount; successful refunds per capture cannot exceed captured amount. Pending children reserve capacity until resolved, so concurrently pending refunds/captures cannot overcommit. Successful net collection = captures - refunds; authorizations/voids/failed attempts do not count as revenue or cash collection. New order-level capture requests cannot exceed accepted payable amount less cancellations, accounting for outstanding captures and refunds; overpayments/chargebacks, offline cash reconciliation, and complex provider expiry states are outside scope. Returns link refunds but cannot change successful capture history.

## payment_allocations

Grain: one allocation of a capture/refund operation to an original order-line monetary component or header shipping component, additionally split by return item for merchandise-return refunds. This supporting table makes split tender, partial cancellation refunds and return refunds attributable instead of leaving only an unallocated order balance.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| payment_allocation_id | bigint | No | PK |
| payment_id | bigint | No | Parent operation |
| order_id | bigint | No | Ownership key for composite FKs |
| order_item_id | bigint | Yes | Original sale line for merchandise/tax; null for shipping components |
| return_item_id | bigint | Yes | Specific returned fulfillment allocation; required for RMA merchandise/tax refunds, otherwise null |
| return_id | bigint | Yes | Ownership key paired with return_item_id; must match parent payment RMA |
| allocation_type | varchar(20) | No | `merchandise`, `tax`, `shipping`, `shipping_tax` |
| amount | numeric(18,2) | No | > 0; magnitude; direction comes from payment operation |

FKs: (payment_id, order_id) -> payments(payment_id, order_id); (order_item_id, order_id) -> order_items(order_item_id, order_id); (return_item_id, return_id, order_item_id, order_id) -> return_items(return_item_id, return_id, order_item_id, order_id). Row checks: merchandise/tax requires order_item_id; shipping/shipping_tax requires it null. return_item_id and return_id are both present or both absent; when present, order_item_id is required and allocation_type must be merchandise/tax. Transactional validation requires these return references only for refund operations with a matching parent payments.return_id, and requires them for every merchandise/tax allocation on such a refund. Capture, cancellation refunds and header shipping refunds have no return-item references.

Indexes: partial unique(payment_id, order_item_id, allocation_type) where order_item_id is not null and return_item_id is null; partial unique(payment_id, return_item_id, allocation_type) where return_item_id is not null; partial unique(payment_id, allocation_type) where order_item_id is null; (payment_id, order_id); (order_item_id, order_id); (return_item_id, return_id, order_item_id, order_id); (order_id, payment_allocation_id). These retry keys allow separate allocations to multiple returned shipment portions of the same order line without duplicates.

Transactional rules: only capture/refund operations have allocations; their sums must equal payment.amount before submitting pending operations or recording terminal success. Authorization/void must have none. Zero components are omitted. Allocations freeze when the parent becomes succeeded/failed; pending adjustments cannot change a request already submitted to a provider without an explicit reconciliation command. New failed retries use new payment IDs with newly validated allocations.

Across pending/succeeded captures, allocated merchandise/tax cannot exceed the uncancelled original line component entitlement; header allocations cannot exceed original shipping components. A cancellation after capture explicitly lowers current payable and creates attributed refunds; do not retroactively invalidate previously valid captures or edit their allocation rows. Pending/succeeded refunds per parent capture/component/line cannot exceed that capture's allocation. Lock order and affected captures while checking limits.

Refunds with return_id must identify the exact return_item_id for each merchandise/tax allocation. Sum pending/succeeded allocations across all refund operations and captures per return item and component; never exceed that item's approved merchandise_refund_amount/tax_refund_amount. Lock the affected return items alongside order/capture rows. Rejected/cancelled RMAs confer no refundable entitlement. Header shipping allocations remain RMA-level and cannot exceed approved shipping components. These item-level checks supplement the original order-line and capture limits. Refunds without return_id require an audited cancellation or shipping-fee adjustment command; merchandise/tax amounts cannot exceed the original component allocated to cancelled units. All cancellation + return refunds for a line stay within original net merchandise/tax amounts, with unit eligibility and cent residuals reconciled to cancelled/returned quantities. Shipping adjustments and RMA shipping refunds share the original header-component cap. Provider refunds spanning several captures produce separate refund operations and allocations. This is allocation of operational money, not a finance/general-ledger model.
