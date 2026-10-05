# Stewardship, temporal history and audit rules

## Review workflow and publication

1. Observe source identities/versions, classify eligibility and create source_assignment unmapped or an explicit exclusion after approved classification. Preserve raw values/CDC or file evidence references.
2. Generate same-source and cross-source candidates under versioned domain rules. Record alternatives, quality/missingness, corroboration, contradictions, candidate counts and ranking information. Existing assignments continue unless a material conflict warrants a hold for a defined period.
3. Route ambiguous/new candidates to domain stewards. Customer reviewers check party kind, contact sharing and temporal/person evidence; product reviewers check variant/package/UOM and barcode ownership. No source records are edited as part of mapping review.
4. Reviewer approves link/singleton, rejects a pair, defers for evidence, or excludes a nonidentity source record. Pair rejection records a reason and, when definitive, cannot_link; it does not ban the source from other candidates. Deferred/proposed/rejected alternatives never attribute facts.
5. Before publication, validate all source and target revisions, whole-cluster cannot-link/type/package checks, source interval uniqueness, approved target compatibility, relevant consent/privacy holds and reviewer authority. If evidence/assignment changed while under review, re-review affected changes; do not approve a stale candidate silently.
6. Publish the decision, assignment intervals, entity registry/lineage, any approved aliases/relations and attribute selections as one consistent mapping release. Later implementation needs atomicity or a consistent versioned snapshot; consumers cannot combine half a merge with old member assignments.
7. Track mapping coverage/conflicts, reviewed false matches, stale evidence and reversals. New contradictory evidence triggers review/hold, not an automatic target swap. Transport replay reuses persisted keys and decisions.

Initial policy: no automatic **cross-record** links for either domain, including exact GTIN and exact combined contacts. Steward bulk approvals are allowed only if each affected pair/cluster passed the same evidence and conflict checks and each decision has explicit scope. Initial unmapped observations and candidate generation can later be automated without authorizing a link. Future automated linking requires independently approved rule-version evaluation results and release controls, outside this documentation task.

Mapping stewards resolve enterprise identity; source-data owners resolve invalid raw references/codes/amounts. A mapping approval does not certify a suspect SCC sale customer_id_ref/item_id_ref. Review outcomes must preserve that unresolved transaction-reference flag even when the master crosswalk is approved. No ordinary row-level correction can hide a customer/product collision by rewriting the source.

## decision_log and review provenance

| Field group | Required content | Purpose |
| --- | --- | --- |
| Identity/scope | decision_id, decision_type, entity_domain, affected source tuples and old/new enterprise targets | Exact scope of link/singleton/exclusion/merge/split/correction/rejection |
| Replay/concurrency | decision_request_key, expected assignment/evidence revisions, published mapping_release_id | Stable request key reused on retry; changed evidence cannot create accidental duplicate entities or overwrite newer decisions |
| Evidence/policy | candidate_id(s), rule_id/version, normalization_version, input_snapshot_id, evidence_snapshot_id, conflict/cannot-link evaluation | Reconstruct what reviewer saw and which alternatives were evaluated |
| Decision | pre-review confidence, confirmed outcome where approved, structured reason_code, restricted rationale/evidence references | Confidence remains explainable rather than an opaque score |
| Authority | created_at/by, reviewed_at/by, approver role/scope; optional independent approver for sensitive merges/splits | Identify responsible steward; merge/split independent-review requirement remains an approval-policy question |
| Time | effective interval and basis, recorded_at, supersedes/undo decision references | Separate business applicability from when decision was known |
| Operational provenance | matching_run_id, mapping_release_id, source snapshot/CDC coordinate or file batch/revision/checksum, source quality flags | Audit/replay lineage without guessing source updated_at ordering |

Store direct PII only in restricted evidence with agreed access/retention. General logs/Jira carry decision IDs, source keys, rule IDs and reason codes rather than full names/contacts/addresses. Input fingerprints are not anonymization or a substitute for retaining authorized evidence. Anonymization/erasure must propagate through raw/normalized/contact/attribute-selection history as required while preserving permitted non-PII decision lineage. No source secret or credential is needed for the mapping contract.

## Two time axes and effective dates

Business-valid intervals use `[valid_from, valid_to)`; recorded/knowledge intervals use `[recorded_from, recorded_to)`. Null end is open, equal-boundary handoff is permitted, end <= start is invalid. Times are UTC with source/timezone conversion provenance. DATE-only business facts and uncertain SCC local timestamps are not converted into invented exact instants.

Default valid_from is the first **known applicable** source observation under the agreed baseline/source commit ordering; a steward can approve an earlier business date/period only with cited reliable evidence. created_at/updated_at, registration date, current code owner or file extract time alone cannot establish a historic match. For day-level decisions, record the approved timezone/day boundary and precision; a source date spanning two distinct assignments remains ambiguous unless evidence resolves it. No blanket backdating to 1970 or all pre-baseline sales.

When a decision is corrected, append a new knowledge revision; close the previous recorded interval and retain its original business interval/target/status. At the new knowledge time, publish corrected nonoverlapping valid intervals. Closing an old approved interval never erases its enterprise target or rewrites raw facts. Subject to privacy rules, reports can ask either “what did we believe then?” or “what is the approved attribution now for that business period?”

Example: source S was assigned to customer E1 from January 1, approved January 10. On March 5, review proves S represents E2 from February 1 onward. Illustrative dates are not real customer data.

| Assignment revision | Target/status | Business interval | Knowledge interval |
| --- | --- | --- | --- |
| M1 revision 1 | E1 / approved | Jan 1 -> open | Jan 10 -> Mar 5 |
| M1 revision 2 | E1 / approved | Jan 1 -> Feb 1 | Mar 5 -> open |
| M2 revision 1 | E2 / approved | Feb 1 -> open | Mar 5 -> open |

Before January 10 there was no approved knowledge claim for that period. A February fact queried as known on February 20 uses E1; the same fact under the March 5 release uses E2. An unresolved/anonymous period remains null enterprise target rather than a guessed E1/E2. Exact replay of March 5 yields the same M1/M2/entity/decision IDs, not a third target.

## Merge, split and false-match correction

Merge: review evidence for every affected member and select a surviving enterprise key using approved existing stewardship selection, otherwise earliest registry creation with UUID lexical tie-break; source company/PK/ranking score is not the selector. Retain predecessor keys and effective/recorded entity_lineage, mark predecessors merged only in the applicable registry history, and publish affected assignment revisions. Stable source identity never changes. Never apply a present-day redirect automatically to every historical fact.

Split/undo: a false match must be reversible. Restore prior enterprise keys for previously known distinct entities where possible; allocate new keys only for genuinely new partition identities with reviewed lineage. Assign specific source members and periods to specific successors. A split is one-to-many lineage; there is no universal predecessor -> one successor shortcut. Confirm the partition respects cannot_link and produces at most one eligible target per source/time. Original mistake, correction reason, approver and impacted release/report periods remain reconstructable under retention policy.

Transitive clusters require compatible party kind and product package/variant across all members. One high-scoring edge never overrides another pair's definitive cannot_link. Suppression records include pair/domain, reason, evidence, reviewer, valid/recorded interval and policy version; fresh contradictory or stronger evidence can reopen only through explicit decision review, not by changing a fuzzy score.

Source retirement/deletion: keep historical keys/assignments; cease new matching on unavailable evidence, and close future eligibility or open a reviewed hold as appropriate. One retired SCC account/product does not delete an enterprise entity supported by another source. Privacy exclusion may withdraw future contact-based matching and force attribute erasure; approved historical permitted attribution is handled under the erasure/retention policy, not inferred from an active flag alone.

## SCD and downstream fact behavior

Mapping history changes **membership**. Customer/product dimension SCD changes **attributes**. A customer moving or a product category/name correction normally versions/corrects attributes while preserving enterprise ID. A party-kind error, source repurposing or changed selling-package/physical variant may require reviewed membership correction or a new entity. Do not use a new dimension surrogate key as a new enterprise identity automatically.

Attribute_selection keeps selected value/effective period, selection rule/version, source identity and source row/address version, decision and alternatives/conflict evidence. Type 1 typo correction is distinguished from Type 2 real business change. Known authoritative erasure can replace useful old data; ordinary null/stale fields cannot. RMRG and SCC clocks/quality differences remain visible rather than deciding survivorship by greatest updated_at.

Facts retain original transaction/customer/item references, monetary amounts, units and source-line identity. Derived enterprise keys include mapping_release_id and applied assignment revision. Publish separate current-approved attribution and reproducible as-known/report-release views; an explicit restatement policy is needed before changing certified historical reports. A source-only unresolved view remains available and identified-entity metrics disclose resolution coverage.

Joins use approved assignments only, at most one per applicable source/time/knowledge; source-reference conflict, hold, ambiguous date/code ownership or excluded identity yields null enterprise key and reason. Do not copy arbitrary MAX confidence, fan out every candidate, change original order snapshots, double count duplicates after merging accounts, turn a product pack relation into an identity join, or multiply money by conversion factors. Backfills preserve original raw evidence and rerun the same approved release unless an explicitly authorized restatement uses a newer release.
