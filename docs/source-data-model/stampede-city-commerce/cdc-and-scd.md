# CDC scope and downstream SCD candidates

## Proposed database capture allowlist

All seven tables need a consistent initial baseline and ongoing inserts, updates and physical deletes. Capture raw inactive/void/negative/duplicate records too; filtering only “good” current rows would hide source changes and reconciliation gaps.

| Source table | Capture | Identity / purpose |
| --- | --- | --- |
| scc.customer_master | Full load + I/U/D | customer_id; account/contact/address changes and retirement |
| scc.item_master | Full load + I/U/D | item_id; flat catalog/department/unit/price changes |
| scc.sales_orders | Full load + I/U/D | sales_order_id; mutable invoice state/amounts/customer references |
| scc.sales_order_lines | Full load + I/U/D | sales_order_line_id; original entered lines and in-place corrections |
| scc.payment_transactions | Full load + I/U/D | payment_transaction_id; posting/refund corrections and duplicate imports |
| scc.locations | Full load + I/U/D | location_id; aliases, type, status, geography |
| scc.stock_balance | Full load + I/U/D | stock_balance_id; reported balances and stale duplicate corrections |

File datasets in [legacy-files.md](legacy-files.md) use independent batch/revision contracts and do not participate in database CDC. Canonical source keys include source_system = `scc`, database, table and PK; legacy files have their own dataset/batch/record identity and authority scope. Never deduplicate different source PKs merely because printed numbers or normalized customer/item codes agree.

## Later DMS prerequisites and capture semantics

Keep MySQL on Aiven -> AWS DMS -> S3, with Kafka reserved for events. AWS documents MySQL source binary-log requirements including ROW format and FULL row image in its [DMS MySQL source guide](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Source.MySQL.html). Before implementation, verify supported Aiven/MySQL/DMS versions, InnoDB, binlog enablement/retention, permissions, source durability settings and endpoint/task options. No settings are changed in this task.

- Agree and test baseline-to-CDC boundary, source event ordering/transaction identity and delete payloads against actual emitted DMS S3 output. A FULL source binlog setting does not itself define the S3 envelope or guarantee exposed before-images.
- Source updated_at is nullable/unreliable and local; it is neither a CDC cursor nor SCD effective time. Preserve source audit values beside separate source commit/order, operation, schema-version and ingestion/object provenance metadata. IDs/ingestion arrival time do not imply global commit order.
- Apply replay deterministically by keyed change order from the agreed DMS contract; preserve raw changes. The same source PK can be updated several times with identical audit times; do not collapse those distinct changes using `(PK, updated_at)`.
- No row_version exists. For current-state convergence, source sequence governs stale update/delete handling. Avoid delete-resurrection on out-of-order replay; use an agreed delete/version watermark. Keyed deletion must work even when no full old row appears in the landed payload.
- Enforced source parents/children can land out of order. Resolve/wait/reconcile later. Logical customer/item references may **remain** missing forever, and should not be retried endlessly as if the source guaranteed a parent.
- Reference retirements use raw active/status fields, not a consistent deleted flag. Controlled physical deletions emit D events. RESTRICT prevents cascading loss of enforced order/stock/payment history; loose references can become orphaned after master deletion, which downstream must flag.
- Changes can be late/backdated at the business layer. DATE/local DATETIME need conversion provenance; source commit chronology remains separate. Cross-table import batches are not guaranteed atomic. Use reconciliation windows rather than claiming every landed transaction produces immediately balanced orders/stock.
- Schema evolution is reviewed: additive nullable columns first where appropriate; change raw vocabularies without losing unknown values; coordinate renames/drops/numeric precision/key changes with consumers before deployment. No primary-key mutation, TRUNCATE-as-delete strategy or reset/reseed of IDs is included.
- Retain full numeric precision and unsigned IDs; avoid JSON/JavaScript float conversion for bigint keys. Missing prior history cannot be reconstructed from today's masters or a new CDC baseline.

## Proposed analytical history rules

SCD Type 1/2 belongs in downstream analytical dimensions. Operational source tables receive no valid_from/valid_to/is_current or warehouse surrogate-key columns. Proposals are subject to agreement on correction-versus-real-change classification and privacy retention.

| Source table | Type 1 candidates | Type 2 candidates | Fact/limitation treatment |
| --- | --- | --- | --- |
| customer_master | customer_name spelling correction, email_address/phone_number current-contact corrections; formatting fixes in address fields | Genuine moves (address_text/city/province/postal_code/country), customer_group, customer_type, active_flag, credit_limit | Identity stays source-qualified; duplicate-person merges need crosswalk history; no assumed consent/loyalty equivalence |
| item_master | Description/barcode/brand typo correction; department-name spelling | Substantive department_code/name reclassification, brand, unit_code/units_per_pack, selling_price, last_cost, active_flag | No sales cost snapshot; historical margin may be unknown; master unit change does not reinterpret old quantity automatically |
| locations | Name/address/timezone typo corrections | Genuine relocation, location_type, timezone_name, active_flag and closure status | closed_on is a reported business date, not necessarily dimension effective time; unresolved stockroom/store roles retained |
| sales_orders | Explicit reported-document corrections in current-state view | None as a normal dimension | Transaction fact with observed change history; preserve source corrections/status changes rather than calling them customer SCD |
| sales_order_lines | Explicit entry correction in current fact view | None | Mutable sales-line fact; cannot promise immutable original quantity/price before capture began |
| payment_transactions | Corrected raw posting attributes in current fact view, with history | None | Signed payment-posting fact; no retroactive fabricated successful capture/refund graph |
| stock_balance | Manual reorder_level correction when identified as typo | reorder_level policy changes only if a replenishment dimension is useful | Quantity fields are balance facts/snapshots, not Type 2 dimension versions per change; conflicting duplicate rows unresolved |

For files: supplier offer costs/pack factors/department mappings can become effective-dated reference history after approval; finance adjustments, returns, deliveries, physical counts and historical sales remain facts/observations with revision history, not ordinary SCD dimensions. Code crosswalks may require their own downstream effective periods, especially when codes are reused; they are not new operational source tables.

Use source commit time/order for CDC-observed Type 2 validity, half-open intervals and deterministic tie handling from the actual payload. Classify ambiguous master changes as history-preserving initially unless privacy requires erasure; Type 1 correction requires an explicit authorized correction rule. File revision receipt time, extract time and business-effective date are different clocks. Do not invent historical effective dates from null/stale updated_at. Coverage starts at the agreed baseline or a trustworthy archive; pre-baseline moves/prices cannot be recovered just by SCD processing.

PII privacy corrections/erasure must propagate to raw, historical, current and exported copies under an agreed policy. Preserving every old customer address as Type 2 indefinitely is not a retention decision. Identity linkage must remain auditable without retaining forbidden personal values.
