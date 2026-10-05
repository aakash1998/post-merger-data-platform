# Assumptions, decisions, and review

## Local proposed design decisions

These are source-model proposals for review, not approved architecture ADRs.

1. **Mature omnichannel retail:** physical stores, web, mobile, and call-center orders; guest and registered buyers; ship-from-store, warehouse shipping, pickup, carryout, mixed orders, split shipments/tenders and partial returns.
2. **Stable local identity:** bigint PKs and independent business codes. PostgreSQL schemas/keys stay local to Rocky Mountain. No global customer/product ID or Stampede schema is invented. Shared email/phone does not establish identity.
3. **Catalog:** each SKU is a sellable whole-unit variant in one primary category. Categories are a tree/forest. Bundles, multiple category assignment, weighted goods, serial/lot/expiry tracking, marketplace sellers and supplier/purchase-order tables are outside this task.
4. **Geography/currency:** Canadian/US retail is the initial operating scenario; CAD/USD orders, two-decimal minor units, IANA timezones, country-aware addresses. Current product reference price/cost is single currency per SKU; actual order price/cost may be in the other supported currency through an explicit price decision, not implicit FX. Missing cost remains null.
5. **Money:** prices exclude tax; one combined effective merchandise tax rate per line. Discounts, including order promotions, are allocated to lines at placement. Shipping and shipping tax remain separate header components. Tax jurisdiction breakdown, compound taxes, tax engine integration, promotion definitions, general ledger, and FX history are out of scope.
6. **Sale history:** one shipping and one billing snapshot per order; amendments allowed before handover with source audit evidence. No multiple delivery destinations in one order. Guest carryout can be anonymous. Successful sale documents remain linked to original SKUs/customers after retirement; no automatic cascading deletion.
7. **Inventory:** nonnegative whole-unit balances, aggregate reservations and unavailable stock. Ledger and balances commit together. Transfers are atomic paired legs; no in-transit facility or reservation allocation table. This cannot fully reconstruct per-order reservation lineage, so later expansion may be required before long-running distributed reservation workflows. Available stock never includes inspection stock.
8. **Fulfillment:** shipment represents shipping or store handover. Physical stock decreases at carrier/customer handover, not payment authorization or order placement. No carrier exception/loss workflow, multi-package tracking inside one consignment, replacement fulfillment against an already fulfilled line, or supplier drop shipping. Each independently tracked package is a consignment.
9. **Returns:** returns identify fulfilled allocations; no unreceipted/receiptless returns. Return locations can differ from original fulfillment; exactly one intended receiving store/warehouse is mandatory from RMA creation, including rejected/cancelled records. Quantities received/inspected and entitlement are separate from successful refund operations. Exchanges are a return plus a new order. Partial receipt event detail exists in stock legs, while the RMA line stores cumulative quantities and latest receipt instant.
10. **Payments:** operation rows support card/cash/gift-card/wallet tender, authorization, direct/linked capture, void and refund. No card/bank secrets, gateway payloads, token vault design, provider-specific state machines, chargebacks, gift-card liability ledger, or bank settlement reconciliation. Capture/refund allocations preserve line and shipping-component attribution; merchandise-return refunds additionally identify each return item, with per-item limits across captures. Pending operations block capacity until terminal resolution; timeout/reconciliation policy must be agreed before implementing payment logic.
11. **Lifecycle/privacy:** retirement preserves referential history; privacy erasure is an approved workflow that can scrub PII snapshots/history, not a cascade. Retention periods, consent evidence, actor access and anonymization markers need business/security approval. This design does not claim regulatory compliance.
12. **CDC and downstream analytics:** all 17 source tables participate in CDC; SCD Type 1/2 applies only to downstream analytical attributes, not operational source tables. Capture ordering, baseline boundaries, retention, deletion payloads, business-effective change classification, and schema evolution must be agreed separately before ingestion starts.

## Transactional reconciliation and state transitions

Each lifecycle has a forward path; milestone timestamps cannot be silently cleared or moved backward after settlement. Defaults for new rows are draft/open/planned/requested/pending as appropriate; application commands explicitly advance state with business timestamps. Terminal transitions reject later business-field edits except separately approved privacy/administrative correction workflows.

- Order: draft -> placed -> processing -> partially_fulfilled -> fulfilled -> closed; placed/processing -> cancelled only with zero handed-over units. Fully fulfilled orders may skip intermediate statuses; closing requires fulfillment/cancellation settlement, no pending payment operations, and completed current return workflows. Later valid returns may be opened against a closed sale without rewriting its sale history.
- Line: open -> partially_fulfilled -> fulfilled -> closed, or wholly cancelled. Cumulative fulfillment and cancellation determine state. Header totals remain original accepted values. Remaining payable after cancellations uses original line net/tax amounts proportionally, with the final cancelled unit taking cent residual; shipping cancellations require explicit agreed fee-refund policy.
- Shipment: planned -> allocated -> ready -> handed_over -> delivered; cancellation only before handover. Pickup/carryout goes from ready directly to delivered while recording handover. No shipment allocation is edited after handover.
- Return: requested -> authorized -> partially_received -> received -> closed, with early rejected/cancelled paths; skipping partial_received is valid for one complete receipt. Partially_received means some authorized units remain outstanding across all lines; received means all authorized units received. Final line dispositions and linked successful refunds settle closure.
- Payment: pending -> succeeded or failed only. A new request is needed for a retry after failure. Any pending-provider ambiguity is resolved/reconciled before releasing reserved refund/capture capacity.

Additional monetary checks: combined pending/successful refunds cannot exceed captured funds or approved entitlement. Refunds linked to one RMA cannot exceed its refund_total or component/line entitlement. [Payment allocations](orders-and-payments.md#payment_allocations) identify the original line or shipping component for every capture/refund and the exact return item for RMA merchandise/tax refunds; cancellation and return commands consume the same component limits under order/capture locks. Partial cancellation after capture requires attributed refunds; new capture requests respect the revised payable amount. A wholly cancelled order sets all line quantities to cancelled and has no handed-over units. No successful transaction row is rewritten to hide cancellation/refund history.

## Checks required when this proposal becomes executable

These are future meaningful acceptance tests, not tests or pipelines delivered in this documentation-only task.

| Scenario | Expected invariant |
| --- | --- |
| Registered and guest orders | Guest has null customer FK; shared emails do not merge registered identities |
| Saved address/default edit | At most one active default per role; existing order snapshots unchanged |
| Wrong customer/order address | Composite provenance FK rejects foreign ownership |
| Category reparent/cycle | Self and multilevel/concurrent cycles rejected; history retained downstream |
| SKU retirement or store closure | New allocations rejected; historical references remain resolvable |
| Store/warehouse location pairs | Inventory, shipments and returns reject both-null/both-populated location pairs in every state; inventory has one row per SKU/location and retains zero balances |
| Commercial snapshot changes | After placement, reject edits to accepted quantities/prices/discounts/taxes/cost snapshots and order currency; catalog edits leave sale history unchanged |
| Receiving/damage/cycle counts | Receipt, quarantine/disposal and count variance reconcile all balance components; zero variance creates no zero-delta leg; optional source FKs match product/location |
| Concurrent reserve/handover | Availability never negative; stock ledger and balance agree after retries |
| Paired transfer/reversal | Same product/units, different locations; both legs atomic; no partial reversal |
| Split shipments/pickup/carryout | Same-order line FKs; no overallocation; handover consumes stock once |
| Cross-order or unfulfilled return | Ownership FKs reject mismatches; authorization checks reject unfulfilled units |
| Partial/damaged return | Receipt ledger, unavailable stock, restock/disposal quantities reconcile |
| Partial refunds and cent residuals | Exact return-item attribution; reject mismatched RMA/order/line, missing item references and per-item overrefunds across captures; preserve original price/tax limits |
| Payment return reference | Authorization/capture/void reject return_id; refund may omit it for cancellation/shipping adjustments; RMA line refunds require exact return-item ownership |
| Concurrent capture/refund/void | Parent locks and pending capacity prevent financial overcommit |
| Duplicate order/payment/movement callback | Unique retry keys produce one business effect |
| Late movement/backdated return | Business instant preserved, commit order governs current-state application |
| CDC update/delete/replay | Keyed changes converge; delete with key-only image works; parent arrival can lag |
| Baseline/schema change | Existing rows reconcile; consumers tolerate approved additive changes |
| Privacy/anonymization | Current and historical PII copies follow approved erasure/retention contract |

## Existing-document review before completion

Read AGENTS.md, README.md, docs/architecture.md, docs/architecture/architecture-diagram.md, docs/problem-statement.md, docs/decisions.md, and the component README files. Existing component directories describe planned implementation rather than approved source contracts.

| Existing document | Decision review | Update needed now? |
| --- | --- | --- |
| AGENTS.md | Proposal stays in Phase 1; no ingestion or new technology | No |
| README.md | Model is proposed; it does not complete all Phase 1 approvals | No phase/status change; an optional discovery link can be added later |
| docs/architecture.md and diagram | PostgreSQL/Aiven, DMS/S3, medallion, Snowflake/dbt and Airflow responsibilities unchanged | No |
| docs/problem-statement.md | Customer/sales/inventory/finance/operations goals remain unchanged | No |
| docs/decisions.md | ADR-001..006 remain valid; local schema decisions do not alter architecture | No replacement/amendment; record approved source-model decisions later if desired |
| source-simulator/README.md | Generator still waits for approved contracts | No |
| Other component README files | No implementation or platform responsibility changes | No |

No existing documentation requires correction because of this proposal. All files created/edited for this task remain under `docs/source-data-model/rocky-mountain-retail-group/`, as requested. Approval of this model does not approve the other company's schema, the CDC payload/file/event contracts, or ingestion implementation.

## Validation for this documentation review

Documentation-only validation checks the 17-table inventory, column-table formatting, relative links/anchors, CDC and downstream SCD coverage, and absence of DDL. The review scenarios above are future implementation acceptance requirements; no database or integration tests establish enforcement yet.
