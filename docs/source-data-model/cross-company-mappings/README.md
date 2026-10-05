# Cross-company customer and product mapping strategy

KAN-22: **proposed Phase 1 mapping contract for review**. Builds on the approved [Rocky Mountain model](../rocky-mountain-retail-group/README.md) (KAN-20) and [Stampede model](../stampede-city-commerce/README.md) (KAN-21). Describes analytical identity resolution; no DDL, matching code, pipelines, new platform or architecture change.

KAN-22's Jira description also mentions stores/channels and other shared entities. This task's explicit scope is customers and products; location/channel vocabulary and other entity crosswalks remain future work. Geography/category labels can be evidence here without defining enterprise store/channel models.

## Reading order

1. [Enterprise keys and crosswalks](enterprise-keys-and-crosswalks.md): canonical grains, immutable source identities, logical structures, status/confidence and join invariants.
2. [Customer matching](customer-matching.md): deterministic/fuzzy candidates, shared/anonymous accounts, duplicates and attribute survivorship.
3. [Product matching](product-matching.md): codes, barcodes, variants, packaging/UOM, ambiguous products and canonical attribute rules.
4. [Stewardship and history](stewardship-and-history.md): approvals, cannot-link decisions, effective dates, merge/split reversals, audits and fact attribution.
5. [Acceptance and review](acceptance-and-review.md): examples, future tests, assumptions, unresolved decisions and documentation validation.

## Decisions at a glance

| Concern | Proposed policy |
| --- | --- |
| Source identity | Registered source system/instance/namespace/entity plus exact typed PK; never replace a source ID with an enterprise ID |
| Enterprise customer grain | One identified party of an explicit kind: person, organization or household/account; kinds do not auto-merge |
| Enterprise product grain | One sellable variant at a specific selling-package/unit definition; each and case are related products, not interchangeable identities |
| New keys | Opaque persistent UUID identifiers, customer and product namespaces distinct; no name/email/SKU/barcode-derived key |
| Matching | Deterministic/fuzzy rules propose candidates; initial release requires steward approval for every cross-record link |
| Confidence | confirmed/high/medium/low/insufficient/contradictory are evidence classes, not statistical probabilities or permission to publish |
| Unmatched | No guessed link; source-qualified facts remain available and unresolved target stays null; reviewed distinct parties/products may get singleton enterprise entities |
| Anonymous | RMRG guest sales and SCC WALKIN/shared anonymous accounts have no person enterprise key; anonymous reporting class is not one customer |
| Pack conversion | Versioned, approved related-product/UOM relation; never round KG/CASE into RMRG each or multiply money by unit factor |
| History | Business-valid and decision-recorded intervals; old decisions remain reconstructable, corrections append replacements |
| Survivorship | Attribute-level quality/evidence/time rules, not whole-row “RMRG wins”; source contact/consent/prices remain separately attributable |
| Implementation boundary | Existing Databricks/Delta and Snowflake/dbt responsibilities apply; no new master-data service or source-table changes |

The mapping improves attribution, not source truth. It does not remove duplicate transaction records, grant marketing consent, prove historical addresses, establish original sale cost, or resolve a receipt using an ambiguous customer/item code. Crosswalk membership and dimension SCD history are separate contracts.
