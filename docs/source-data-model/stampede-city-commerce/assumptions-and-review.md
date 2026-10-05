# Assumptions, outstanding decisions and validation

## Proposed decisions

1. KAN-21 scope is the seven requested MySQL domains only; the older application is an assumed realistic source, not a database introspection result. Small Alberta-oriented retailer with stores, stockrooms/depot, POS, phone/back-office and limited web order entry. Actual scale/operating geography needs owner confirmation.
2. `scc` uses InnoDB on a supported Aiven MySQL release. Older/messier refers to business data/application discipline, not an unsupported engine. Local positive numeric IDs provide CDC identity; raw codes are separate, often nonunique.
3. Customer master holds a single mutable address and unparsed person/household/trade name. Anonymous WALKIN cards and duplicate people are expected; no master identity merger or marketing-consent claim.
4. Item master contains flat departments, abbreviations, generic/pack items and mixed units, not a category hierarchy or modern variant system. CAD is the operational assumption; any currency normalization is evidence-based and flagged. Supplier quotes can have other currencies.
5. Order numbers are scoped printed references, not unique order IDs. Customer/item associations are weak logical references; order-line parents, optional known payment/order/location links and stock/master links remain enforced. Null relationships and orphan logical references are explicitly different.
6. Invoice totals/line prices/customer-entered text can change after payment. The model exposes this reality rather than claiming original commercial snapshots. Signed negative credit lines exist; status/payment/refund fields are raw, not a full lifecycle machine.
7. Payment records are signed postings with missing/duplicate receipt/provider references, no authorization/capture graph or per-line allocation. Legacy duplicate imports are business-quality issues; replay dedup must not hide them. Actual bank settlement is not established by this source.
8. Stock balance is reported state with negative/null/stale/duplicate balances and mixed units. There is no movement ledger, reliable unavailable-stock field, transaction-safe reservation lineage or in-transit transfer representation. Count observations aid reconciliation but cannot prove causes of inventory changes.
9. Audit times are nullable second-precision local DATETIME, application maintained and potentially stale. Alberta timezone conversion is a stated assumption, with DST/missing-zone flags. No row_version/UTC timestamp discipline is attributed to the legacy system.
10. Historical sales, paper returns, dispatch status, physical counts, supplier spreadsheets and finance adjustments remain CSV/JSON. Candidate keys/manifest/replacement semantics are proposals; do not mistake them for contracts already implemented by legacy producers. Proposed archive boundary is 2024-01-01, pending coverage agreement.
11. No DDL, source generator, pipelines, infrastructure, new technologies or architecture edits. Source schema proposal, file contracts, CDC envelope and downstream SCD/identity rules require separate approval before ingestion begins.

## Remaining questions / risks

- Confirm actual MySQL release, collation/strict SQL mode, audit-write behavior, stable ID preservation and Aiven/DMS CDC prerequisites. Decide who is allowed to insert explicit IDs; reserve identity assignment to controlled migration/application code.
- Confirm branch/till numbering scopes, file coverage/cutoff and whether older database rows exist; overlapping archive/current records must not inflate sales. Historical payment archives are not currently specified, so pre-cutoff cash reporting is incomplete.
- Confirm tax/freight and header/line discount conventions by producer. Agree reconciliation tolerance and sign/reversal behavior. Without original capture/line allocation evidence, do not promise per-unit refund limits or reliable consolidated margin.
- Approve unit conversions with effective periods and generic-item/category/location crosswalks. Weighted goods cannot map to Rocky Mountain integer each by rounding. Source code reuse and stock duplicate survivors require stewardship.
- Confirm CSV date/number/null/encoding dialects, JSON completeness, ownership, revisions, withdrawal rules and delivery cadence. Return/order/dispatch matching may remain ambiguous; no guessed links are accepted as verified relationships.
- Agree retention/PII erasure, audit actor handling, business-effective correction classification, CDC ordering/delete payload and SCD policies. Missing source historical evidence stays a documented gap.

## Future meaningful acceptance scenarios

These scenarios guide later schema/simulator/CDC/analytics tests; this task delivers documentation only.

| Scenario | Expected outcome |
| --- | --- |
| Duplicate normalized customer/item/location codes | Distinct source IDs preserved; ambiguous crosswalk flagged, no automatic merge |
| WALKIN/shared email/business-name customer | Anonymous/trade classification retained; no false real-person identity |
| Orphan logical customer/item reference | Allowed raw source row; flag unresolved/conflict downstream |
| Missing enforced order parent or stock item/location | Source insert rejected without disabling FK checks |
| Duplicate order/line_number | Rejected at source; duplicate different-line-number business entry remains reviewable |
| Reused order/receipt numbers and duplicate imports | Source PK identity preserved; reconciliation uses scoped evidence, no false transport dedup |
| In-place paid-invoice correction with unchanged updated_at | Distinct CDC changes retained/ordered independently of audit time |
| Negative credit/refund/stock and wrong sign/status | Preserve typed raw values; flag/withhold affected trusted measures, no fabricated source policy |
| Null stock or duplicate pair balance | No implicit zero/sum/latest-audit survivor; approved reconciliation required |
| CASE/KG conversion absent or changes | Retain raw quantity/unit; block unsupported each conversions |
| Header discount overlaps line discount/tax missing | Preserve both amounts; no double subtraction or invented tax |
| Return register and negative line/refund overlap | Merchandise/physical-return/cash facts linked before net metrics; approved credit not cash payment |
| Local DST ambiguity/missing audit timestamp | Raw time retained, conversion flag set; CDC sequence supplies state order |
| CDC update/delete/replay/reordered parent arrival | Source-key convergence and no stale delete resurrection; unresolved loose FK can remain unresolved |
| Full file revision/truncation/overlap/replay | Validate completeness/scope/checksum; exact replay has no new effect; partial file does not imply deletes |
| Historical/current authority boundary | Explicit resolved ownership prevents double-counted sale lines |
| Schema/status changes and privacy erasure | Approved evolution preserved; privacy policy applies to historical and raw copies |

## Existing documentation review

Read KAN-21, AGENTS.md, README.md, docs/architecture.md and its diagram, docs/problem-statement.md, docs/decisions.md, the Rocky Mountain source-model documentation and component README files before design. The architecture remains MySQL/Aiven with AWS DMS -> S3 for CDC and CSV/JSON -> S3 for legacy data, Databricks/Delta, Snowflake/dbt and Airflow/Astronomer.

| Existing document | Review result | Update needed for KAN-21? |
| --- | --- | --- |
| AGENTS.md and README.md | Phase 1 remains active; no ingestion approval inferred | No |
| docs/architecture.md and diagram | File/CDC paths and platform responsibilities unchanged | No |
| docs/problem-statement.md | Smaller source still serves integration/business goals | No |
| docs/decisions.md | ADR-001..006 remain valid; no MySQL migration into PostgreSQL | No |
| Rocky Mountain model documents | Approved model unchanged; new cross-company comparison lives in this directory | No modeling edits; old KAN-20 proposal wording is historical and may be handled by a separate status-documentation task |
| source-simulator and other component README files | Implementation still waits on agreed contracts | No |

All new work stays under `docs/source-data-model/stampede-city-commerce/`. No existing document requires correction to support this proposal. Current-source ownership is documented locally, not an architecture change or silently approved global contract.

## Documentation validation

Read-only Python documentation checks passed for seven files, seven table definitions and 94 domain columns plus three audit fields per table; exactly one non-null unsigned numeric PK per table; matching types for six enforced FKs; constraints/index declarations; explicitly non-enforced references; table inventory and CDC/SCD coverage; six legacy-file datasets; relative links/anchors; Markdown table widths/fences; whitespace; no DDL; current feature branch and directory-only change scope. Manual review covered FK index prefixes, amount/unit/authority distinctions, duplicate-record handling, file revision scope and MySQL identity/CHECK semantics against official MySQL/AWS documentation. No approved Rocky Mountain files or executable components were changed. Database/integration tests are not applicable until an executable schema exists; future behavior scenarios above are not claimed to pass yet.
