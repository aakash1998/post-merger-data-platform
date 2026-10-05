# Legacy CSV/JSON outside MySQL

These datasets remain file sources -> Amazon S3 under the existing architecture. They are **not** additional MySQL tables and are not captured by DMS. Proposed contract sketches define grain, ownership and quality needs; final file contracts, retention and delivery cadence still require agreement before ingestion.

## Shared delivery/replay requirements

For future controlled exports, each delivery needs an external manifest with dataset name, schema_version, batch_id, producer, extracted_at (UTC ISO timestamp), scope, coverage period/as_of, revision, supersedes_batch_id (nullable), expected row/object count, checksum and encoding. This is file provenance, not metadata claimed to exist in the old operational system. Keep raw file bytes, object path/version/checksum and row/object position downstream. No credentials or full card/bank details in manifests or payloads.

All six datasets below are **complete replacements for the declared scope**, not implicit delta streams. A corrected revision replaces an explicitly superseded batch only within that scope after count/checksum validation; missing rows in a partial/failed export do not imply deletes. A complete accepted replacement can withdraw previous observations in that scope. Overlapping scopes/revisions or unknown completeness are quarantined for reconciliation. A repeated checksum/batch is a transport replay, not additional business activity. File path/row number is ingestion identity, not stable identity across revisions; no universal legacy row key is invented.

Proposed CSV transport: UTF-8, comma delimiter, header required, RFC-style quoted fields/doubled embedded quotes; preserve embedded newlines with a real CSV parser. Controlled exports use `\N` for null and quoted empty string for empty text. Old received files may instead use CP1252, semicolons, blanks or mixed date/decimal formats; record the producer-specific schema/encoding revision and reject ambiguous parsing rather than guessing. String reference fields preserve leading zeros. Amount/quantity strings below retain the original format; approved parsers must convert to exact decimals, not binary floats.

JSON exports are UTF-8 objects with `schema_version`, `batch_id`, `scope`, `revision`, `extracted_at` and a named records array. Missing properties, explicit null and empty string remain distinguishable raw evidence. Payload metadata must match the manifest. Reject invalid JSON before row-level interpretation; unknown optional keys are retained as schema-evolution evidence, not silently discarded.

## historical_sales.csv

Owner: finance/POS archive. Proposed cadence: one-off month exports plus explicit corrected monthly revisions. Grain: one archived document line, including a line_sequence from the archive; whole calendar month and location-code scope. Proposed authority boundary: business_date before **2024-01-01** belongs to this archive, on/after that date to MySQL sales_orders/lines. This date is an assumption for approval, not a deployed filter. Validate actual coverage first; overlapping DB rows are retained for reconciliation and excluded from additive sales union until ownership is resolved.

| Field | File representation | Required | Meaning |
| --- | --- | --- | --- |
| branch_code | String | Yes | Legacy location code, not guaranteed unique master match |
| sale_date_text | String | Yes | Producer-specified calendar-date format |
| till_code | String | No | Register scope; absent lowers matching confidence |
| document_number | String | Yes | Printed order/invoice |
| line_sequence | Integer text | Yes | Positive original line number |
| customer_code | String | No | Raw account reference |
| item_code | String | No | Raw item reference |
| description | String | No | Historical sale text |
| quantity_text | Decimal string | No | Signed legacy quantity |
| unit_text | String | No | Legacy selling unit |
| net_line_amount_text | Decimal string | No | Merchandise after reported discount, before tax |
| tax_amount_text | Decimal string | No | Line tax if available |
| currency_text | String | No | Raw currency label |

Candidate record key is branch + parsed sale_date + till + document + line_sequence, but cannot be trusted without collision checks; duplicates/missing scopes are quarantined. No recreated customer snapshots or payment status is inferred. Header totals are not repeated as additive line amounts. Archive lacks authoritative historical receipt/refund postings; historical cash-collection analytics remain incomplete rather than treating sales as payment.

## returns_register.csv

Owner: customer-service paper/spreadsheet register. Proposed cadence: weekly complete return-day/location scopes with late corrected revisions. Grain: one returned item entry, not an electronic RMA with workflow. This file is authoritative for recorded physical returns and approved credit observations; actual monetary receipt/refund authority stays payment_transactions for the live DB period.

| Field | File representation | Required | Meaning |
| --- | --- | --- | --- |
| return_document_number | String | Yes | Local paper return number |
| return_line_number | Integer text | Yes | Entry within document |
| branch_code | String | Yes | Receiving branch |
| return_date_text | String | Yes | Producer-format return day |
| original_order_id | Unsigned integer text | No | Live MySQL sales_order_id if actually known |
| original_order_number | String | No | Often absent/ambiguous printed order reference |
| original_order_date_text | String | No | Original sale day for scoped matching |
| original_till_code | String | No | Original register scope |
| original_branch_code | String | No | Original selling location, may differ from receiving branch |
| original_line_number | Integer text | No | Original line sequence, not necessarily available |
| item_code | String | No | Returned item, sometimes handwritten |
| quantity_text | Decimal string | No | Reported returned quantity magnitude |
| unit_text | String | No | Unit of returned quantity |
| reason_text | String | No | Raw reason |
| disposition_text | String | No | Restock/damaged/dispose/blank; not stock movement proof |
| approved_credit_text | Decimal string | No | Approved amount; tax allocation often unknown |
| payment_transaction_id | Unsigned integer text | No | Actual linked DB refund when known |

Candidate key: branch + parsed return_date + return_document + return_line. No enforced file FKs; validate IDs against DB/source-scoped identity and compare code references. A missing receipt may remain an unmatched return observation. Negative sales lines, this register and refund postings can describe the same activity: do not sum all three as additional refunds/returns. An approved credit is not payment success. Without line/fulfillment provenance, original-price/per-unit overreturn checks may remain unresolved; do not manufacture Rocky Mountain-style return_items.

## delivery_updates.json

Owner: dispatch/carrier spreadsheet export. Proposed cadence: daily complete dispatch-day/branch scope with corrections; records array name `deliveries`. Grain: one consignment/tracking record, whose latest status may overwrite prior status within a revision. Authority: operational delivery evidence, not invoice or inventory-ledger truth.

| Property | JSON type | Required | Meaning |
| --- | --- | --- | --- |
| dispatch_reference | string | Yes | Local dispatch number |
| branch_code | string | Yes | Dispatch scope |
| dispatch_date_text | string | Yes | Producer-format business day |
| sales_order_id | integer or null | No | Live database order ID if known |
| order_number | string or null | No | Raw printed number |
| order_date_text | string or null | No | Original business date for matching |
| till_code | string or null | No | Original register scope |
| carrier_name | string or null | No | Raw carrier |
| tracking_number | string or null | No | May be reused/missing |
| status_text | string or null | No | SENT, OUT, DEL, FAILED and variants |
| status_time_text | string or null | No | Raw local/offset time; format/timezone declared by producer |
| item_codes | array of strings or null | No | Optional hints only, no reliable quantities/line allocation |

Candidate identity: branch + dispatch day + dispatch_reference; duplicate tracking alone is insufficient identity. One order may have several consignments, but this source has no trusted line-level shipment allocation, carrier-handover inventory event or complete event stream. Entire-scope replacement semantics above apply; a row's changing status is not an additive new shipment. Large integer IDs should be serialized/read without floating-point precision loss.

## stock_counts.csv

Owner: branch inventory team. Proposed cadence: monthly and ad-hoc count sessions; complete session/branch scope. Grain: one count-session/item observation. Independent physical evidence for reconciliation with stock_balance; **never sum counts into inventory or automatically turn differences into sale/transfer movements**.

| Field | File representation | Required | Meaning |
| --- | --- | --- | --- |
| count_session | String | Yes | Local physical-count session |
| branch_code | String | Yes | Count location |
| count_date_text | String | Yes | Business count day |
| item_code | String | Yes | Raw item code; resolve duplicates explicitly |
| counted_quantity_text | Decimal string | No | Physical quantity |
| unit_text | String | No | Count unit |
| reported_system_quantity_text | Decimal string | No | Optional system balance at count time, not necessarily current |
| counter_code | String | No | Operator code, not name/contact |

Candidate key: session + branch + item_code; duplicate shelf counts/units may represent subtotals, so no automatic dedup/sum without count-owner signoff. Missing rows mean no observation, not zero stock. Corrections replace the session revision.

## supplier_catalog.csv

Owner: merchandising's spreadsheet maintained from supplier price lists. Proposed cadence: monthly complete supplier/catalog-effective-date scope. Grain: one supplier item offer; multiple suppliers can map to the same local item. It remains a file because there is no supplier/purchasing module in the seven-table source.

| Field | File representation | Required | Meaning |
| --- | --- | --- | --- |
| supplier_code | String | Yes | Supplier business reference |
| supplier_item_code | String | Yes | Vendor offer code |
| local_item_code | String | No | Optional item_master matching hint |
| description | String | No | Supplier description |
| department_text | String | No | Supplier grouping, not enterprise category truth |
| unit_text | String | No | Offered unit |
| units_per_pack_text | Decimal string | No | Conversion hint requiring approval |
| cost_text | Decimal string | No | Vendor quoted cost |
| currency_text | String | No | Supplier quote currency; may differ from operational CAD |
| effective_date_text | String | Yes | Catalog-effective business date |

Candidate key: supplier + supplier_item + effective_date. Advisory enrichment only: do not overwrite item_master.last_cost or derive sales margin from a current offer. Pack factors cannot resolve weighted/generic merchandise automatically. Retain conflicting mappings for stewardship.

## finance_adjustments.csv

Owner: finance close spreadsheet. Proposed cadence: monthly complete accounting-period scope with explicit revisions. Grain: one finance adjustment line; **separate measures**, not another sale or payment table. Retain this because manual close adjustments do not originate in the retail application.

| Field | File representation | Required | Meaning |
| --- | --- | --- | --- |
| adjustment_reference | String | Yes | Spreadsheet adjustment ID |
| adjustment_line | Integer text | Yes | Positive line within adjustment |
| period_text | String | Yes | YYYY-MM accounting period |
| branch_code | String | No | Branch allocation, if known |
| account_code | String | Yes | Raw finance account label |
| order_number_ref | String | No | Optional unscoped invoice reference |
| adjustment_amount_text | Decimal string | Yes | Signed correction amount |
| currency_text | String | Yes | Must be resolved before consolidation |
| reason_code | String | No | Sanitized operational code |

Candidate key: period + adjustment_reference + line. A finance adjustment is not proof of actual refund, physical return or stock movement. Never mutate canonical orders/payments based solely on an unscoped invoice reference. Finance-adjusted reporting must expose a separate bridge/measure with provenance and explicit approval, not double count the amount in sales and cash facts.
