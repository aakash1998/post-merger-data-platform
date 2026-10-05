# Customers and catalog

All tables include the [five common audit columns and global constraints](conventions.md). `PK` and `FK` below are constraints, not merely documentation hints. All four tables participate in full-load + I/U/D CDC.

## customers

Grain: one registered person/account; guest buyers have no synthetic shared customer row.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| customer_id | bigint | No | PK |
| customer_number | varchar(30) | No | Unique stable business identifier |
| first_name | varchar(100) | No | Given name; anonymization may replace with approved nonblank marker |
| last_name | varchar(100) | No | Family name; same privacy policy |
| email | varchar(254) | Yes | Current contact; not unique, shared household emails allowed |
| phone | varchar(25) | Yes | Current phone |
| preferred_language | varchar(10) | No | `en-CA`, `fr-CA`, `en-US`; default `en-CA` |
| loyalty_tier | varchar(20) | No | `none`, `silver`, `gold`, `platinum`; default `none` |
| lifecycle_status | varchar(20) | No | `active`, `inactive`, `anonymized` |
| marketing_opt_in | boolean | No | Default false; consent evidence is outside this source-model scope |
| registered_at | timestamp with time zone | No | Business registration instant, possibly earlier than created_at for imported customers |
| anonymized_at | timestamp with time zone | Yes | Required exactly when lifecycle_status is anonymized |
| archived_at | timestamp with time zone | Yes | Retirement timestamp; does not remove identity/history |

Constraints: nonblank names/number; anonymized customers have null email/phone and marketing_opt_in false; anonymized_at >= registered_at when present; archived_at >= registered_at. Identity survives anonymization. No cross-company/global customer key is assumed.

Indexes: unique(customer_number); nonunique expression index on lower(email) where email is not null; (lifecycle_status, customer_id). FKs: none. Email lookup retrieves candidates, not automatic customer merging.

## customer_addresses

Grain: one mutable saved address owned by a customer. A customer can have multiple addresses and separate defaults for billing/shipping; one address can serve both roles.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| customer_address_id | bigint | No | PK |
| customer_id | bigint | No | FK -> customers.customer_id |
| address_label | varchar(50) | Yes | e.g. Home, Office |
| recipient_name | varchar(200) | No | Recipient |
| address_line1 | varchar(200) | No | Street/PO box |
| address_line2 | varchar(200) | Yes | Unit/additional line |
| city | varchar(100) | No | Locality |
| region | varchar(100) | Yes | Province/state; country-aware requirement in application |
| postal_code | varchar(20) | Yes | Required by application for countries using postal codes |
| country_code | char(2) | No | Country |
| phone | varchar(25) | Yes | Delivery contact |
| is_default_shipping | boolean | No | Default false |
| is_default_billing | boolean | No | Default false |
| archived_at | timestamp with time zone | Yes | Retired saved address |

Constraints: archived address cannot be default; archived_at >= created_at. Unique(customer_address_id, customer_id) is available for composite provenance ownership checks. Application replaces defaults atomically and validates delivery/serviceability; no uniqueness on street text.

Indexes: (customer_id, archived_at); partial unique(customer_id) where is_default_shipping and archived_at is null; equivalent partial unique for is_default_billing. Order snapshots retain saved-address provenance but must not change when this row changes.

## product_categories

Grain: one category node in an adjacency-list hierarchy.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| category_id | bigint | No | PK |
| category_code | varchar(30) | No | Unique business code |
| parent_category_id | bigint | Yes | Self FK -> product_categories.category_id; null for root |
| category_name | varchar(150) | No | Display name |
| description | varchar(1000) | Yes | Description |
| sort_order | integer | No | >= 0; default 0 |
| is_active | boolean | No | Default true |
| archived_at | timestamp with time zone | Yes | Retirement instant |

Constraints: parent_category_id differs from category_id; archived rows are inactive; archived_at >= created_at. Longer cycles are rejected transactionally when assigning/reparenting; serialize hierarchy changes so concurrent edits cannot introduce cycles. Category names need not be globally unique. Products may remain attached to retired categories for history; new sales assignments require active categories.

Indexes: unique(category_code); (parent_category_id, sort_order, category_id). FK deletion is restricted, including children and products.

## products

Grain: one sellable SKU/variant. Size/color variants each receive their own product_id and SKU; a style_code optionally groups variants.

| Column | PostgreSQL type | Nullable | Meaning / constraint |
| --- | --- | --- | --- |
| product_id | bigint | No | PK |
| sku | varchar(50) | No | Unique stable SKU |
| category_id | bigint | No | FK -> product_categories.category_id; exactly one primary category |
| product_name | varchar(200) | No | Current name |
| description | varchar(2000) | Yes | Current description |
| brand | varchar(100) | Yes | Brand label |
| style_code | varchar(50) | Yes | Optional variant grouping; not unique |
| size_label | varchar(30) | Yes | Variant attribute |
| color_name | varchar(50) | Yes | Variant attribute |
| barcode | varchar(50) | Yes | Unique when non-null; optional GTIN/string, preserving leading zeros |
| unit_of_measure | varchar(10) | No | `each` only in Phase 1 |
| list_price | numeric(18,2) | No | >= 0; current reference price, not sale history |
| standard_cost | numeric(18,2) | Yes | >= 0 when known; null means unknown, not zero |
| currency_code | char(3) | No | Currency for list_price and standard_cost |
| weight_kg | numeric(10,3) | Yes | > 0 when provided |
| lifecycle_status | varchar(20) | No | `draft`, `active`, `discontinued` |
| launched_at | timestamp with time zone | Yes | Business availability instant |
| discontinued_at | timestamp with time zone | Yes | Required exactly for discontinued state |

Constraints: active products require launched_at; discontinued_at >= launched_at when both present; no obligation that sale price exceeds cost. Barcode uniqueness only for present values; blank barcodes are rejected. Activation and new order acceptance require an active primary category (transactional rule).

Indexes: unique(sku); unique(barcode) where barcode is not null; (category_id, lifecycle_status); (style_code) where style_code is not null. Product IDs/SKUs remain referenced after discontinuation. Current catalog pricing is one currency per SKU; CAD/USD sale prices are independently snapshotted on order lines, not computed from an implicit exchange rate.
