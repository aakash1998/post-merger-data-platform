# Rocky Mountain mappings, differences and data quality

Mappings target **future canonical analytics**, not inserts into Rocky Mountain's operational PostgreSQL tables. Keep source_system = `scc` and original table/PK, with curated crosswalks for customer/item/location identities. No code, email, bigint or barcode is globally unique. The [approved Rocky Mountain model](../rocky-mountain-retail-group/README.md) remains unchanged.

## Domain mappings

| Stampede source | Rocky Mountain comparison | Proposed canonical mapping | Material difference / loss |
| --- | --- | --- | --- |
| customer_master.customer_id/code/name | customers.customer_id/customer_number/first_name/last_name | Source-qualified account key; optional stewarded customer/person crosswalk | Full name may be a company/household; splitting on a space is unsafe; duplicate code and WALKIN do not establish identity |
| customer_master address_text/city/province/postal_code/country | customer_addresses separate saved addresses | One parsed current-address observation when parseable | No collection/default roles/history before CDC; not an order-time address snapshot |
| customer_group, active_flag | loyalty_tier, lifecycle_status | Approved source-specific segment/status vocabulary | Do not invent gold/silver tiers or assume Y means marketing consent; no consent evidence |
| item_master.item_id/code/description/barcode | products.product_id/sku/product_name/barcode | Source-qualified item key plus optional SKU crosswalk | Generic/pack records, duplicate codes/barcodes, embedded variant text; no reliable enterprise SKU uniqueness |
| department_code/name | product_categories tree and products.category_id | Flat source department dimension, then stewarded category crosswalk | No parent hierarchy; repeated/conflicting names cannot imply a tree |
| selling_price, last_cost | list_price, standard_cost | Current source price and last-cost observation in validated CAD | Last receipt cost is not standard cost or historical sale cost; source has no line cost snapshot |
| unit_code, units_per_pack | unit_of_measure = each; integer quantities | Canonical quantity plus explicit source unit/conversion provenance | KG/CASE/fractional values cannot be silently rounded to each; unapproved conversion blocks unit-based consolidated metrics |
| locations | stores and warehouses, separate namespaces | Unified canonical location with approved store/depot role | One source namespace; STOCKROOM may belong to a shop, not an independent warehouse; unknown role unresolved |
| sales_orders ID/order_number/business_date | orders ID/unique order_number/placed_at | Source-qualified sale key; printed number separate; business_date retained | Printed number reused; DATE is not an instant; no accepted immutable totals/currency or full lifecycle |
| customer_id_ref/customer_code_ref | orders enforced customer_id FK | Resolve valid ID then cross-check code; record conflicts/unresolved guest/shared account | Raw IDs can be orphaned or disagree with code; do not choose an arbitrary duplicate code survivor |
| delivery_address_text/customer_name_text | immutable order_addresses and contact snapshots | Optional document-entered text with confidence/provenance | Mutable, incomplete and no billing/shipping roles; never reconstruct from today's master address as sale-time truth |
| sales_order_lines | order_items commercial snapshots | Source-qualified line, quantity/unit, reported amounts and source status | Mutable prices/quantity, negative credit lines, missing taxes and no per-unit cancellation accounting |
| payment_transactions | payments operation graph and payment_allocations | Signed posting fact with validated tender/type/status and linked sale where known | No authorization/capture distinction, immutable terminal evidence, line allocations or original-capture refund limits |
| stock_balance | inventory and stock_movements | Validated current/periodic reported stock snapshot by source item/location/unit | Negative/null/duplicate balances; no ledger, unavailable-stock figure, transaction-safe reservations or movement reconstruction |
| delivery_updates.json | shipments and shipment_items | Dispatch/consignment observation with scoped order matching | Missing exact line/quantity/handover history; cannot invent shipment-item records |
| returns_register.csv | returns and return_items | Return observation; link sale/refund only when evidence supports it | Missing original receipt/line/fulfillment and tax splits; approved credit differs from actual payment refund |
| stock_counts.csv | physical count evidence associated with stock movements | Independent count fact and discrepancy measure | Not a source stock ledger; comparing snapshots does not prove cause of movement |
| historical_sales.csv | historical orders/items | Archive-specific source line keys and original amounts | Coverage boundary required; lacks trusted historical payments and customer snapshots |
| supplier_catalog.csv, finance_adjustments.csv | No direct requested source-table equivalent | Advisory supplier enrichment; separately approved finance adjustment measures | Do not create new source technologies/tables or silently modify sales/cost/payment truth |

## Quality cases and intended handling

Source constraints preserve a modest structural floor, not fully clean business data. “Quarantine” below means later downstream handling; no pipeline is implemented here. Keep original values and reason codes even when a curated value is derived.

| Problem / realistic example | Can exist in typed MySQL model? | Downstream rule |
| --- | --- | --- |
| C001 and ` c001 ` represent possible duplicate accounts; email shared/malformed | Yes | Normalize lookup candidates; source IDs remain distinct; steward match and retain confidence |
| WALKIN holds thousands of unrelated anonymous purchases | Yes | Represent anonymous/shared-account classification; never one real person in customer counts |
| Blank name/email and province “Alta”, country “Canada” | Yes | Normalize approved vocabularies, retain raw; missing contact is not automatic invalid sale |
| Item code/barcode copied onto a retired and active record | Yes | Resolve effective, reviewed crosswalk; ambiguous code lookup cannot choose MAX(id) |
| item_id_ref points to no master or disagrees with item_code_ref | Yes; item reference has no FK | Flag orphan/conflict; permit an explicitly unknown-item sale view but block product-attributed measures |
| Line points to absent sales_order_id | No; enforced parent FK | Reject DB insert; file orphan fixture goes to quality review without disabling FK checks |
| Same order and line_number repeated | No; unique pair | Reject DB insert; duplicate historical CSV row remains file-quality fixture |
| Same printed order at two tills or repeated import with new PK | Yes | Use scoped candidates for review; transport replay dedup by CDC event does not remove a duplicate source sale |
| Header total 112.00 versus subtotal 100, tax 5, freight 0, discount 0 | Yes | Report reconciliation difference; do not silently replace header total with computed value |
| Header and line discounts both populated | Yes | Validate producer conventions; do not subtract both automatically; allocation is a curated decision |
| Old invoice price changed after payment; current master price different | Yes | Preserve CDC-observed versions; no claim of original price before baseline; do not backfill historical price from catalog |
| Negative credit line plus paper return plus negative refund posting | Yes/files | Separate merchandise reversal, physical return and cash movement; link overlap before deriving net-sales/return metrics |
| REFUND with positive amount, posted_flag unknown, duplicate processor ref | Yes | Validate type/sign/tender and posting certainty; quarantine cash measure on conflict; no fabricated capture parent |
| Refund/original receipt lacks order ID but only printed number | Yes | Scope by date/location/till when available; unresolved remains unallocated, not a guessed order match |
| stock on_hand = -3, allocated = 8, stale count date | Yes | Preserve reported values, flag stock/availability invalid; do not publish available-to-promise as trustworthy |
| Duplicate stock item/location pair, conflicting balance_as_of | Yes | Never sum duplicate snapshots; ambiguous survivor requires source correction/stewardship |
| 1 CASE with units_per_pack missing, 2.500 KG versus each | Yes | Preserve decimals/unit; conversions require approved factor and effective period; no rounding into integer source model |
| updated_at null/regresses or two edits share one second | Yes | Use actual CDC source order; flag audit quality, never incremental-filter on updated_at |
| Local 01:30 during DST fallback, missing timezone | Yes | Preserve wall-clock/date; unresolved instant flagged; a business date remains reportable with provenance |
| Zero date, numeric value “1,234.50” or impossible date string | Not valid typed DB fixture under strict mode; files can contain strings | Reject/flag file parsing with declared locale; do not model corrupt typed values by relaxing SQL mode |
| Different CSV encodings, repeated revised export, truncated file | Files only | Check manifest/count/checksum/revision; replacements only after completeness validation |

## Reconciliation priorities and authority

Validate line amounts against quantity/price only when unit and discount conventions are known; line net is nominally quantity * unit_price - line discount, tax separate. Header total nominally subtotal - header discount + tax + freight, but freight tax and header/line discount overlap can be unknown. These equations are diagnostics, not automatic correction rules. Thresholds/tolerances must be agreed; there is no blanket “close enough” amount accepted in this proposal.

Payment_transactions is the evidence for entered cash postings; sales_orders.paid_amount is a reconciliation cache. A posted marker alone is weaker than gateway/bank settlement evidence, which this source lacks. Separate reported posting totals from externally settled cash claims. Returns and finance adjustments supply different facts rather than overriding payments. Product-attributed revenue, converted unit metrics, trusted stock availability and historical cash reporting must expose coverage/quality gaps instead of passing unresolved rows as fully reconciled enterprise data.
