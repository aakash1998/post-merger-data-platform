"""Fail closed on structural contracts and mature-source reconciliations."""

from collections import defaultdict
from typing import Any

from .contracts import Row, SCHEMA, ZERO, money, validate_row
from .generator import Bundle

# Child columns, parent table, parent columns. Logical SCC references are excluded.
FKS: dict[str, dict[str, list[tuple[tuple[str, ...], str, tuple[str, ...]]]]] = {
    "rmrg": {
        "customer_addresses": [(("customer_id",), "customers", ("customer_id",))],
        "product_categories": [
            (("parent_category_id",), "product_categories", ("category_id",))
        ],
        "products": [(("category_id",), "product_categories", ("category_id",))],
        "inventory": [
            (("product_id",), "products", ("product_id",)),
            (("store_id",), "stores", ("store_id",)),
            (("warehouse_id",), "warehouses", ("warehouse_id",)),
        ],
        "stock_movements": [
            (("inventory_id",), "inventory", ("inventory_id",)),
            (("shipment_item_id",), "shipment_items", ("shipment_item_id",)),
            (("return_item_id",), "return_items", ("return_item_id",)),
            (("reverses_movement_id",), "stock_movements", ("stock_movement_id",)),
        ],
        "orders": [
            (("customer_id",), "customers", ("customer_id",)),
            (("origin_store_id",), "stores", ("store_id",)),
        ],
        "order_addresses": [
            (("order_id",), "orders", ("order_id",)),
            (("order_id", "source_customer_id"), "orders", ("order_id", "customer_id")),
            (
                ("source_customer_address_id", "source_customer_id"),
                "customer_addresses",
                ("customer_address_id", "customer_id"),
            ),
        ],
        "order_items": [
            (("order_id",), "orders", ("order_id",)),
            (("product_id",), "products", ("product_id",)),
            (("requested_pickup_store_id",), "stores", ("store_id",)),
        ],
        "payments": [
            (("order_id",), "orders", ("order_id",)),
            (("parent_payment_id", "order_id"), "payments", ("payment_id", "order_id")),
            (("return_id", "order_id"), "returns", ("return_id", "order_id")),
        ],
        "payment_allocations": [
            (("payment_id", "order_id"), "payments", ("payment_id", "order_id")),
            (
                ("order_item_id", "order_id"),
                "order_items",
                ("order_item_id", "order_id"),
            ),
            (
                ("return_item_id", "return_id", "order_item_id", "order_id"),
                "return_items",
                ("return_item_id", "return_id", "order_item_id", "order_id"),
            ),
        ],
        "shipments": [
            (("order_id",), "orders", ("order_id",)),
            (("origin_store_id",), "stores", ("store_id",)),
            (("origin_warehouse_id",), "warehouses", ("warehouse_id",)),
            (
                ("shipping_address_id", "order_id", "shipping_address_role"),
                "order_addresses",
                ("order_address_id", "order_id", "address_role"),
            ),
        ],
        "shipment_items": [
            (("shipment_id", "order_id"), "shipments", ("shipment_id", "order_id")),
            (
                ("order_item_id", "order_id"),
                "order_items",
                ("order_item_id", "order_id"),
            ),
        ],
        "returns": [
            (("order_id",), "orders", ("order_id",)),
            (("receiving_store_id",), "stores", ("store_id",)),
            (("receiving_warehouse_id",), "warehouses", ("warehouse_id",)),
        ],
        "return_items": [
            (("return_id", "order_id"), "returns", ("return_id", "order_id")),
            (
                ("order_item_id", "order_id"),
                "order_items",
                ("order_item_id", "order_id"),
            ),
            (
                ("shipment_item_id", "order_item_id", "order_id"),
                "shipment_items",
                ("shipment_item_id", "order_item_id", "order_id"),
            ),
        ],
    },
    "scc": {
        "sales_orders": [(("location_id",), "locations", ("location_id",))],
        "sales_order_lines": [
            (("sales_order_id",), "sales_orders", ("sales_order_id",))
        ],
        "payment_transactions": [
            (("sales_order_id",), "sales_orders", ("sales_order_id",)),
            (("location_id",), "locations", ("location_id",)),
        ],
        "stock_balance": [
            (("item_id",), "item_master", ("item_id",)),
            (("location_id",), "locations", ("location_id",)),
        ],
    },
}


def require(condition: bool, description: str) -> None:
    if not condition:
        raise ValueError(description)


UNIQUE = {
    "customers": [("customer_number",)],
    "product_categories": [("category_code",)],
    "products": [("sku",), ("barcode",)],
    "stores": [("store_code",)],
    "warehouses": [("warehouse_code",)],
    "inventory": [("product_id", "store_id"), ("product_id", "warehouse_id")],
    "stock_movements": [
        ("movement_key",),
        ("transfer_id", "movement_type"),
        ("reverses_movement_id",),
    ],
    "orders": [("order_number",), ("order_request_key",)],
    "order_addresses": [("order_id", "address_role")],
    "order_items": [("order_id", "line_number")],
    "payments": [
        ("payment_request_key",),
        ("provider", "provider_transaction_id", "operation_type"),
    ],
    "shipments": [("shipment_number",), ("carrier", "tracking_number")],
    "shipment_items": [("shipment_id", "order_item_id")],
    "returns": [("return_number",)],
    "return_items": [("return_id", "shipment_item_id")],
}


def unique(rows: list[Row], columns: tuple[str, ...]) -> None:
    keys = [
        tuple(r[c] for c in columns)
        for r in rows
        if all(r[c] is not None for c in columns)
    ]
    require(len(set(keys)) == len(keys), f"Duplicate unique key: {columns}")


class Validator:
    """Retains master lookup sets and inventory totals, never the order history."""

    def __init__(self, masters: dict[str, Bundle]) -> None:
        self.masters = masters
        self.master_indexes: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
        self.ledger: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
        self.inventory = {r["inventory_id"]: r for r in masters["rmrg"]["inventory"]}

    def bundle(self, company: str, bundle: Bundle) -> None:
        indexes: dict[tuple[str, tuple[str, ...]], set[tuple[Any, ...]]] = {}
        for table, values in bundle.items():
            pk = SCHEMA[company][table][0][0]
            require(
                len({v[pk] for v in values}) == len(values), f"Duplicate PK: {table}"
            )
            if company == "rmrg":
                for key in UNIQUE.get(table, []):
                    unique(values, key)
                if table == "customer_addresses":
                    for flag in ("is_default_shipping", "is_default_billing"):
                        unique(
                            [v for v in values if v[flag] and v["archived_at"] is None],
                            ("customer_id",),
                        )
                elif table == "payment_allocations":
                    unique(
                        [
                            v
                            for v in values
                            if v["order_item_id"] is not None
                            and v["return_item_id"] is None
                        ],
                        ("payment_id", "order_item_id", "allocation_type"),
                    )
                    unique(
                        [v for v in values if v["return_item_id"] is not None],
                        ("payment_id", "return_item_id", "allocation_type"),
                    )
                    unique(
                        [v for v in values if v["order_item_id"] is None],
                        ("payment_id", "allocation_type"),
                    )
            for v in values:
                validate_row(company, table, v)
                for child, parent, parent_columns in FKS[company].get(table, []):
                    key = tuple(v[c] for c in child)
                    if any(x is None for x in key):
                        continue
                    cache = (parent, parent_columns)
                    if cache not in indexes:
                        master_key = (company, parent, parent_columns)
                        if master_key not in self.master_indexes:
                            self.master_indexes[master_key] = {
                                tuple(x[c] for c in parent_columns)
                                for x in self.masters[company].get(parent, [])
                            }
                        master = self.master_indexes[master_key]
                        indexes[cache] = (
                            master
                            if parent not in bundle
                            else master
                            | {
                                tuple(x[c] for c in parent_columns)
                                for x in bundle[parent]
                            }
                        )
                    require(
                        key in indexes[cache],
                        f"Broken FK: {company}.{table} {child}={key} -> {parent}",
                    )
        if company == "scc":
            keys = [
                (r["sales_order_id"], r["line_number"])
                for r in bundle.get("sales_order_lines", [])
            ]
            require(len(set(keys)) == len(keys), "Duplicate SCC order/line number")
            return
        self.rmrg(bundle)

    def rmrg(self, b: Bundle) -> None:
        for customer in b.get("customers", []):
            if customer["lifecycle_status"] == "anonymized":
                require(
                    customer["email"] is None
                    and customer["phone"] is None
                    and not customer["marketing_opt_in"]
                    and customer["anonymized_at"] is not None,
                    "Invalid anonymization",
                )
        for inv in b.get("inventory", []):
            require(
                (inv["store_id"] is None) != (inv["warehouse_id"] is None),
                "Inventory location XOR",
            )
            require(
                min(
                    inv["quantity_on_hand"],
                    inv["quantity_reserved"],
                    inv["quantity_unavailable"],
                    inv["reorder_point"],
                )
                >= 0
                and inv["quantity_reserved"] + inv["quantity_unavailable"]
                <= inv["quantity_on_hand"]
                and inv["target_stock_level"] >= inv["reorder_point"],
                "Inventory balance constraints",
            )
        orders = {r["order_id"]: r for r in b.get("orders", [])}
        lines = {r["order_item_id"]: r for r in b.get("order_items", [])}
        shipments = {r["shipment_id"]: r for r in b.get("shipments", [])}
        shipped = {r["shipment_item_id"]: r for r in b.get("shipment_items", [])}
        returns = {r["return_id"]: r for r in b.get("returns", [])}
        return_items = {r["return_item_id"]: r for r in b.get("return_items", [])}
        payments = {r["payment_id"]: r for r in b.get("payments", [])}
        allocated = b.get("payment_allocations", [])
        for order in orders.values():
            items = [l for l in lines.values() if l["order_id"] == order["order_id"]]
            require(bool(items), "Accepted order has no lines")
            require(
                (order["channel"] == "store") == (order["origin_store_id"] is not None),
                "Store origin rule",
            )
            for column, component in [
                ("merchandise_subtotal", "gross_amount"),
                ("discount_total", "discount_amount"),
                ("merchandise_tax_total", "tax_amount"),
            ]:
                require(
                    order[column] == sum((l[component] for l in items), ZERO),
                    "Order line/header totals",
                )
            require(
                order["order_total"]
                == order["merchandise_subtotal"]
                - order["discount_total"]
                + order["merchandise_tax_total"]
                + order["shipping_amount"]
                + order["shipping_tax_amount"],
                "Order total equation",
            )
            require(order["placed_at"] is not None, "Seed accepted order placement")
        for address in b.get("order_addresses", []):
            require(
                (address["source_customer_id"] is None)
                == (address["source_customer_address_id"] is None),
                "Address provenance pair",
            )
        for line in lines.values():
            require(
                0 <= line["quantity_cancelled"] <= line["quantity_ordered"]
                and line["quantity_ordered"] > 0,
                "Invalid line quantities",
            )
            require(
                line["gross_amount"]
                == money(line["quantity_ordered"] * line["unit_price"]),
                "Line gross equation",
            )
            require(
                0 <= line["discount_amount"] <= line["gross_amount"],
                "Line discount bounds",
            )
            require(
                line["tax_amount"]
                == money(
                    (line["gross_amount"] - line["discount_amount"])
                    * line["tax_rate_percent"]
                    / 100
                ),
                "Line tax rounding",
            )
            require(
                line["line_total"]
                == line["gross_amount"] - line["discount_amount"] + line["tax_amount"],
                "Line total equation",
            )
            units = sum(
                s["quantity"]
                for s in shipped.values()
                if s["order_item_id"] == line["order_item_id"]
                and shipments[s["shipment_id"]]["shipment_status"] != "cancelled"
            )
            handed = sum(
                s["quantity"]
                for s in shipped.values()
                if s["order_item_id"] == line["order_item_id"]
                and shipments[s["shipment_id"]]["handed_over_at"] is not None
            )
            require(
                units + line["quantity_cancelled"] <= line["quantity_ordered"],
                "Shipment over-allocation",
            )
            require(
                (line["requested_fulfillment"] == "pickup")
                == (line["requested_pickup_store_id"] is not None),
                "Pickup store rule",
            )
            if line["line_status"] == "fulfilled":
                require(
                    handed == line["quantity_ordered"] - line["quantity_cancelled"],
                    "Fulfillment status quantity",
                )
            if line["line_status"] == "cancelled":
                require(
                    line["quantity_cancelled"] == line["quantity_ordered"]
                    and handed == 0,
                    "Cancellation quantity",
                )
        for ship in shipments.values():
            require(
                (ship["origin_store_id"] is None)
                != (ship["origin_warehouse_id"] is None),
                "Shipment origin XOR",
            )
            require(
                (ship["fulfillment_type"] == "ship")
                == (ship["shipping_address_id"] is not None),
                "Shipment shipping address",
            )
            for si in shipped.values():
                if si["shipment_id"] == ship["shipment_id"]:
                    line = lines[si["order_item_id"]]
                    require(
                        si["quantity"] > 0
                        and ship["fulfillment_type"] == line["requested_fulfillment"],
                        "Shipment line mode/quantity",
                    )
                    if ship["fulfillment_type"] == "pickup":
                        require(
                            ship["origin_store_id"]
                            == line["requested_pickup_store_id"],
                            "Wrong pickup origin",
                        )
                    if ship["fulfillment_type"] == "carryout":
                        require(
                            ship["origin_store_id"]
                            == orders[ship["order_id"]]["origin_store_id"],
                            "Wrong carryout origin",
                        )
            if ship["shipment_status"] == "delivered":
                require(
                    ship["planned_at"]
                    <= ship["ready_at"]
                    <= ship["handed_over_at"]
                    <= ship["delivered_at"],
                    "Shipment milestone ordering",
                )
                if ship["fulfillment_type"] == "ship":
                    require(
                        bool(ship["carrier"]) and bool(ship["tracking_number"]),
                        "Delivered carrier references",
                    )
                else:
                    require(
                        ship["handed_over_at"] == ship["delivered_at"]
                        and ship["carrier"] is None,
                        "Store delivery semantics",
                    )
        for item in return_items.values():
            q, a, r, restock, dispose = (
                item[k]
                for k in (
                    "quantity_requested",
                    "quantity_authorized",
                    "quantity_received",
                    "quantity_restocked",
                    "quantity_disposed",
                )
            )
            require(
                q > 0
                and 0 <= r <= a <= q
                and restock + dispose == r
                and min(restock, dispose) >= 0,
                "Return quantities",
            )
            si = shipped[item["shipment_item_id"]]
            require(
                shipments[si["shipment_id"]]["handed_over_at"] is not None
                and a <= si["quantity"],
                "Return fulfillment eligibility",
            )
            line = lines[item["order_item_id"]]
            require(
                item["merchandise_refund_amount"]
                <= money(
                    (line["gross_amount"] - line["discount_amount"])
                    * a
                    / line["quantity_ordered"]
                )
                and item["tax_refund_amount"]
                <= money(line["tax_amount"] * a / line["quantity_ordered"]),
                "Return original-price entitlement",
            )
            require(
                item["last_received_at"] <= item["inspected_at"], "Inspection ordering"
            )
        for r in returns.values():
            require(
                (r["receiving_store_id"] is None)
                != (r["receiving_warehouse_id"] is None),
                "Return location XOR",
            )
            require(
                r["currency_code"] == orders[r["order_id"]]["currency_code"],
                "Return currency",
            )
            require(
                r["refund_total"]
                == sum(
                    (
                        r[k]
                        for k in (
                            "merchandise_refund_amount",
                            "tax_refund_amount",
                            "shipping_refund_amount",
                            "shipping_tax_refund_amount",
                        )
                    ),
                    ZERO,
                ),
                "Return total equation",
            )
            for rc, lc in [
                ("merchandise_refund_amount", "merchandise_refund_amount"),
                ("tax_refund_amount", "tax_refund_amount"),
            ]:
                require(
                    r[rc]
                    == sum(
                        (
                            i[lc]
                            for i in return_items.values()
                            if i["return_id"] == r["return_id"]
                        ),
                        ZERO,
                    ),
                    "Return header/line amounts",
                )
            require(
                r["requested_at"]
                <= r["authorized_at"]
                <= r["first_received_at"]
                <= r["fully_received_at"]
                <= r["resolved_at"],
                "Return milestone ordering",
            )
            settled = sum(
                (
                    p["amount"]
                    for p in payments.values()
                    if p["return_id"] == r["return_id"]
                    and p["payment_status"] == "succeeded"
                ),
                ZERO,
            )
            require(settled == r["refund_total"], "Closed return settlement")
        for payment in payments.values():
            require(
                payment["currency_code"] == orders[payment["order_id"]]["currency_code"]
                and payment["amount"] > 0,
                "Payment currency/amount",
            )
            own = [a for a in allocated if a["payment_id"] == payment["payment_id"]]
            if payment["operation_type"] in ("capture", "refund"):
                require(
                    sum((a["amount"] for a in own), ZERO) == payment["amount"],
                    "Payment allocation reconciliation",
                )
            else:
                require(not own, "Authorization/void allocation")
            require(
                (payment["processed_at"] is None)
                == (payment["payment_status"] == "pending"),
                "Payment terminal timestamp",
            )
            require(
                (payment["failure_code"] is not None)
                == (payment["payment_status"] == "failed"),
                "Payment failure code",
            )
            if payment["parent_payment_id"] is not None:
                parent = payments[payment["parent_payment_id"]]
                require(
                    parent["payment_status"] == "succeeded"
                    and all(
                        parent[k] == payment[k]
                        for k in (
                            "order_id",
                            "currency_code",
                            "provider",
                            "payment_method",
                        )
                    ),
                    "Payment parent identity/status",
                )
                require(
                    parent["operation_type"]
                    == (
                        "capture"
                        if payment["operation_type"] == "refund"
                        else "authorization"
                    ),
                    "Payment parent operation",
                )
            children = [
                p
                for p in payments.values()
                if p["parent_payment_id"] == payment["payment_id"]
                and p["payment_status"] in ("pending", "succeeded")
            ]
            require(
                sum((p["amount"] for p in children), ZERO) <= payment["amount"],
                "Payment parent capacity",
            )
        for allocation in allocated:
            payment = payments[allocation["payment_id"]]
            require(
                allocation["amount"] > 0
                and (
                    (allocation["allocation_type"] in ("merchandise", "tax"))
                    == (allocation["order_item_id"] is not None)
                ),
                "Allocation component/line",
            )
            require(
                (allocation["return_id"] is None)
                == (allocation["return_item_id"] is None),
                "Allocation return pair",
            )
            if payment["operation_type"] == "refund":
                parent_allocations = [
                    a
                    for a in allocated
                    if a["payment_id"] == payment["parent_payment_id"]
                    and a["allocation_type"] == allocation["allocation_type"]
                    and a["order_item_id"] == allocation["order_item_id"]
                ]
                require(
                    allocation["amount"]
                    <= sum((a["amount"] for a in parent_allocations), ZERO),
                    "Refund original capture component",
                )
                if (
                    allocation["order_item_id"] is not None
                    and payment["return_id"] is not None
                ):
                    require(
                        allocation["return_id"] == payment["return_id"]
                        and allocation["return_item_id"] in return_items,
                        "Refund exact return-item provenance",
                    )
        # Component caps must hold in aggregate across operations, not just per row.
        for line in lines.values():
            for kind, entitlement in [
                ("merchandise", line["gross_amount"] - line["discount_amount"]),
                ("tax", line["tax_amount"]),
            ]:
                captures = [
                    a
                    for a in allocated
                    if a["order_item_id"] == line["order_item_id"]
                    and a["allocation_type"] == kind
                    and payments[a["payment_id"]]["operation_type"] == "capture"
                    and payments[a["payment_id"]]["payment_status"]
                    in ("pending", "succeeded")
                ]
                require(
                    sum((a["amount"] for a in captures), ZERO) <= entitlement,
                    "Capture original line component cap",
                )
        for parent in payments.values():
            if parent["operation_type"] != "capture":
                continue
            for original in [
                a for a in allocated if a["payment_id"] == parent["payment_id"]
            ]:
                refunds = [
                    a
                    for a in allocated
                    if payments[a["payment_id"]]["parent_payment_id"]
                    == parent["payment_id"]
                    and payments[a["payment_id"]]["operation_type"] == "refund"
                    and payments[a["payment_id"]]["payment_status"]
                    in ("pending", "succeeded")
                    and a["allocation_type"] == original["allocation_type"]
                    and a["order_item_id"] == original["order_item_id"]
                ]
                require(
                    sum((a["amount"] for a in refunds), ZERO) <= original["amount"],
                    "Aggregate capture-component refund cap",
                )
        for ri in return_items.values():
            for kind, column in [
                ("merchandise", "merchandise_refund_amount"),
                ("tax", "tax_refund_amount"),
            ]:
                refunds = [
                    a
                    for a in allocated
                    if a["return_item_id"] == ri["return_item_id"]
                    and a["allocation_type"] == kind
                    and payments[a["payment_id"]]["payment_status"]
                    in ("pending", "succeeded")
                ]
                require(
                    sum((a["amount"] for a in refunds), ZERO) <= ri[column],
                    "Aggregate return-item entitlement cap",
                )
        sale_totals: dict[int, int] = defaultdict(int)
        receipt_totals: dict[int, int] = defaultdict(int)
        for m in b.get("stock_movements", []):
            inv = self.inventory[m["inventory_id"]]
            vector = [m["quantity_delta"], m["reserved_delta"], m["unavailable_delta"]]
            require(any(vector), "Zero ledger movement")
            require(
                (m["source_document_type"] is None) == (m["reference_number"] is None),
                "Movement external document pair",
            )
            require(
                not (m["shipment_item_id"] and m["return_item_id"]),
                "Mutually exclusive stock provenance",
            )
            kind = m["movement_type"]
            if kind in ("opening", "receipt", "return"):
                require(
                    vector[0] > 0 and vector[1:] == [0, 0],
                    "Positive physical movement vector",
                )
            elif kind == "sale":
                require(
                    vector[0] < 0 and vector[0] <= vector[1] <= 0 and vector[2] == 0,
                    "Sale movement vector",
                )
                sale_totals[m["shipment_item_id"]] -= vector[0]
            elif kind == "reserve":
                require(
                    vector[0] == 0 and vector[1] > 0 and vector[2] == 0,
                    "Reserve vector",
                )
            elif kind in ("quarantine", "unquarantine"):
                require(
                    vector[0] == 0
                    and vector[1] == 0
                    and (vector[2] > 0 if kind == "quarantine" else vector[2] < 0),
                    "Inspection vector",
                )
            elif kind == "adjustment":
                require(vector[0] != 0 and vector[1:] == [0, 0], "Adjustment vector")
            for i, delta in enumerate(vector):
                self.ledger[m["inventory_id"]][i] += delta
            if m["shipment_item_id"] is not None:
                si = shipped[m["shipment_item_id"]]
                line = lines[si["order_item_id"]]
                ship = shipments[si["shipment_id"]]
                require(
                    inv["product_id"] == line["product_id"]
                    and inv["store_id"] == ship["origin_store_id"]
                    and inv["warehouse_id"] == ship["origin_warehouse_id"],
                    "Sale stock product/origin",
                )
            if m["return_item_id"] is not None:
                item = return_items[m["return_item_id"]]
                line = lines[item["order_item_id"]]
                r = returns[item["return_id"]]
                require(
                    inv["product_id"] == line["product_id"]
                    and inv["store_id"] == r["receiving_store_id"]
                    and inv["warehouse_id"] == r["receiving_warehouse_id"],
                    "Return stock product/location",
                )
                if kind == "return":
                    receipt_totals[item["return_item_id"]] += vector[0]
        for si in shipped.values():
            expected = (
                si["quantity"]
                if shipments[si["shipment_id"]]["handed_over_at"] is not None
                else 0
            )
            require(
                sale_totals[si["shipment_item_id"]] == expected,
                "Sale ledger vs handover units",
            )
        for ri in return_items.values():
            require(
                receipt_totals[ri["return_item_id"]] == ri["quantity_received"],
                "Return ledger vs receipt units",
            )

    def finish(self) -> None:
        for ident, inv in self.inventory.items():
            require(
                self.ledger[ident]
                == [
                    inv["quantity_on_hand"],
                    inv["quantity_reserved"],
                    inv["quantity_unavailable"],
                ],
                "Final inventory vs complete ledger",
            )
        self.bundle("rmrg", {"inventory": list(self.inventory.values())})
