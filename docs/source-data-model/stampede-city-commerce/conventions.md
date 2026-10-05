# Source conventions and enforcement

## Technology and identity

Assume a supported Aiven MySQL release with InnoDB and `utf8mb4`. Verify the actual server/DMS version compatibility before DDL or CDC setup. This is a legacy application design, not a recommendation to run an unsupported old database version. IDs are positive auto-increment values, immutable and not reused after deletion. Normal writes obtain positive IDs from auto-increment; controlled import/application code must reject explicitly assigned zero IDs and key changes. Positivity/immutability is a write contract, not a CHECK on an AUTO_INCREMENT column (MySQL disallows that). Child FK types match size and unsignedness exactly.

All declared FKs use ON DELETE RESTRICT / ON UPDATE RESTRICT. Do not disable FK checking to manufacture orphan fixtures. Logical references explicitly marked **not enforced** may be missing or invalid. Indexes are ordinary MySQL B-tree indexes, including explicit FK indexes where not covered by a leading key. No PostgreSQL partial-index design is copied. FK support requires matching types/indexes as described in the [MySQL FK manual](https://dev.mysql.com/doc/refman/8.0/en/create-table-foreign-keys.html).

Nonunique business-code indexes use explicit `utf8mb4_bin` collation for case-sensitive lookup. Retain case and surrounding whitespace as source evidence; downstream normalization can create collisions. Comparison semantics alone are not byte provenance, particularly trailing spaces: preserve original strings and their hashes downstream rather than treating an indexed equality lookup as identity. IDs alone are unique, except the order/line-number pair specified in the dictionary. Email, item/customer codes, payment references and stock item/location pairs are intentionally not unique.

## Shared audit columns — present on all seven tables

| Column | MySQL type | Nullable | Source behavior |
| --- | --- | --- | --- |
| created_at | DATETIME | Yes | Application-entered local wall-clock creation time, whole seconds; null for unknown imported records |
| updated_at | DATETIME | Yes | Last reported application edit time; some legacy batch edits fail to change it |
| updated_by | VARCHAR(30) | Yes | Short operator/application code; may be blank/shared, never a secret |

No automatic timestamp defaults/triggers or row-version counter are assumed. New normal application writes should set these times, but fixtures can reflect null, tied, stale or regressing audit values. Do not add a source CHECK requiring updated_at >= created_at: violations are quality evidence. Do not use updated_at as a CDC watermark. Missing audit values remain null, never invented as ingestion time. Physical deletes carry no source deleted_at.

All source DATETIME fields, including audits, are **local wall-clock values**, normally `America/Edmonton`; MySQL DATETIME does not carry a timezone or perform TIMESTAMP-style session conversion. Preserve raw time, location and the stated conversion assumption; missing timezone or DST ambiguity is an explicit quality flag, not silently resolved. Source DATE fields represent business/calendar dates. Do not fabricate an exact instant from a date. This distinction follows [MySQL temporal type semantics](https://dev.mysql.com/doc/refman/8.0/en/datetime.html).

## Types and deliberately limited checks

- Monetary values are signed DECIMAL, not floating point or MySQL ENUMs. Raw quantities use signed DECIMAL(12,3) to allow legacy EA/KG/CASE records; there is no automatic mapping to Rocky Mountain's integer units. Money is CAD operationally, but null/malformed currency labels remain visible and must be validated before reporting. Currency strings are VARCHAR(8), not a guaranteed ISO code.
- Names, addresses, phone/email, statuses, departments and reasons are raw bounded text. Blank strings and null have different source representations. Not-null raw codes can still be blank; blank-code tests are downstream, not hidden CHECKs. Country/province strings may be full names/abbreviations; phones are not forced to E.164.
- Enforce PK uniqueness/non-null unsigned storage, line_number > 0 and structural FK/unique constraints as specified; positive generated identities and key immutability follow the write contract above. Monetary nonnegativity, quantity ranges, status vocabularies, timestamp ordering, default-address uniqueness and financial equations are **not** source constraints. Source numeric limits still reject overflow/type-invalid values; strict-mode setup should reject invalid/zero dates. Malformed numeric/date strings belong in file-quality fixtures, not typed DB columns.
- MySQL CHECK enforcement must be verified for the deployed release; [CHECK constraints](https://dev.mysql.com/doc/refman/8.0/en/create-table-check-constraints.html) became enforced in 8.0.16. The design does not claim unsupported checks work on older releases.
- Payment fields exclude card numbers, CVV, bank credentials and opaque gateway payloads. Free-text notes are excluded to avoid accidentally copying sensitive unstructured content.

## Business intentions versus guarantees

The old application intends positive sale quantities, known customer/item codes, balanced invoice totals, receipt/refund reconciliation and one balance per item/location. It can commit violations because imports and manual corrections do not share transactional controls. These are reporting/reconciliation rules, not guarantees from PKs/FKs. Retain originals in Bronze, flag ambiguity in Silver, and withhold affected measures from trusted marts rather than rewriting the source contract to make every legacy row clean.

Insert retries may create multiple source PKs for one business receipt; CDC replays repeat a single source change. Keep those distinct: transport deduplication must not erase genuine duplicate source records before business review. Normal retirement changes raw active/status fields. Controlled deletes remain possible and captured; no cascading deletion or reliable soft-delete flag is assumed.
