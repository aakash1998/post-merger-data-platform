# Product candidate matching, packaging and crosswalks

## Source differences and identity grain

RMRG products.product_id is a stable sellable SKU/variant with unique SKU, optional unique current barcode, category_id into a hierarchy, structured style/size/color and each-only unit. SCC item_master.item_id is a stable record with potentially repeated/reused item_code/barcode, abbreviated item_description, raw brand_name/department labels and unit_code/units_per_pack that may describe CASE/KG/generic merchandise. SCC field/description ambiguity must not be interpreted as absence of variant/package differences.

Use [source-qualified keys](enterprise-keys-and-crosswalks.md); matching never writes SCC item IDs/codes into RMRG products or declares equal local codes a global SKU. Enterprise identity is one sellable variant **and selling package**, not a brand/category or generic description. Keep size/color/formulation/pack/unit evidence when available. An absent SCC size/color does not mean it agrees with every RMRG variant.

## Evidence preparation

- SKU/item codes: preserve raw values and source/date ownership; create versioned trim/case comparison views only for candidate search. Code equality across companies, even normalized, is weak evidence without an approved alias/owner relationship. Repeated codes in SCC need source PK and valid-period context.
- Barcodes: retain original string/symbology/type provenance. For declared GTIN candidates, accept only supported 8/12/13/14-digit representations with valid check digit and known producer interpretation; compare validated identifiers in a zero-padded 14-digit view while preserving original length/leading zeros. Do not strip a case indicator or check digit, repair a bad digit automatically, numeric-cast away zeros or expand UPC-E without a reviewed symbology-aware rule. Invalid/internal/variable-measure codes remain raw and do not enter the strong GTIN rule.
- GTIN normalization follows [GS1 leading-zero representation](https://ref.gs1.org/glossary/leading_zero_es) and [check-digit guidance](https://www.gs1.org/services/how-calculate-check-digit-manually). Syntactic check validity is not evidence that the retailer assigned the identifier correctly. Different package quantities/levels can require different identifiers; [GS1 pack/case rules](https://www.gs1.org/1/gtinrules/en/rule/270/packcase-quantity) support keeping package identity distinct.
- Descriptions/brands: case/Unicode/token normalization, reviewed abbreviation/brand alias dictionaries; extract size/color/pack/net-content/model only with recorded parse confidence. Do not remove all numeric tokens: “12”, “500”, size and model numbers may determine identity. A brand alias is evidence, not a guarantee two products match.
- Classification: RMRG category hierarchy and SCC flat department mappings use stewarded source-specific category correspondence; broad “APPAREL” similarity only supports a candidate. No department code is treated as RMRG category_id or an invented parent tree.
- Prices/costs: display as contextual review evidence only. Different source currencies, promotions, pack prices and last-cost versus standard-cost semantics prevent price equality/difference from proving/disproving identity. Do not derive historical sale cost from the chosen product master.

## Deterministic and fuzzy candidates

Initial cross-record linking is steward-approved for **all** rules. Confidence classes are defined in [crosswalks](enterprise-keys-and-crosswalks.md); hard variant/package conflicts override any ranking score. High requires a unique compatible enterprise candidate after checking source duplicates and entire cluster consistency.

| Rule ID | Candidate evidence | Initial confidence / action |
| --- | --- | --- |
| P-D01 | Exact validated GTIN, matching package/unit, compatible known brand/variant, no competing duplicates or reuse conflicts | High review candidate; checksum/equality alone is not sufficient; missing variant/package evidence lowers confidence |
| P-D02 | Existing stewarded source alias/manufacturer relation, exact compatible model/variant/brand and same selling package | High if owner/effective-period evidence is complete; source schemas lack a manufacturer-ID field, so external confirmation must be cited rather than invented |
| P-D03 | Exact normalized description + reviewed brand + compatible variant/package + compatible category evidence, no usable GTIN | Medium review; retail labels may describe many models with same words |
| P-D04 | Equal SKU/item-code string across sources | Low/insufficient alone; propose only with independent corroboration; never auto-link |
| P-D05 | Approved existing assignment for exact source identity/period | Reuse decision; material unit/variant/reuse conflict triggers review, not silent reassignment |
| P-F01 | Token/edit description similarity + compatible brand/category and available variant evidence | Medium/low review candidate; no fuzzy-only approval or suppression of conflicting numeric/variant tokens |
| P-F02 | Abbreviated generic description with same department or similar price | Low/insufficient; missing brand/variant/unit prevents exact identity assertion |

Candidate blocking uses valid GTIN, approved aliases, or brand/model/variant + category/token blocks; collect alternatives across blocks. Raw department or code-only blocks can be used for exploration but do not establish equivalence. Oversized generic-brand/category blocks are review work, not proof of no match. No algorithm/library or numerical auto-match threshold is selected. Future automation requires labelled exact/different-variant/pack/reused-code cases and measured precision; it is disabled in this proposal.

Duplicate/reused SCC barcodes, conflicting brand/size/color/net-content/package, generic assorted-item codes, untrusted pack factors, known internal barcode scopes, missing temporality and competing candidates all require review. A current RMRG unique barcode does not resolve historical SCC duplicates or barcode misuse. Retired products remain candidates for temporally appropriate history; do not select only the newest active record.

## Packaging and UOM relation contract

EA/EACH can be aliases only after confirming they mean the same source selling unit. CASE is not an alias for EACH. Positive SCC units_per_pack is a hint until supported by a reviewed supplier/package definition and applicable dates. KG cannot be converted into each from a generic average or price ratio. Conversions never change an enterprise identity grain or mutate source unit/quantity.

`product_relation` links distinct approved enterprise products, with relation_type `contains` or `equivalent_measure`, source/target product IDs, source/target units, positive exact decimal/rational factor, applicable variant/package definition, effective/recorded intervals, rule/decision IDs, approver, evidence and factor precision. `contains` means one specified source package contains a documented count of target selling units. `equivalent_measure` applies only when the same physical definition and dimensional conversion are evidenced; not an unsupported KG-to-piece bridge. Separate this from source_assignment, which always expresses identity rather than a conversion.

| Example | Enterprise identity decision | Quantity / money treatment |
| --- | --- | --- |
| SCC EA, same GTIN/variant/package as RMRG each | May approve same enterprise_product_id after review | Units equivalent only under approved EA=each alias; original money unchanged |
| SCC CASE of 12 verified RMRG sellable units | Distinct case enterprise product; approved contains relation to each | Derived each-equivalent quantity = cases * 12 with relation ID/version; never multiply transaction revenue by 12 |
| SCC 2.500 KG, RMRG integer each | No exact identity or conversion based on unit alone | Retain KG metric; converted each unresolved unless specific reviewed physical correspondence is truly supported |
| Missing/zero/negative/conflicting units_per_pack | Candidate/assignment held if packaging identity is unclear | No guessed factor or integer rounding; money can remain source-qualified without consolidated unit count |
| Pack changed from 6 to 12 under one SCC item_id/code | New effective-period product assignment if product definition changed, plus relations as reviewed | Preserve original item key and dated conversion; prior quantities keep old pack meaning |

For product relation graphs, require no cycles in contains hierarchy, no multiple conflicting applicable factors for a source/target/unit/period, compatible physical dimension and no contradictory paths. Missing conversion is not zero quantity. Fractional CASE quantities are reviewed; each-equivalent may be fractional and cannot be rounded to satisfy RMRG source integer constraints. Canonical analytics can preserve exact decimals without changing either operational model.

## Crosswalk, duplicates and unresolved products

One source item maps to at most one enterprise product at a valid/knowledge instant. Many reviewed duplicate item/SKU records can map to the same exact product; retain all source IDs, statuses and transaction facts. Whole-cluster consistency and cannot-link rules prohibit merging distinct variants through a generic bridge. Source code aliases are versioned lookups and can point to multiple competing owners; code-only archive references stay unresolved when time/owner cannot be proved.

An unambiguous distinct sellable item can get a reviewed singleton entity even if only one company sells it. Missing variant/pack facts or generic “ASSORTED GOODS” records remain unmapped/review_required or excluded with GENERIC_NONIDENTITY reason; do not coalesce every generic code into one counted product. An excluded generic item can still contribute a separately labelled unattributed sales measure. Rejection of one product pair does not exclude the source item from every other possible match.

Canonical attribute selections favor steward-confirmed definitions, then fit-for-purpose documented evidence; RMRG structured variant/name/category is a display fallback when compatible, not unconditional truth. Store all source SKUs/item codes/barcodes as aliases, never replace them with one winning SKU. Brand/category conflicts remain visible; SCC flat departments retain their own source label and reviewed enterprise category correspondence. Source prices/costs/currency remain source-specific offers/valuation observations, not a blended enterprise selling price or invented historical cost.

Substantive variant/package redefinition is identity change or an effective assignment change requiring review; name/brand/category corrections and policy changes can be dimension SCD1/SCD2 without changing enterprise ID when physical identity is unchanged. New evidence must not silently turn yesterday's exact product link into today's case conversion.
