# Seven-table MySQL dictionary

Each table includes the [three shared audit columns](conventions.md). All tables participate in full-load + I/U/D CDC. Columns marked as logical references are intentionally not enforced FKs. The dictionary describes a proposed source shape, not executable DDL.

## customer_master

Grain: one account/card record. Household, trade-account and duplicate-person records coexist; anonymous sales often use a shared walk-in code.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| customer_id | INT UNSIGNED | No | PK; positive, immutable auto-increment |
| customer_code | VARCHAR(20) | No | Raw account code; nonunique, may be blank or reused on a different record |
| customer_name | VARCHAR(160) | Yes | One unparsed person/business/household name |
| customer_type | VARCHAR(20) | Yes | Observed labels include RETAIL, TRADE, WALKIN; no vocabulary CHECK |
| email_address | VARCHAR(150) | Yes | Raw email, possibly obsolete/malformed/shared |
| phone_number | VARCHAR(40) | Yes | Raw phone including extensions/free formatting |
| address_text | VARCHAR(300) | Yes | One mutable street/unit field; may contain line breaks |
| city | VARCHAR(80) | Yes | Free text |
| province | VARCHAR(40) | Yes | AB, Alberta, Alta and blanks possible |
| postal_code | VARCHAR(20) | Yes | Raw postal/ZIP |
| country | VARCHAR(40) | Yes | CA, Canada, CAN and blanks possible |
| customer_group | VARCHAR(30) | Yes | Free-text segmentation, not standardized loyalty tiers |
| credit_limit | DECIMAL(12,2) | Yes | Trade credit limit, CAD; negative values are exceptions, not accepted business policy |
| active_flag | VARCHAR(5) | Yes | Y/N, 1/0, yes/no, blank/unknown |

FKs: none. Constraints: non-null unsigned PK/unique identity and declared nullability only; no uniqueness on code/contact/name. Indexes: (customer_code) with binary collation; (email_address); (active_flag, customer_id). Neither email lookup nor a WALKIN card is a real-person identity match. Current address changes overwrite previous source values; there is no saved-address collection or historical order-address provenance.

## item_master

Grain: one legacy item record. Some records represent packs or generic merchandise rather than distinct modern SKU variants.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| item_id | INT UNSIGNED | No | PK; positive, immutable auto-increment |
| item_code | VARCHAR(30) | No | Raw code, not unique across duplicate/retired records |
| item_description | VARCHAR(180) | Yes | Abbreviated description; variant details often embedded |
| department_code | VARCHAR(20) | Yes | Flat reporting group, not an FK/category hierarchy |
| department_name | VARCHAR(80) | Yes | Repeated free-text label, may disagree for same code |
| brand_name | VARCHAR(60) | Yes | Raw brand |
| barcode | VARCHAR(40) | Yes | String preserving zeros; reused/missing/duplicate possible |
| unit_code | VARCHAR(12) | Yes | EA, EACH, KG, CASE etc.; no assumed conversion |
| units_per_pack | DECIMAL(10,3) | Yes | Reported conversion hint, not trusted; missing/zero/negative possible |
| selling_price | DECIMAL(12,2) | Yes | Current CAD price; zero/negative exceptions retained |
| last_cost | DECIMAL(12,2) | Yes | Last received cost, not standard valuation |
| active_flag | VARCHAR(5) | Yes | Legacy active marker |

FKs: none. Constraints: non-null unsigned PK/unique identity and nullability only; no nonnegative-price or unique barcode/code CHECK. Indexes: (item_code) with binary collation; (barcode); (department_code, active_flag). No product-category table, variant/style grouping, separate price book or product activation workflow.

## locations

Grain: one store, depot or back-room location in a single reference table.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| location_id | SMALLINT UNSIGNED | No | PK; positive, immutable auto-increment |
| location_code | VARCHAR(12) | No | Raw branch/depot code; nonunique aliases/retired duplicates possible |
| location_name | VARCHAR(100) | Yes | Display label |
| location_type | VARCHAR(20) | Yes | SHOP, STORE, DEPOT, STOCKROOM, unknown; no CHECK |
| address_text | VARCHAR(250) | Yes | Single address field |
| city | VARCHAR(80) | Yes | Locality |
| province | VARCHAR(40) | Yes | Raw province |
| postal_code | VARCHAR(20) | Yes | Raw code |
| country | VARCHAR(40) | Yes | Raw country |
| timezone_name | VARCHAR(64) | Yes | Reported zone; absent normally uses documented Alberta assumption with a quality flag |
| active_flag | VARCHAR(5) | Yes | Current operating marker |
| closed_on | DATE | Yes | Reported closure date, may conflict with active_flag |

FKs: none. Constraints: non-null unsigned PK/unique identity and nullability; no capabilities or lifecycle transition checks. Indexes: (location_code) with binary collation; (location_type, active_flag). No separate warehouse identities, pickup/ship-from-store capabilities or facility-opening lifecycle.

## sales_orders

Grain: one sales/invoice document from POS or back-office order entry; same printed order number can appear at different tills, dates and locations.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| sales_order_id | BIGINT UNSIGNED | No | PK; positive, immutable auto-increment |
| order_number | VARCHAR(30) | No | Raw printed document number; not unique |
| business_date | DATE | No | Business posting day; no fabricated transaction instant |
| entered_at | DATETIME | Yes | Local order-entry instant |
| location_id | SMALLINT UNSIGNED | Yes | Enforced FK -> locations.location_id; absent for unknown/imported origin |
| till_code | VARCHAR(12) | Yes | Raw register/operator batch scope |
| customer_id_ref | INT UNSIGNED | Yes | Logical reference to customer_master.customer_id; deliberately no FK |
| customer_code_ref | VARCHAR(20) | Yes | Raw printed account code; may contradict ID or be a shared WALKIN code |
| customer_name_text | VARCHAR(160) | Yes | Entered document name, not a guaranteed immutable snapshot |
| delivery_address_text | VARCHAR(300) | Yes | Optional one-field destination; often absent on carryout |
| sales_channel | VARCHAR(20) | Yes | POS, PHONE, WEB, unknown/blank; no CHECK |
| order_status | VARCHAR(20) | Yes | OPEN, PAID, SENT, VOID, CLOSED and variants; no transition checks |
| currency_text | VARCHAR(8) | Yes | CAD, C$, $, blank; operational assumption CAD, validate before canonical mapping |
| subtotal_amount | DECIMAL(14,2) | Yes | Reported merchandise subtotal; convention before discount/tax |
| discount_amount | DECIMAL(14,2) | Yes | Header discount, not reliably allocated to lines |
| tax_amount | DECIMAL(14,2) | Yes | Header tax; no tax-jurisdiction breakdown |
| freight_amount | DECIMAL(14,2) | Yes | Freight charge, reported tax treatment may be ambiguous |
| total_amount | DECIMAL(14,2) | Yes | Reported accepted invoice total; can disagree with components/lines |
| paid_amount | DECIMAL(14,2) | Yes | Mutable cached payment total, not authoritative receipt facts |

FKs: location_id only. Constraints: non-null unsigned PK/unique identity and declared nullability. No unique order number, total equation, customer FK, enforced status or snapshot freeze. Indexes: (location_id, business_date, order_number); (business_date, sales_order_id); (order_number); (customer_id_ref); (customer_code_ref) with binary collation; (order_status, business_date). Proposed legacy reconciliation candidate is location + business_date + till_code + order_number, but null/missing scopes and duplicates prevent treating it as a guaranteed key.

## sales_order_lines

Grain: one entered line within a sales document. Quantity/price/description can be corrected in place, even after payment; no cancellation allocation or shipment bridge.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| sales_order_line_id | BIGINT UNSIGNED | No | PK; positive, immutable auto-increment |
| sales_order_id | BIGINT UNSIGNED | No | Enforced FK -> sales_orders.sales_order_id |
| line_number | SMALLINT UNSIGNED | No | Positive entry sequence; unique within order |
| item_id_ref | INT UNSIGNED | Yes | Logical reference to item_master.item_id; no FK |
| item_code_ref | VARCHAR(30) | Yes | Raw entered/printed code, may conflict with item ID |
| description_text | VARCHAR(180) | Yes | Entered sale text; generic/custom-item lines allowed |
| unit_code | VARCHAR(12) | Yes | Line selling unit, may disagree with master |
| quantity | DECIMAL(12,3) | Yes | Signed; negative legacy credit lines exist, zero is a quality exception |
| unit_price | DECIMAL(12,2) | Yes | Reported price; not necessarily current catalog price |
| discount_amount | DECIMAL(14,2) | Yes | Optional entered line discount; header discount can overlap |
| tax_amount | DECIMAL(14,2) | Yes | Optional entered line tax, often omitted |
| line_amount | DECIMAL(14,2) | Yes | Reported net merchandise amount before tax; import convention can disagree |
| line_status | VARCHAR(12) | Yes | Entered status; may be blank or differ from header |

Constraints: PK; enforced parent FK; unique(sales_order_id, line_number); line_number > 0. There is no item FK or quantity/price/amount equation CHECK. A repeated line number under one order is rejected by this model; malformed historical file duplicates are quarantined, not inserted by disabling constraints. Indexes: unique order/line key supplies order FK lookup; (item_id_ref); (item_code_ref) with binary collation. Two different line numbers may still be duplicate business entries. No source line currency column; header's raw currency context applies and can itself be corrected.

## payment_transactions

Grain: one receipt/refund posting in a legacy cashbook/POS import, not a payment authorization or gateway-operation lifecycle. Multiple tenders and duplicate imports are possible.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| payment_transaction_id | BIGINT UNSIGNED | No | PK; positive, immutable auto-increment |
| sales_order_id | BIGINT UNSIGNED | Yes | Enforced FK -> sales_orders.sales_order_id when known |
| order_number_ref | VARCHAR(30) | Yes | Unscoped printed number; may be ambiguous or disagree with linked order |
| location_id | SMALLINT UNSIGNED | Yes | Enforced FK -> locations.location_id; may differ from order location |
| receipt_number | VARCHAR(30) | Yes | Nonunique till receipt number |
| transaction_date | DATE | No | Posting day |
| transaction_time | DATETIME | Yes | Optional local transaction instant |
| transaction_type | VARCHAR(15) | Yes | PAYMENT, REFUND, REVERSAL and raw variants |
| tender_code | VARCHAR(20) | Yes | CASH, CRD, VISA, MC, CHQ, etc. |
| amount | DECIMAL(14,2) | No | Signed posting; normally payment positive, refund negative |
| currency_text | VARCHAR(8) | Yes | Raw currency label; same CAD assumption as orders |
| reference_text | VARCHAR(80) | Yes | Nonsecret processor/cheque reference; nonunique/missing possible |
| posted_flag | VARCHAR(5) | Yes | Y/N, 1/0, unknown; not a settlement guarantee |
| reversal_of_id_ref | BIGINT UNSIGNED | Yes | Logical prior posting reference; deliberately no self FK |

Constraints: non-null unsigned PK/unique identity, declared FKs/nullability only. No sign/type CHECK, parent-capture graph, idempotency key, provider uniqueness or refundable-balance constraint. Indexes: (sales_order_id, transaction_date); (location_id, transaction_date); (receipt_number); (order_number_ref); (reference_text); (reversal_of_id_ref). An orderless payment is allowed; a non-null enforced order FK cannot point to a missing order. A raw order number can be unresolved. Do not infer success from an order's paid_amount or status alone. Corrections may update posting fields in place; CDC preserves changes, but the source does not guarantee historical immutability.

## stock_balance

Grain: one reported balance record for an item/location. Intended business grain is one pair, but stale duplicate records can exist after branch imports; each gets a distinct source key.

| Column | MySQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| stock_balance_id | BIGINT UNSIGNED | No | PK; positive, immutable auto-increment |
| item_id | INT UNSIGNED | No | Enforced FK -> item_master.item_id |
| location_id | SMALLINT UNSIGNED | No | Enforced FK -> locations.location_id |
| quantity_on_hand | DECIMAL(12,3) | Yes | Reported signed stock; negative/null possible |
| quantity_on_order | DECIMAL(12,3) | Yes | Expected supplier quantity, no purchase-order lineage |
| quantity_allocated | DECIMAL(12,3) | Yes | Legacy held-stock figure; can exceed on_hand or be stale |
| unit_code | VARCHAR(12) | Yes | Balance unit; may contradict item master |
| reorder_level | DECIMAL(12,3) | Yes | Manual threshold, zero/negative/missing possible |
| last_count_date | DATE | Yes | Last reported physical count day |
| balance_as_of | DATETIME | Yes | Reported local effective instant, not capture/commit time |

Constraints: PK and item/location FKs only; no unique(item_id, location_id), nonnegative-stock CHECK or reservation equation. Indexes: (item_id, location_id); (location_id, item_id); (balance_as_of). FKs guarantee referenced master records exist, not that codes, units or balances are correct. Duplicate pair balances must not be summed or automatically selected by unreliable updated_at; require an approved survivor/correction decision. Physical-count CSV provides independent evidence, not a movement ledger. No reconstructable source stock ledger, atomic reservation allocation or stock-transfer history is claimed.
