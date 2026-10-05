# Source Simulator

KAN-24 implements reproducible **relational seed snapshots** for Rocky Mountain Retail Group (17 PostgreSQL tables) and Stampede City Commerce (seven MySQL tables). It follows the approved [Rocky Mountain dictionary](../docs/source-data-model/rocky-mountain-retail-group/README.md), [Stampede dictionary](../docs/source-data-model/stampede-city-commerce/README.md), and [matching strategy](../docs/source-data-model/cross-company-mappings/README.md). The user-approved contracts govern implementation despite their historical “proposed” headings.

KAN-25 extends these models with [continuous database changes](docs/continuous-changes.md): a rate-controlled local source state, durable transaction journal, business lifecycle commands, and a PostgreSQL/MySQL transaction writer for later database integration. The seed CLI and immutable seed output remain available separately.

## Run locally

Python 3.11+ with IANA timezone data is required. Runtime and tests use the standard library; no Faker, database, credentials, or cloud access is needed. From the repository root:

```sh
PMDP_ENV=dev PYTHONPATH=source-simulator/src python3 -m retail_simulator \
  --config source-simulator/config/small.json \
  --output source-simulator/generated/dev/seed-24

PYTHONPATH=source-simulator/src python3 -m unittest discover -s source-simulator/tests -v
```

`PMDP_ENV` must explicitly be `dev` or `test`, following the [environment conventions](../docs/environment-naming-conventions.md). Synthetic generation rejects `prod`. `--output` is a local artifact destination, not a resource name or deployment target. Workload profiles contain no connection information. An optional installation with `pip install -e ./source-simulator` exposes the same CLI as `pmdp-seed`; installation needs setuptools, but the commands above do not install dependencies.

Omit `--config` to generate 500/120 customers, 100/40 products, and 2,000/500 orders for Rocky Mountain/Stampede respectively. `config/small.json` is a smaller complete example. Copy it and adjust fields below for larger runs. Unknown fields, invalid counts/fractions, and invalid date windows fail before publishing.

| Configuration | Default | Meaning |
| --- | --- | --- |
| `seed` | 24 | Local deterministic PRNG; does not modify global randomness |
| `start_date`, `days` | 2025-01-01, 365 | Business-order window; minimum start 2024-01-01, maximum 3,650 days, consistent with the documented SCC archive boundary |
| `rmrg_customers`, `scc_customers` | 500, 120 | Master counts; minimum 12 each to retain matching fixtures |
| `rmrg_products`, `scc_products` | 100, 40 | Master counts; minimum 12 each |
| `rmrg_orders`, `scc_orders` | 2,000, 500 | Exact commercial-document counts; zero permits a master-only seed |
| `rmrg_stores`, `rmrg_warehouses`, `scc_locations` | 4, 2, 3 | Facility counts; SCC locations respect SMALLINT UNSIGNED limits |
| `overlap_fraction` | 0.45 | True overlapping share of regular SCC masters, excluding five reserved edge-case records; capped by available RMRG masters; duplicate-account scenario adds another labelled link |
| `guest_fraction` | 0.18 | RMRG null-customer orders / SCC shared WALKIN usage probability |
| `return_fraction` | 0.10 | Return probability for fulfilled RMRG orders |
| `open_fraction`, `cancel_fraction` | 0.08, 0.04 | Probabilities for RMRG processing/cancelled orders; remaining orders fulfilled |
| `messy_fraction` | 0.15 | Probability of SCC invoice/posting inconsistencies and duplicate/invalid stock snapshots; labelled master edge cases are always present |
| `initial_stock` | 80 | Base units per RMRG product/facility; opening adds 0–40 units; historical receipts replenish shortages |
| `max_lines` | 5 | Order-line ceiling, 1–100; weighted basket distribution tops out at five |

Fractions are probabilities, not quotas. Small or zero-order profiles need not contain every transactional scenario. All profiles retain master matching edge cases. Product/facility stock is dense: memory and file size increase with their Cartesian product, so choose facility/catalog counts deliberately.

## Output and replay

One `rmrg/<table>.jsonl` and `scc/<table>.jsonl` file is written per approved table, including empty fact files for zero-order configurations. Each record has **exactly** that table's domain and audit columns; nullable absent values are explicit JSON null. No enterprise keys, scenario labels, ingestion metadata, or CDC envelopes are added to source rows.

- Monetary and fractional quantities are exact decimal **strings** with their source scale; a future loader must parse them as Decimal/SQL DECIMAL, never float. IDs and whole-unit RMRG quantities are JSON integers; consumers must preserve bigint precision.
- RMRG instants carry `+00:00`. SCC DATETIME values are timezone-free second-precision wall clocks, normally America/Edmonton; DATE values remain dates. Null, blank, missing evidence, and unreliable SCC audit values are preserved.
- `manifest.json` contains the full workload config, generator/column-contract version fingerprint, source-instance names, snapshot timestamp, row counts, SHA-256 checksums, load order, all-table CDC scope, validation summary, and scenario counts. These are **seed export** metadata, not DMS commit/ingestion metadata or SCC legacy-file manifests.
- `matching_truth.jsonl` contains source-qualified PK pairs, constructed same-entity labels (true/false/null), scenario names, and provenance. It is test evidence only: it neither approves a match nor assigns enterprise keys. Do not feed it into matching inputs or measure predictions against unlabelled pairs as though they were all negatives.

The same config, environment, generator version, and Python runtime produce the same bytes. Reusing a completed output verifies its fingerprint, checksums, file inventory, and counts and returns it unchanged. A changed config, incomplete output, or altered file is rejected; choose a new output directory. There is no overwrite flag. Export uses a temporary sibling directory and publishes by atomic rename only after all validations pass. Failed runs discard staging and can restart from the seed; there is no mid-run checkpoint. JSON logs contain progress/counts and artifact metadata, not customer rows.

Orders stream one transaction at a time. Generation retains masters, source-key indexes, O(days) daily counts, final inventory balances/ledger totals, and the current basket. Memory does not grow with order history. Computation/output scale with order count; inventory state scales with products × locations. The exported ledger represents historical seed facts, not a running mutation service.

## Business assumptions and coverage

This seed is a fictional Alberta/CAD assortment and facility footprint, not a forecast or tax engine. Contact domains use `example.invalid`; phone numbers use fictional 555 values. GTIN-like strings are synthetic and checksum-valid where intended, **not** evidence of real GS1 ownership. Approved USD support is retained in the schema but not exercised by this initial CAD workload; no FX is invented.

RMRG has hierarchical categories, structured addresses/variant attributes, registered/guest and anonymized customers, and store/web/mobile/call-center ordering. Weighted baskets mostly contain one or two lines and single units; promotions affect about 20% of lines. The top 20% of customers/products receive approximately 65% of selection draws, and November/December and weekends have heavier order demand. Orders use a fixed illustrative 5% effective tax and a CAD 7.95 shipping fee below CAD 100. Counts/probabilities are configurable; these distribution shapes are explicit workload assumptions.

RMRG seed coverage includes mixed ship/pickup orders, warehouse and ship-from-store origins, carryout, outstanding reservations, cancelled accepted orders, failed authorization retries, successful card authorization/capture or direct cash capture, component allocations, and original-price partial-unit returns with settled refunds. Returned goods enter quarantine and are restocked or disposed through linked ledger legs. Inventory starts at zero, receives opening stock, and is reconciled to all posted deltas. Audit columns represent controlled snapshot import/posting, while business timestamps describe prior activity. The generator uses one tender per accepted order, one consignment per fulfillment mode, and one return authorization/returned unit per selected sale; split tenders, same-line split consignments, transfer/reversal histories, unresolved inspections, and every lifecycle state are not claimed as current scenario coverage.

SCC stays smaller and denormalized: one raw customer address, flat item departments, unified locations, loose customer/item references, local weak audits, and cashbook payments. It preserves duplicate account/code/barcode evidence, malformed contacts, CASE/KG units and missing pack factors, negative credits/stock, null/duplicate balances, stale/regressing timestamps, reused printed/receipt numbers, orphan **logical** references, unallocated postings, duplicate imports, invoice-total differences, and conflicting refund sign/status evidence. Enforced parent-order and item/location FKs remain intact; malformed numeric/date strings and zero dates never enter typed database fixtures. SCC stock snapshots are reported observations, not a fabricated movement ledger tied to sales.

Matching labels cover exact contact/name overlap, abbreviated names/address evidence, duplicate accounts, shared-contact false positives, organization/WALKIN/anonymized exclusions, exact GTIN+each overlap, distinct CASE packages, KG incompatibility, reused-code/barcode conflicts, generic/invalid products, and unmatched source identities. RMRG source keys/SKUs never replace SCC keys/codes.

## Contracts, validation, and later work

`src/retail_simulator/schema.json` copies all approved column names, SQL types, and nullability, including five RMRG and three SCC audit columns on every table. Tests compare it directly with the Markdown dictionaries, preventing silent schema drift. Generation validates column sets, type ranges/scales, vocabularies, nullability, PK progression, enforced/composite FKs, per-transaction unique keys, line/header monetary equations, payment/refund capacities and provenance, fulfillment/return quantities and location ownership, and final stock-ledger totals before publishing. Full-snapshot tests additionally verify uniqueness and cross-order ownership and intentionally corrupt meaningful relationships. This validates generated scenarios; it is not a database constraint engine or proof of every possible future transition.

No database is connected or loaded. A later loader must use the manifest load order, import explicit seed IDs under controlled migration rules, advance identity sequences/auto-increment counters, and load each snapshot atomically into an empty/approved target. Final inventory is already a snapshot: inserting the historical ledger must **not** apply its deltas a second time. Relational JSONL export is a seed artifact, not a new operational source or replacement for DMS.

Continuous database mutations are KAN-25; Kafka events are KAN-26. SCC `historical_sales.csv`, `returns_register.csv`, `delivery_updates.json`, `stock_counts.csv`, `supplier_catalog.csv`, and `finance_adjustments.csv` remain the [approved legacy-file datasets](../docs/source-data-model/stampede-city-commerce/legacy-files.md); they are not invented MySQL tables and are not generated by this relational ticket. Cloud provisioning, DDL, ingestion, matching algorithms, and architecture/schema redesign remain outside scope. The existing architecture/decisions need no changes; only this component's prior placeholder needed implementation/run instructions.
