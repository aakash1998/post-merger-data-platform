# Enterprise keys and logical crosswalk structures

These are platform-neutral **logical analytical records**, not new operational database tables or physical DDL. Field types below describe meaning/interchange rather than choosing a storage engine. Use the existing lakehouse/analytics platforms when implementation is authorized.

## Source-qualified identities

Source identity tuple: `(source_system, source_instance, source_namespace, source_entity, source_pk)`. Store tuple components separately; display serialization is escaped/versioned, never ambiguous string concatenation. source_instance is a registered logical database identity, not a hostname that changes during managed-service failover. Production/test instances never share identity. Namespace is the registered schema/database; a rename needs a reviewed registry alias, not silent creation of new entities.

| Domain | source_system | source_namespace / source_entity | source_pk |
| --- | --- | --- | --- |
| Customer | rmrg | rmrg / customers | customers.customer_id |
| Customer | scc | scc / customer_master | customer_master.customer_id |
| Product | rmrg | rmrg / products | products.product_id |
| Product | scc | scc / item_master | item_master.item_id |

Registered logical instance names can initially be `rmrg-retail-prod` and `scc-retail-prod`, pending environment confirmation. Numeric PKs serialize as lossless canonical base-10 positive strings (including unsigned MySQL bigint where encountered); never JavaScript floating-point numbers. This is typed PK serialization, not normalization of customer_number/customer_code/SKU/item_code/barcode strings. Original business codes retain whitespace/case/leading zeros and source provenance separately.

Customer addresses are evidence owned by customers via their source FK, not independent person identities. Categories are product-classification evidence, not product identity. SCC order customer_id_ref and line item_id_ref must first resolve within the SCC source instance; contradictory ID/code references remain quality cases even if the master record has an approved enterprise mapping.

RMRG key 42 and SCC key 42 are different identities; customer 42 and product 42 are different domains. Source business codes can change/recur without changing source identity. If the same SCC item PK is repurposed for a different real product, preserve that PK and date-separated enterprise assignments with reviewed evidence. PK reset/reuse after restore violates approved source assumptions: quarantine it and require a reviewed instance-epoch repair, never silently remap all historic rows.

Files do not acquire invented source master PKs: customer/item codes in historical_sales.csv or supplier_catalog.csv are references. Resolve a dated, source-scoped alias only when unambiguous evidence identifies a master record; otherwise keep dataset/batch/record provenance and unresolved enterprise key. Current code ownership is not proof of historical ownership.

## Canonical key and grain strategy

Enterprise identifiers are opaque, centrally persisted UUID values represented as strings: enterprise_customer_id and enterprise_product_id. The logical entity registry ensures global uniqueness; domain is required in all joins, so one domain's UUID never stands in for another. Generate a key once in the authorized later implementation, persist it, and reuse it on replay; no new technology or generation library is selected here.

- Do not derive a key from name, email, phone, address, SKU, barcode, chosen winner source PK, mutable attributes or cluster member ordering. Changing those values must not change an entity key.
- Customer entity_kind is `person`, `organization`, or `household_account`. A SCC trade/business account can be an organization or household/account after review; it is not silently a person because its contact name resembles an RMRG person. Person-to-organization employment/contact relationships are outside this identity contract.
- Product entity_kind is `sellable_variant`. Variant and selling-package definition is part of identity, with canonical_unit and pack definition explicitly documented. A CASE of 12 and one EACH remain separate enterprise products; an approved contains/conversion relation supports common-unit analytics without making their identities equal. Weighted products can have canonical_unit `kg`; this does not change RMRG's each-only source contract.
- A legitimate source record with no suitable match can be approved as a **singleton** enterprise entity after eligibility/distinctness review. Such records are mapped with decision_type `singleton`, not falsely labelled a cross-company match. Mere absence of a candidate does not prove a new person/product and does not automatically mint a new enterprise key.
- Unknown, generic, anonymous or contradictory records can remain unmapped/excluded. Facts retain source identity and resolution status; an optional reporting “unknown/anonymous” class is not an enterprise person/product and must be excluded from distinct identified counts.
- Enterprise keys never get recycled/deleted because one source retires. Merge/split lineage is explicit; warehouse dimension-version keys are separate from stable enterprise IDs.

## Logical record inventory

| Record | Grain / logical key | Purpose |
| --- | --- | --- |
| entity_registry | One domain + enterprise_id | Entity kind, lifecycle (`active`, `merged`, `retired`), created/retired decision reference; holds stable identity, not a winning source row |
| source_assignment | One mapping_id and revision of a source identity's business-valid decision interval | Approved target or explicit unresolved/excluded state; temporal source-to-enterprise crosswalk |
| match_candidate | One candidate_id for two source identities and evidence/version scope | Proposed link, confidence, conflicts, disposition; alternatives never treated as approved membership |
| decision_log | One immutable decision_id | Approval/rejection/merge/split/evidence authority, reviewer and affected records |
| cannot_link | One same-domain source/entity pair and effective/recorded interval | Reviewed negative constraint preventing repeated false proposals or transitive cluster merges |
| entity_lineage | One approved predecessor/successor relation per decision and interval | Merge/split/correction history; split is not a single blind redirect |
| business_alias | One source-scoped code occurrence/owner and validity/evidence interval | Dated candidate lookup, never a universal customer/product key |
| attribute_selection | One enterprise attribute/version and selection decision | Chosen analytical value, winning source/version and alternative provenance |
| product_relation | One approved typed product pair and validity/decision interval | Packaging/conversion relation, never crosswalk identity membership |

These records can be realized in configuration/datasets within the existing stack. Their separation describes distinct semantics, not a mandate for nine physical tables.

## source_assignment structure

All fields are required unless explicitly nullable. A crosswalk version is uniquely identified by `(mapping_id, revision)`; mapping_id is persistent for the decision interval, revision a positive integer. Each source identity has at most one current decision state and one approved enterprise target at any business instant and knowledge instant.

| Field | Logical type / nullability | Contract |
| --- | --- | --- |
| mapping_id, revision | UUID string; positive integer | Stable interval identity plus revision; never reused |
| entity_domain | customer or product | Target domain must agree |
| source_system, source_instance, source_namespace, source_entity, source_pk | Strings | Complete registered source tuple; always retained even after merge/retirement |
| enterprise_id | UUID string, nullable | Required exactly when mapping_status = approved; null for unresolved/excluded/terminal decision rows |
| mapping_status | Enumerated string | Values below; controls eligibility to attribute facts |
| decision_type | Enumerated string | `singleton`, `link`, `merge`, `split`, `correction`, `hold`, `exclusion`, `expiry`; must agree with status |
| entity_kind | Enumerated string, nullable | Required for approved assignment; must agree with target registry kind |
| confidence_level | Enumerated string | Evidence class below; confidence alone never approves a mapping |
| rule_id, rule_version, normalization_version | Strings | Exact policy/configuration versions; steward-only singleton can use explicit not_applicable rule marker |
| confidence_score, score_definition_id | Decimal 0..1; string, both nullable | Optional ranking measure only when both present; not a calibrated probability unless separately validated |
| evidence_snapshot_id | String | Immutable restricted evidence reference for source versions, corroboration and conflicts |
| candidate_id | UUID string, nullable | Candidate supporting a link; singleton/exclusion may have none |
| decision_id | UUID string | Decision-log linkage, including initial unresolved observation decisions |
| valid_from, valid_to | UTC instant; nullable UTC end | Half-open business applicability interval; unknown start is represented by documented known_from policy, not null/1970 invention |
| effective_basis | Enumerated string | `source_observed`, `steward_business_date`, `archive_period`; source audit time not automatically valid_from |
| recorded_from, recorded_to | UTC instant; nullable UTC end | Half-open knowledge interval for this revision; records what was believed when |
| supersedes_revision_ref | mapping_id/revision reference, nullable | Correction linkage; old revision remains queryable |
| mapping_run_id, input_snapshot_id | Strings | Evaluated input snapshot/run; exact replay converges on prior decision/IDs |
| created_at, created_by | UTC instant; actor ID | Mapping creation evidence, not source created_at |
| reviewed_at, reviewed_by | UTC instant; actor ID, both nullable | Required for approved/excluded human decisions; initial automated observation can lack reviewer |
| reason_code, reason_detail_ref | String; restricted reference, latter nullable | Structured rationale and optional restricted details, no free-text PII in general logs |

Source created_at/updated_at/row_version (RMRG only), CDC commit/sequence/operation, file checksum/batch/revision/position where applicable and source-quality flags live in the linked evidence snapshot. No source timestamp is replaced by mapping/ingestion timestamp. Evidence retention/erasure follows approved privacy rules.

## Status and confidence vocabularies

| mapping_status | Meaning / target | Publication rule |
| --- | --- | --- |
| unmapped | No approved assignment, enterprise_id null | Source-only/unresolved reporting; candidates may exist separately |
| review_required | Unresolved new assignment or hold interval, enterprise_id null | No enterprise attribution for that held interval |
| approved | Reviewed singleton or identity link, enterprise_id non-null | Eligible subject to effective/knowledge intervals, entity kind and source-reference quality |
| excluded | Anonymous/shared generic/nonidentity record or explicit policy exclusion, enterprise_id null | Retain source records; do not invent identified counts |
| expired | Closed unresolved/exclusion state, enterprise_id null | Terminal decision snapshot; historical approved intervals remain represented as approved with valid_to |
| superseded | Withdrawn unresolved/exclusion state, enterprise_id null | Nonapproved administrative state; old approved knowledge revisions keep their original status |

Ending a formerly approved assignment **does not overwrite its status/target**: close its valid/recorded interval and append the replacement. expired/superseded are not how approved targets are erased. Reviewed rejections are pair-specific `match_candidate.disposition = rejected` and/or cannot_link, not a declaration that the whole source record can never match anybody.

Candidate disposition values: `proposed`, `in_review`, `approved`, `rejected`, `deferred`, `superseded`. Candidate approval authorizes a decision; the actual fact join still uses approved source_assignment, never a candidate row. Candidate structure carries both source tuples, same domain, source/version interval, candidate rank, evidence/conflict flags, rule versions, confidence/score, disposition and decision/reviewer references. It records no “winning” assignment until reviewed publication succeeds atomically.

Confidence values: `confirmed` = steward-confirmed with cited identity evidence; `high` = strong compatible multifeature evidence, unique eligible candidate; `medium` = plausible with missing corroboration or fuzzy element; `low` = weak single-field similarity; `insufficient` = not enough usable evidence; `contradictory` = material conflict/veto. Reviewer may approve medium/high evidence only by adding confirmation/rationale; the approved link records confirmed with original pre-review class retained in evidence. Singleton confirmation confirms entity eligibility, not a cross-company match probability.

## Invariants and safe joins

- Assignment business intervals must not overlap for the same source identity at the same knowledge version; recorded intervals for one revision chain cannot overlap. End > start; null end means open. Approved assignment target must exist with compatible domain/kind.
- Many source identities can map to one enterprise entity; one source identity cannot concurrently map to multiple enterprise entities. Alternative candidates do not multiply facts. Before approval, validate the whole affected cluster against cannot-link, party-kind and product-variant/package conflicts; pairwise transitivity is not proof.
- Business aliases can overlap/collide and therefore generate multiple candidates. No alias overwrite hides reused code ownership. Facts with only a reused code and no valid date/master evidence remain unresolved.
- Join a fact using its source master identity and applicable business time plus the chosen mapping knowledge snapshot. At most one eligible assignment; overlaps are errors, not MAX(confidence)/latest-row selection. A date-only fact with a mapping change within that day stays unresolved unless approved day-level policy proves ownership.
- Facts always retain original source master IDs/references, amounts, units and transaction grain. Enterprise attribution is additional metadata; it does not consolidate duplicate sales/payment facts or convert quantity/money by identity merge.
