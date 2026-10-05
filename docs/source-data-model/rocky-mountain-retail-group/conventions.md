# Shared conventions and enforcement

These definitions are part of **every table** in the dictionary. Column tables list domain columns; the following audit columns must be added to each of the 17 tables without exception.

| Column | PostgreSQL type | Nullable | Contract |
| --- | --- | --- | --- |
| created_at | timestamp with time zone | No | Database-assigned creation time; immutable; default current transaction time |
| updated_at | timestamp with time zone | No | Database-maintained on every meaningful row change, including status and privacy changes; initial value equals created_at |
| row_version | bigint | No | Starts at 1; increments once per row update; optimistic concurrency token; strictly positive |
| created_by | varchar(100) | No | Stable application/service actor ID; never credentials or free-form PII |
| updated_by | varchar(100) | No | Actor responsible for most recent change |

Database invariant: `updated_at >= created_at`. Later DDL must implement database-side timestamp/version maintenance and immutable-key enforcement, not rely solely on simulator discipline. Transaction timestamps can tie and are not a global sequence. Historical event times below are separate from these audit times. Use UTC for interchange; `timestamp with time zone` represents instants, not a stored original timezone name. Store/warehouse timezone fields retain business timezone names. Source audit fields must survive downstream; DMS operation, commit/order, and ingestion metadata are additional fields, never substitutions for them.

## Types and keys

- Every primary key is non-null, positive, database-generated `bigint` identity, never reused or changed. All corresponding foreign-key columns are `bigint`. Identity is not a business number or evidence of event order.
- Business identifiers (`customer_number`, SKU, order number, location codes) are separately unique, nonblank, stable and not reused after retirement. Codes are trimmed uppercase ASCII unless explicitly described otherwise. Human names/descriptions are Unicode strings. Normalization is performed before writing; key codes are checked for the agreed canonical form.
- Quantities are `integer` whole selling units; ledger deltas can be signed. Money uses `numeric(18,2)`; price and tax computations use decimal arithmetic with half-up rounding to two decimal places at line level. Percentages use `numeric(5,2)`, from 0 to 100. No floating-point money.
- Phase 1 supports CAD and USD (`char(3)`, required currency values limited to those codes). One order has one currency; operational prices are in their stated currency. No implicit FX conversion. Country fields are `char(2)`, uppercase ISO country codes; authoritative code validation is an application/reference-data rule. Timezone fields are `varchar(64)` IANA zone names, validated by the application.
- Status/type/reason fields use bounded `varchar` plus explicit allowed-value constraints; avoid PostgreSQL enums for changeable business vocabularies. Null never means a hidden status. A future vocabulary change requires a reviewed contract revision.
- Non-null textual identifiers and required names/address text must be nonblank after trimming. Phone numbers use `varchar(25)` canonical E.164 when present. Postal codes are `varchar(20)`, country-specific validation outside the database. Email is `varchar(254)` with trimming and lowercasing; syntax verification is an application responsibility. Email is not a customer identity key.
- No JSON blobs for core domain relationships or money. Product variants are individual SKUs; no array of line items or embedded payment details. Secrets, full card numbers, CVV, bank credentials, and raw gateway payloads are excluded.

## Foreign keys, constraints, and indexes

Unless stated otherwise, every listed foreign key has **ON DELETE RESTRICT and ON UPDATE RESTRICT** semantics. No automatic cascade erases operational history. Nullable foreign keys permit absence only as explained in their column descriptions. Retirement is via lifecycle status or `archived_at` where provided; no global soft-delete flag is invented for every fact table.

Primary keys and declared unique keys supply B-tree indexes. Listed secondary indexes are B-tree unless explicitly partial or expression-based. Do not create a duplicate index for an existing key prefix. Index every foreign-key access path, using the listed composite indexes or an additional single-column FK index when no listed index begins with that FK. This rule includes self-references and optional provenance/reversal fields. Composite same-order foreign keys require corresponding parent unique keys even when the ID itself is already unique; this intentional redundancy enforces ownership. Add those unique keys exactly where specified.

Database enforcement covers non-null values, primary/unique/foreign keys, row-local checks, and partial uniqueness. Cross-row sums, category cycles, lifecycle transitions, balances, and counterpart movement matching require transactional business logic with locks, or later reviewed constraint triggers. A plain row CHECK is not proposed as a cross-table validator. This follows PostgreSQL's documented [constraint semantics](https://www.postgresql.org/docs/current/ddl-constraints.html).

Partial unique indexes can enforce **at most one** current default address; they do not ensure a default exists. Inventory, shipments, and returns each require exactly one store/warehouse location FK on every row, including initial and terminal states. Future database row checks must reject both-null and both-populated pairs; FKs independently validate the selected location. Location uniqueness on inventory uses two partial unique indexes because one location FK is null. All predicate conditions are specified in the table docs. These designs do not depend on a particular PostgreSQL extension or on `NULLS NOT DISTINCT` support.

## Transaction and lifecycle rules

- Customer/order/address ownership, currency alignment, cumulative quantities, financial reconciliation, and inventory reservation updates are atomic business transactions. Lock affected order, payment parent, and inventory rows; lock inventory in ascending ID order to reduce deadlocks. Later implementation must reject stale `row_version` writes and retry transient conflicts safely.
- Inventory reservations live in `inventory.quantity_reserved` in this scope; there is no per-order reservation table. Fulfillment must allocate/consume/release reservations atomically. Exact reservation lineage is a documented limitation, not something inferred from aggregate balances.
- Creation retries reuse domain idempotency keys (specified per table). Database CDC replays are a different concern: a replay must not create new operational business rows.
- Transaction documents freeze customer-facing prices/addresses upon placement. Corrections occur through explicit amendments before fulfillment, cancellation, return/refund, or stock reversal; silently editing fulfilled quantities or successful money operations is forbidden.
- Source constraints reject malformed operational rows. Malformed feed/quarantine simulation belongs to later ingestion contracts, not disabling source constraints.

All tables participate in CDC, including reference tables and auxiliary lines. See [CDC contract](cdc-and-scd.md) for delete, replay, and history rules.
