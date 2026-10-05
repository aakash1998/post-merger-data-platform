# Merger analytics business questions

KAN-23 defines the questions the completed platform should answer for Rocky Mountain Retail Group (RMRG) and Stampede City Commerce (SCC). These are proposed reporting requirements for Phase 1 review, not approved metric contracts or implemented models.

The mart names below describe likely business outputs from trusted Gold datasets, with analytical transformations and marts owned by dbt in Snowflake under the [existing architecture](architecture.md). They do not prescribe tables or duplicate transformations between platforms.

## Customers

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| How many identified customers buy from either company, and how much overlap exists? | Sizes the combined customer base and cross-selling opportunity without counting duplicate accounts as new customers. | Customer masters, orders/sales, approved customer crosswalks | Distinct purchasing enterprise parties in the period, split by person/organization/household; count buying from both companies; overlap / combined identified buyers; identity-resolution coverage | `mart_customer_overview` |
| Are customers returning, and which groups drive repeat sales? | Guides retention investment and highlights customer loss during integration. | Customer masters/segments, orders and lines, historical sales, customer crosswalks | Buyers with at least two distinct eligible orders / identified buyers in the period; cohort repeat-purchase rate within an agreed window; net merchandise sales per identified buyer | `mart_customer_overview` |

## Sales

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| How are combined sales changing by company, location and available channel? | Shows whether the acquired business and combined footprint are growing or weakening. | Orders/sales and lines, returns/credits, historical sales, locations, channel labels | Net merchandise sales, eligible order count, average order value (net merchandise sales / eligible orders), change versus the comparable prior period | `mart_sales_performance` |
| How much sales value is lost to discounts, cancellations and merchandise reversals? | Makes pricing leakage and avoidable lost demand visible. | Orders/lines, cancellation quantities, returns/credits, product and location classifications | Discount amount and discount / gross merchandise value; cancelled merchandise value; merchandise reversal value and reversal / eligible merchandise sales | `mart_sales_performance` |

## Products

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| Which products/categories sell best, and which assortments overlap or sell only at one company? | Supports assortment consolidation and practical cross-selling decisions. | Product/item masters, categories/departments, order lines, product/category crosswalks | Net merchandise sales and sales share by product/category; comparable sold quantities; count of approved products sold by both companies or only one in the period | `mart_product_performance` |
| Which products generate the most physical returns, and why? | Identifies quality, sizing or assortment problems before expanding them across the group. | Product crosswalks, sales/fulfillment lines, return items, SCC returns register | Received return quantities by reason; returned / fulfilled quantities for linked sale cohorts using comparable units; unmatched-return coverage | `mart_product_performance` |

## Inventory

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| Where do we have stock shortages or excess stock relative to demand? | Helps prioritize replenishment and review stock redistribution. | Inventory/stock balances, products and unit mappings, locations, sales history | On-hand and available quantities by product/location/unit; days of supply (validated available stock / average daily sold quantity over an agreed window); RMRG below-reorder and above-target counts | `mart_inventory_position` |
| How reliable are reported inventory balances? | Prevents purchasing and fulfillment decisions based on stale or inaccurate stock. | RMRG inventory/stock movements, SCC stock balances and stock-count files, product/location references | Counted minus reported quantity at the same count scope/time; discrepancy rate among comparable counts; stale, invalid and duplicate balance counts | `mart_inventory_position` |

## Finance

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| What merchandise margin can we support with trustworthy cost evidence? | Identifies profitable sales and the evidence needed before claiming combined profitability. | Sales lines, cancellations/returns, RMRG sale-time cost snapshots, product classifications | Merchandise gross profit (net merchandise sales minus attributable merchandise cost) and gross margin on cost-supported sales only; cost coverage as a share of eligible sales | `mart_finance_reconciliation` |
| Do sales, payment postings and close adjustments reconcile? | Exposes collection/refund exceptions and explains differences in management reporting. | Orders/lines/tax/shipping, RMRG payments and allocations, SCC payment transactions, returns, finance-adjustment files | Successful RMRG captures minus refunds; validated SCC signed posted receipts/refunds; linked order payable-versus-payment difference; unallocated postings; separately approved adjustment bridge by period/currency | `mart_finance_reconciliation` |

## Operations

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| Where are fulfillment delays and outstanding orders accumulating? | Helps protect service while the businesses integrate. | RMRG orders/shipments and line allocations, SCC orders and delivery-update files, locations | Open-order count and age; order-to-handover duration where timestamps exist; deliveries completed by promise date / delivered consignments with a known promise; delivery-status coverage | `mart_operations_service` |
| Are physical returns and refunds being resolved promptly? | Limits customer frustration and highlights refund backlogs. | RMRG returns/items/payments, SCC returns register and linked refund postings, locations | Open RMRG return count/age; approved entitlement less successful linked refunds; receipt-to-refund duration where supported; unresolved SCC return/refund links | `mart_operations_service` |

## Executive reporting

| Business question | Why leadership cares | Required source domains | Expected KPI or metric | Likely Gold/dbt mart |
| --- | --- | --- | --- | --- |
| Is the combined business improving against the pre-merger baseline? | Gives leadership a consistent view of integration progress and areas needing intervention. | Customer, sales, product, inventory, finance and operations outputs above; agreed merger date/baseline | Net sales growth, identified-buyer overlap/repeat rate, cost-supported margin, stock exceptions and service trends versus comparable pre-merger periods, split by company | `mart_merger_scorecard` |
| Which reported results are complete enough to trust? | Makes evidence gaps visible before leadership acts on consolidated numbers. | Source/ingestion audit metadata, reconciliation/quality results, crosswalk releases, file coverage and the marts above | Data as-of and freshness by domain/company; covered periods; unresolved customer/product attribution share; excluded/quarantined counts and monetary value where measurable; reconciliation exceptions | `mart_merger_scorecard` |

## Reporting assumptions and limits

- **Comparable scope:** report by company, business period and currency first. Do not add CAD and USD without an approved FX source/policy. Agree the business calendar, merger date, baseline, eligible sale statuses and common location/channel/category definitions; retain unknown labels where SCC evidence is missing. Prior-period and cohort metrics require complete comparable history.
- **Sales versus cash:** proposed net merchandise sales means merchandise after discounts, less attributable cancellations and merchandise credits/reversals, excluding tax and shipping. Agree recognition timing and reversal authority before modeling. Do not count the same SCC negative line, return credit and refund three times; physical returns, cash refunds and finance adjustments are separate measures. Validate SCC header/line discount overlap. Count each eligible commercial order once even when it has multiple lines, tenders or consignments.
- **Identity and units:** use approved, effective customer/product assignments from a recorded mapping release. Guests and WALKIN accounts are anonymous sales, not identified people. Unresolved facts retain source-level totals but remain unattributed in entity metrics, with coverage shown. Compare quantities only within compatible units or approved dated conversions; converting packages never multiplies revenue.
- **Finance evidence:** SCC current `last_cost` and supplier quotes cannot establish historical margin. Missing RMRG costs remain unknown; return/cancellation cost treatment needs finance agreement. SCC postings are reported cashbook evidence, not confirmed bank settlement. These sources cannot support complete combined profit, EBITDA, bank reconciliation or proven merger cost savings without further agreed inputs.
- **Operational evidence:** RMRG availability subtracts reserved and unavailable stock. SCC lacks unavailable stock and a ledger; label its on-hand-minus-allocated measure as reported availability after validation. Do not infer transfers or sum duplicate snapshots. Promise-date service and precise duration metrics may be RMRG-only; SCC date/status files cannot establish missing promises, event history or line fulfillment. Publish supported subsets and coverage, not invented values.
- **Reproducibility:** retain source identity, business date/time, ingestion/file provenance, report as-of and mapping release. Replays and replacement file revisions must not add activity; approved corrections/restatements must be distinguishable from new business. The SCC archive/database boundary and file authority rules remain proposals requiring agreement.

## Source documentation

- [Business problem](problem-statement.md) and [architecture decisions](decisions.md).
- [RMRG source model](source-data-model/rocky-mountain-retail-group/README.md), including sales/payment, inventory and fulfillment/return contracts.
- [SCC source model](source-data-model/stampede-city-commerce/README.md), [legacy file proposals](source-data-model/stampede-city-commerce/legacy-files.md) and [quality/authority limits](source-data-model/stampede-city-commerce/mappings-and-quality.md).
- [Cross-company identity strategy](source-data-model/cross-company-mappings/README.md) and [history/report attribution rules](source-data-model/cross-company-mappings/stewardship-and-history.md).
