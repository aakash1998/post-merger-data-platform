# Customer candidate matching and survivorship

## Source evidence and eligibility

RMRG supplies customers.first_name/last_name/email/phone/lifecycle_status and separate saved customer_addresses with country/region/postal code and default roles. SCC supplies one raw customer_name, email_address/phone_number, mutable address_text/city/province/postal_code/country, customer_type/group/active_flag. Neither contract provides verified-contact flags, birth dates, government IDs or a shared loyalty/account identifier. Do not invent those fields or claim source email/phone ownership is authenticated.

Every source account keeps its [source-qualified identity](enterprise-keys-and-crosswalks.md). First classify it as person, organization, household_account, anonymous/shared, or unresolved. SCC name alone cannot decide person versus organization. Classification uncertainty goes to review and blocks cross-kind links. Anonymized records, privacy placeholders and approved anonymous/shared-account records are excluded from new contact/name matching; existing legitimate attribution follows privacy/retention policy without revealing erased values.

Anonymous/WALKIN classification uses a versioned, source-specific approved account-ID/code/type list plus owner evidence. Case/space-normalized WALKIN, CASH CUSTOMER or similar text is a **classification candidate**, not enough by itself to exclude a genuine person called “Walkin.” Review exact source IDs before publishing exclusion; confidently known shared cards are excluded even if stale contact data is present. Blank identity fields are insufficient evidence, not automatic proof of anonymity.

## Normalized candidate evidence

Keep raw values and source versions; all derivations carry normalization_version, parse-confidence and observed interval. Failed parses are null derived evidence with a quality reason, never fabricated data.

| Evidence | Candidate preparation | Risk / limit |
| --- | --- | --- |
| Name | Unicode-normalized case-folded/tokenized comparison; preserve raw spelling, diacritics and meaningful tokens; trim/collapse whitespace | SCC full name may be organization/household; do not split blindly into first/last; initials/nicknames need explicit reviewed rules |
| Email | Trim; case-fold domain; exact stored-local-part comparison first; lowercased-local-part view only as a separately labelled weaker candidate | No provider-specific dot/plus stripping; no “same mailbox” guarantee; source RMRG already lowercases, so original mailbox case evidence may be lost |
| Phone | Parse with known country evidence, explicit country code and separate extension; reject impossible/incomplete local numbers | Shared household/business phones and recycled numbers; missing country does not justify choosing a country silently |
| Address | Country-aware parsing of street/building/unit/city/region/postal code; source-approved abbreviations; retain unit and postal detail | One building/postal code is not one household/person; SCC embedded unit parsing may be uncertain |
| Account codes | Keep as source-local aliases with observed/effective intervals | customer_number and customer_code have unrelated namespaces; equality never proves cross-company identity |
| Time/source quality | Compare contemporaneous usable observations and approved freshness horizon | RMRG updated_at records any row edit, not contact verification; SCC updated_at can be stale; current address cannot prove a historical match |

RMRG multiple saved addresses attach only through customer_addresses.customer_id. Compare eligible nonarchived addresses at their observed period; do not let an order delivery recipient or third-party address become the purchasing person's identity. Default role is relevance evidence, not residency verification.

## Deterministic candidates — equality is not confirmation

Each rule proposes a pair, gathers all alternative candidates and applies eligibility/veto checks. A high label requires exactly one compatible candidate enterprise cluster at that evaluation scope, not merely the first pair found. Missing corroboration demotes to medium/low or insufficient. No cross-record customer mapping is automatically approved in the initial policy.

| Rule ID | Candidate evidence | Initial confidence / handling |
| --- | --- | --- |
| C-D01 | Exact usable email + parsed phone + compatible full personal name, contemporaneous and not shared/suppressed | High candidate for steward review; neither contact alone is verified, and shared-contact checks still apply |
| C-D02 | Exact usable email + compatible full personal name + exact parsed street/unit/postal/country | High if all evidence is reliable and unique; otherwise medium, especially multiple family members |
| C-D03 | Exact parsed phone + compatible full personal name + exact parsed address including unit | High if not shared/recycled and unique; otherwise medium; business switchboards are not person evidence |
| C-D04 | Exact full name + address including unit, no usable independent contact | Medium review candidate; common names/co-residence remain plausible false matches |
| C-D05 | Exact email or phone alone; exact name alone; equality of cross-company account codes | Low candidate evidence for contact/name only; code equality alone is insufficient and is not a link rule |
| C-D06 | Previously approved link for the exact source identity and valid interval | Reuse approved decision unless material new conflict/privacy/repurposing triggers a hold; replay does not rematch/create a key |

Candidate generation blocks on exact valid email, exact parsed phone, or parsed postal/street plus name tokens. Collect the union of blocks, not just a single email result. Block membership is not positive evidence by itself; correlated spelling tokens do not count as independent corroboration. Store unavailable/rejected block reasons and candidate-count evidence. Very common contacts/address/name blocks require review and bounded evaluation; skipped oversized blocks remain unresolved and measurable, never treated as “no match.”

## Fuzzy candidates

Fuzzy evidence ranks review candidates; **fuzzy-only evidence never publishes a link**. Proposed comparisons include token overlap/edit similarity on names and parsed street/city, reviewed nickname/abbreviation dictionaries and diacritic-tolerant secondary views. No matching library or model is selected or implemented.

- C-F01: minor name spelling difference with exact usable phone/email and compatible address. Medium until reviewed, high only if genuinely independent strong corroboration and unique eligibility are demonstrated; retain which name tokens disagree.
- C-F02: compatible full name plus close street spelling and exact unit/postal/country, with some corroborating contact evidence. Medium review; unit number mismatch or unknown parsing is never hidden by a high aggregate similarity.
- C-F03: reordered/abbreviated SCC name compared with RMRG full name using exact contact as supporting evidence. Medium/low; initials can represent a different family member or organization.
- Name/address similarity without reliable contact, especially common surnames or a shared building, is low/insufficient. Transliteration or phonetic similarity alone is never identity proof. A broad fallback review block can use postal region + name tokens, but there is no unbounded cross join or assumption that blocked-out pairs are different people.

Any optional numeric ranking score has a versioned definition and missing-data handling; correlated name variants cannot stack into fake confidence. This proposal intentionally sets no numerical auto-match threshold or calibrated probability. Before future automation, evaluate labelled same/different-party pairs, precision/false-match rates, common-name/shared-contact slices, ambiguity gaps and drift; approve a rule/version-specific policy. Initial steward-only linking is concrete policy, not a claim automation has been tested.

## Duplicate handling, vetoes and manual review

Match within each source as well as across sources; SCC duplicates and RMRG duplicate-person accounts can each be distinct source records. Approved duplicate-person accounts can share an enterprise person key while keeping account-level revenue/loyalty/status evidence separate. Do not delete records, rewrite their primary keys or collapse their transactions. Exact repeated CDC delivery is separate from genuine duplicate source accounts.

Review all candidate cluster members before approving a union. A matches B and B matches C does not justify A = C if A/C conflict. A reviewed cannot_link on any member pair blocks the whole cluster merge. Cyclic link graphs do not override negative decisions. One source identity has one enterprise target per valid/knowledge instant.

Hard holds or review cases include person/organization/household-kind mismatch; meaningful conflicting names despite shared contacts; two competing candidates with comparable evidence; shared email/phone or multiple family members at one address; recycled contact timelines; SCC code reuse with no historical owner; unexplained existing-target changes; generic/anonymized placeholders; contradictory order ID/code references; absent country/unit/address parse evidence; and source deletion/repurposing. Different current addresses alone are not a hard identity veto because people move; incompatible dates/contact/person evidence must be assessed together. Never merge solely to reduce duplicate counts.

## Anonymous and guest facts

RMRG orders.customer_id null stays an anonymous/guest fact, even when contact_email/contact_phone is present. That snapshot may be a delivery contact and lacks a stable master relationship. No automatic person identity is created from guest order contact fields. SCC approved shared WALKIN master rows get mapping_status excluded with ANONYMOUS_SHARED_ACCOUNT reason; their source account IDs/codes remain on facts but enterprise_customer_id is null.

Anonymous reporting uses source-qualified transaction counts and a reporting classification; it contributes zero identified-person keys. It must not map all WALKIN/guest sales to one counted enterprise customer. An unresolved known account is “unresolved,” not anonymous. Later customer registration does not retroactively identify past guest purchases without an explicitly reviewed transaction-attribution contract, outside the default master crosswalk. If a shared account is later repurposed to an identified account under the same PK, use reviewed effective intervals and keep earlier anonymous sales excluded.

## Attribute survivorship

Identity approval selects membership; it does not authorize taking every field from a winning row. Attribute selection has its own decision/source-version provenance, missingness, business validity and quality history. Precedence: approved steward correction -> demonstrably validated/fit-for-purpose value -> temporally appropriate source evidence -> source-specific display fallback. RMRG's structured fields are a fallback preference for display, not proof of accuracy. If two credible values conflict, retain both and a conflict flag; withhold an asserted single truth unless the attribute rule resolves it.

| Attribute | Survivorship rule |
| --- | --- |
| Name/party kind | Retain verified/reviewed kind; person display uses appropriate structured RMRG name when no better correction exists; SCC trade names remain organization/account names |
| Email/phone | Source contacts remain a set with source/period/usability; a selected display/preferred contact needs evidence, no globally verified flag inferred from formatting/row timestamp |
| Address | Keep distinct source address roles/periods; RMRG structured saved address can aid display; SCC current address does not rewrite order snapshots or historic residence |
| Loyalty/group | RMRG loyalty_tier and SCC customer_group are source-specific attributes, not interchangeable enterprise tiers |
| Active/archived state | Keep per-account lifecycle; SCC inactive does not deactivate an active RMRG account or delete the enterprise person |
| Consent | Do not transfer RMRG marketing_opt_in or assume SCC active_flag is consent; consent remains purpose/source-specific with missing SCC evidence explicitly unknown |
| Credit limit | SCC credit_limit is account-specific; never apply to an RMRG account or sum into a personal enterprise credit authorization |

Missing/blank/placeholder values cannot overwrite useful selected values unless an authorized privacy erasure or explicit meaningful-null correction requires it. Privacy erasure can override ordinary survivorship across approved identity-linked copies, with retained non-PII decision lineage. Do not expose PII in Jira/log evidence or add retention claims beyond approved policy.
