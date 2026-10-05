# Acceptance scenarios, assumptions and document review

## Proposed assumptions and decisions

- Scope is analytical customer/product identity and attribution for the approved source models, not source schema redesign or a new master-data application. Stores/channels and other shared entities mentioned broadly in Jira remain out of this user-requested scope.
- Approved source schemas lack authenticated shared person IDs, verified-contact flags and SCC structured variant/package fields. Strong normalized equality remains candidate evidence; default cross-record linking is steward-only for both domains. Rule confidence classes are not calibrated probabilities; no untested threshold is presented as proven precision.
- Opaque persisted UUID enterprise keys are distinct from source IDs and dimension-version keys. Real identified distinct parties/products can become reviewed singleton entities; unresolved/excluded records keep null target and source-qualified identity. Anonymous reporting classifications never count as one identified customer/product.
- Customers represent typed parties; person/organization/household_account are not interchangeable. Products represent variant/selling package; CASE versus EACH is a product relation, not identity collapse. Canonical analytics can retain decimals/KG without changing RMRG's integer each source model.
- Many source records can share an approved target, but one source record has at most one approved target at a valid/knowledge instant. Contradictory cluster pairs veto transitive merges. Source codes/barcodes/contact details remain aliases/evidence and can change or collide.
- Mapping publication uses consistent releases and append-only correction lineage. Valid/business time and recorded/knowledge time stay distinct; source-audit gaps and pre-baseline history are not fabricated. No source transaction/unit/money value is overwritten by attribution.

## Illustrative acceptance cases

These are expected behavior specifications for future implementation; no matching code or runtime tests are delivered here. Names/keys below are synthetic placeholders.

| Case ID | Scenario | Required outcome |
| --- | --- | --- |
| ID-01 | RMRG customer 42 and SCC customer 42 | Two source identities; no numerical-ID equality merge |
| ID-02 | RMRG customer 42 and RMRG product 42 | Different domains/targets; source-instance and domain-safe joins |
| ID-03 | SCC prod and test have same item key | Separate registered instances; no test-to-prod attribution |
| C-01 | Same name/email/phone/address, unique compatible party | High candidate, then steward-confirmed approved link; repeat evaluation reuses persisted decision/key |
| C-02 | Two family members share email/phone/address, different names | Review/contradiction; no email/household-to-one-person collapse |
| C-03 | Exact common name/address, no independent contact | Medium/low review, no automatic identity link |
| C-04 | SCC “J SMTH” near RMRG full name with exact phone | Fuzzy candidate with abbreviation risk; not confirmed by similarity alone |
| C-05 | RMRG guest contact matches known master; SCC shared WALKIN has an email | Guest/shared transactions remain null enterprise person under default policy; distinguish unresolved real account |
| C-06 | WALKIN-like code belongs to a legitimate named account | Classification reviewed by source ID/evidence; text pattern alone does not exclude |
| C-07 | SCC trade organization shares contact with employee's RMRG account | No cross-kind identity link; employment relationship outside scope |
| C-08 | SCC duplicate account PKs approved for same person | Both retained and mapped; no source-row/transaction deletion or credit/consent transfer |
| C-09 | A-B and B-C evidence positive but A-C cannot_link | Whole-cluster merge blocked; no blind transitive closure |
| C-10 | New address without changed person identity | Attribute history changes; enterprise key stable; historical order snapshots unchanged |
| C-11 | Source contact anonymized/privacy-erased | Stop new contact matching, apply approved evidence/attribute/history erasure, retain permitted non-PII lineage |
| P-01 | Exact validated GTIN, same variant/package/UOM, unique compatible candidate | High review candidate; steward approval still required |
| P-02 | Same valid barcode copied to wrong brand/size or duplicated SCC rows | Material-conflict review; checksum/uniqueness on one source does not certify identity |
| P-03 | Leading-zero GTIN-12 versus its validated GTIN-14 display | Compare approved normalized representation; preserve raw string/length; no integer conversion |
| P-04 | Internal barcode or bad check digit happens to match source code | No strong GTIN rule; retain raw evidence and low/insufficient candidate status |
| P-05 | Same description/brand but size/color/model differs | Different variant; no link through generic description or category |
| P-06 | Equal local SKU/item_code with no independent evidence | No identity assertion; source-local alias candidates only |
| P-07 | Verified case of 12 versus consumer each | Separate keys plus contains relation; quantity conversion labelled, money unchanged |
| P-08 | KG versus each, missing pack factor, stale/conflicting factor | No guessed conversion or rounding; incompatible/uncertain package identity reviewed |
| P-09 | Same SCC PK/code switches from pack 6 to pack 12 | Source PK stays; reviewed dated assignment/relation change; historic quantities use old definition |
| P-10 | Archived code references two owners across dates, event date absent/ambiguous | Unresolved enterprise target; no current-owner backfill |
| P-11 | Two legitimate source duplicates of exactly one product | Approved common key with all aliases/source facts preserved; not duplicate-transaction cleanup |
| P-12 | Generic assorted merchandise with no exact variant | Unmapped/review_required or excluded; no invented shared counted product |
| X-01 | Candidate rejected for E1 but credible E2 exists | Pair-specific rejection/cannot-link; source not globally excluded |
| X-02 | Valid unmatched distinct person/product after review | Singleton decision/opaque key; not reported as a successful cross-company link |
| X-03 | Two eligible approved assignments overlap one source/time | Publication fails; never select maximum score or fan out facts |
| X-04 | Reviewer approves stale evidence after source/assignment changed | Revision guard requires re-review; no overwritten newer decision |
| X-05 | Merge then false-match split with several members | Specific member/period reassignment, stable source keys, prior entity keys restored where possible; auditable lineage |
| X-06 | Business correction on Mar 5 effective Feb 1 | Two-time revision supports as-known versus current-approved attribution, without changing raw fact |
| X-07 | Day-only sale on day containing source-to-target change | Hold/unresolved unless approved day-level evidence proves attribution |
| X-08 | Mapping replay/backfill using same release | Stable IDs/assignments, no added entity/candidate fanout; original transaction grain retained |
| X-09 | Higher-quality contact/price unavailable, lower-quality source non-null | Missing/conflicting selected truth remains explicit; no consent/price/cost synthesis |
| X-10 | Bank/finance or stock discrepancy after identity matching | Identity link does not certify source reconciliation or fabricate sale cost/settlement/ledger |

Future verification must cover idempotent decision publication, interval/revision uniqueness, candidate/assignment separation, cluster vetoes, merge/split reversal, privacy propagation, report reproducibility and labelled false-match evaluation. Coverage includes source-quality slices and unresolved/anonymous counts; do not measure success only by how many pairs were linked.

## Remaining decisions before implementation

Confirm entity-kind classification and stewardship owners/authority, evidence freshness horizons, approved name/brand/UOM/category alias dictionaries, contact sharing/recycling rules and GTIN producer interpretation. Supply labelled match/nonmatch examples; any future auto-link threshold/precision target requires approval rather than this document inventing a measured accuracy.

Confirm source-instance registration and identity persistence under restore/rename, physical representation of logical crosswalk records in the existing stack, matching-run/release idempotency, date-only/DST precision policies, baseline/history coverage and report-restatement rules. Existing source contacts are not authenticated; customer confirmation may need additional authorized evidence before high-risk links.

Confirm privacy/evidence access/retention, merge/split review authority, category/variant/package interpretation and effective conversion factors. Supply manufacturer/supplier documentation where needed; SCC units_per_pack/catalog hints cannot alone verify packaging. Candidate review should not become permission to introduce sensitive identity fields absent from the source contracts.

## Existing documentation review

Read KAN-22, AGENTS.md, README.md, docs/architecture.md/problem-statement.md/decisions.md and relevant approved customer/product dictionaries, conventions, CDC/SCD, assumptions, historical/supplier-file and source-to-source mapping docs. Their source identities, duplicate/contact/unit limitations and immutable commercial snapshots constrain this strategy.

| Existing documentation | Consistency result | Required changes now |
| --- | --- | --- |
| Architecture/ADR-001..006, AGENTS.md | Existing data platforms/Phase 1 boundaries retained; no source consolidation into one database | None |
| RMRG customer/catalog/conventions/history | Customer numbers/SKUs local and immutable; contacts not identity keys; source snapshots not overwritten | None; approved modeling remains unchanged |
| SCC tables/conventions/mappings/history/files | Duplicate codes, loose references, anonymous accounts, mixed units and unreliable dates explicitly supported | None; files do not become source master tables |
| Existing source-model README/status wording | KAN-20/21 are user-approved; historical document proposal wording does not authorize refinement | No modeling/status edits in this ticket |
| Project README | Optional future navigation link, no phase completion/architecture change implied | No required correction |

All KAN-22 work stays under `docs/source-data-model/cross-company-mappings/`. No existing document requires correction because of these proposed mapping decisions. No DDL, matching code or runtime validation can prove match quality yet.

## Documentation validation performed

Read-only Python checks passed for six Markdown documents, six assignment statuses and six confidence classes, nine customer and seven product rules, 36 unique acceptance cases, required crosswalk/time/audit fields, explicitly cited source-field existence against both approved dictionaries, relative links/anchors, table widths/fences/whitespace, absence of DDL and feature-branch/directory-only change scope. Manual consistency review covered nine logical record structures, candidate-versus-assignment status, anonymous/shared-account treatment, whole-cluster vetoes, package/unit identity, survivor provenance, temporal cardinality and merge/split correction semantics. No approved source models or architecture files changed. The acceptance cases are reviewed specifications, not executable matching tests; no measured precision or runtime enforcement is claimed without matching code.
