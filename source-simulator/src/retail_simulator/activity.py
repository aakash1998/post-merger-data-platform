"""Continuous retail commands built on KAN-24 rows, pricing and ledger helpers."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random
from typing import Any
from zoneinfo import ZoneInfo

from .changes import Change, Database, Transaction
from .config import Config
from .contracts import Row, SCHEMA, ZERO, money, row
from .generator import Bundle, Generator, FIRST, LAST
from .persistence import Persistence


class LiveGenerator(Generator):
    """Reuse seed transaction helpers against current rows and durable key highwaters."""

    def __init__(
        self,
        data: Database,
        config: Config,
        counters: dict[str, int],
        rng: random.Random,
        now: datetime,
    ) -> None:
        self.config = config
        self.random = rng
        self.start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self.snapshot = now
        self.ids = defaultdict(int, counters)
        self.masters = {
            co: {table: list(rows.values()) for table, rows in tables.items()}
            for co, tables in data.items()
        }
        self.balances = {
            (
                inv["product_id"],
                "store" if inv["store_id"] else "warehouse",
                inv["store_id"] or inv["warehouse_id"],
            ): inv
            for inv in self.masters["rmrg"]["inventory"]
        }
        self.pending_movements = []
        self.metrics = defaultdict(int)
        self.day_weights = [1]

    def stamp(self) -> datetime:
        return self.snapshot.replace(microsecond=0)

    def payment(
        self,
        bundle: Bundle,
        oid: int,
        operation: str,
        amount: Decimal,
        stamp: datetime,
        method: str,
        parent: int | None = None,
        status: str = "succeeded",
        return_id: int | None = None,
        components: list[tuple[int | None, str, Decimal, int | None]] | None = None,
    ) -> int:
        ident = super().payment(
            bundle,
            oid,
            operation,
            amount,
            min(stamp, self.snapshot),
            method,
            parent,
            status,
            return_id,
            components,
        )
        value = bundle["payments"][-1]
        if value["processed_at"] is not None:
            value["processed_at"] = min(value["processed_at"], self.snapshot)
        return ident


class Activity:
    def __init__(
        self, store: Persistence, config: Config, rng: random.Random | None = None
    ) -> None:
        self.store, self.config = store, config
        self.rng = rng or random.Random()

    def plan(
        self, company: str, activity: str, now: datetime | None = None
    ) -> Transaction | None:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Activity clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        # Snapshot bootstrap can be later than wall time in a test profile.
        latest = max(
            (
                r["updated_at"]
                for rows in self.store.data["rmrg"].values()
                for r in rows.values()
            ),
            default=now,
        )
        if now < latest:
            raise ValueError("Activity clock precedes the loaded source baseline")
        original = self.store.data
        working = dict(original)
        working[company] = deepcopy(original[company])
        customers = [
            r
            for r in working["rmrg"]["customers"].values()
            if r["lifecycle_status"] == "active"
        ]
        cfg = replace(
            self.config,
            rmrg_orders=1,
            scc_orders=1,
            rmrg_customers=len(customers) + 1,
            scc_customers=len(working["scc"]["customer_master"]),
            open_fraction=1.0,
            cancel_fraction=0.0,
            return_fraction=0.0,
            days=1,
            rmrg_products=len(working["rmrg"]["products"]),
            scc_products=len(working["scc"]["item_master"]),
            rmrg_stores=len(working["rmrg"]["stores"]),
            rmrg_warehouses=len(working["rmrg"]["warehouses"]),
            scc_locations=len(working["scc"]["locations"]),
        )
        generator = LiveGenerator(
            working, cfg, dict(self.store.highwater[company]), self.rng, now
        )
        generator.masters["rmrg"]["customers"] = customers
        if not self.execute(company, activity, working, generator, now):
            return None
        # Fold all business edits into one SQL update per affected source row.
        changes = []
        local = now.astimezone(ZoneInfo("America/Edmonton")).replace(
            tzinfo=None, microsecond=0
        )
        for table, rows in working[company].items():
            previous = original[company][table]
            for ident in sorted(previous.keys() | rows.keys()):
                before, after = previous.get(ident), rows.get(ident)
                if before == after:
                    continue
                if after is not None:
                    if company == "rmrg":
                        after.update(updated_at=now, updated_by="continuous-simulator")
                        after["row_version"] = (
                            before["row_version"] + 1 if before else 1
                        )
                        if before is None:
                            after.update(
                                created_at=now, created_by="continuous-simulator"
                            )
                    elif before is None:
                        after.update(
                            created_at=local, updated_at=local, updated_by="SIM"
                        )
                    elif (
                        activity not in {"correct_invoice", "correct_posting"}
                        or self.rng.random() >= self.config.messy_fraction
                    ):
                        after.update(updated_at=local, updated_by="SIM")
                changes.append(Change(table, ident, deepcopy(before), deepcopy(after)))
        if not changes:
            return None
        return Transaction(
            self.store.sequence + 1,
            company,
            activity,
            tuple(changes),
            dict(generator.ids),
        )

    def insert_bundle(self, company: str, bundle: Bundle, data: Database) -> None:
        for table, values in bundle.items():
            pk = SCHEMA[company][table][0][0]
            for value in values:
                data[company][table][value[pk]] = value

    def pick(self, values: list[Row]) -> Row | None:
        return self.rng.choice(values) if values else None

    def execute(
        self, company: str, name: str, data: Database, g: LiveGenerator, now: datetime
    ) -> bool:
        tables = data[company]
        local = now.astimezone(ZoneInfo("America/Edmonton")).replace(
            tzinfo=None, microsecond=0
        )
        if name == "new_customer":
            table = "customers" if company == "rmrg" else "customer_master"
            ident = g.id(table)
            if company == "rmrg":
                customer = row(
                    company,
                    table,
                    now,
                    customer_id=ident,
                    customer_number=f"R-{ident:08d}",
                    first_name=self.rng.choice(FIRST),
                    last_name=self.rng.choice(LAST),
                    email=f"live{ident}@example.invalid",
                    phone=f"+1403555{100+ident%100:04d}",
                    preferred_language="en-CA",
                    loyalty_tier="none",
                    lifecycle_status="active",
                    marketing_opt_in=False,
                    registered_at=now,
                )
                address = row(
                    company,
                    "customer_addresses",
                    now,
                    customer_address_id=g.id("customer_addresses"),
                    customer_id=ident,
                    address_label="Home",
                    recipient_name=f"{customer['first_name']} {customer['last_name']}",
                    address_line1=f"{100+ident} Example Avenue",
                    city="Calgary",
                    region="AB",
                    postal_code="T2P 1J9",
                    country_code="CA",
                    phone=customer["phone"],
                    is_default_shipping=True,
                    is_default_billing=True,
                )
                self.insert_bundle(
                    company,
                    {"customers": [customer], "customer_addresses": [address]},
                    data,
                )
            else:
                customer = row(
                    company,
                    table,
                    local,
                    customer_id=ident,
                    customer_code=f"C{ident:05d}",
                    customer_name=f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}",
                    customer_type="RETAIL",
                    email_address=f"live-scc{ident}@example.invalid",
                    address_text=f"{100+ident} Sample Rd",
                    city="Calgary",
                    province="Alta",
                    country="Canada",
                    customer_group="Regular",
                    credit_limit=ZERO,
                    active_flag="Y",
                )
                tables[table][ident] = customer
            return True
        if name == "update_customer":
            table = "customers" if company == "rmrg" else "customer_master"
            customer = self.pick(
                [
                    r
                    for r in tables[table].values()
                    if r.get("lifecycle_status") != "anonymized"
                    and r.get("customer_type") != "WALKIN"
                ]
            )
            if customer is None:
                return False
            if company == "rmrg":
                customer.update(
                    loyalty_tier=self.rng.choice(["silver", "gold", "platinum"]),
                    preferred_language=self.rng.choice(["en-CA", "fr-CA"]),
                )
                customer["phone"] = f"+1403555{self.rng.randint(100,199):04d}"
            else:
                customer.update(
                    phone_number=f"(403) 555-{self.rng.randint(100,199):04d}",
                    active_flag=self.rng.choice(["Y", "N", "1", "0"]),
                    province=self.rng.choice(["AB", "Alberta", "Alta"]),
                )
            return True
        if name == "new_order":
            if company == "rmrg":
                bundle = next(g.rmrg_orders(order_stamp=now))
            else:
                bundle = next(g.scc_orders())
                bundle.pop("payment_transactions", None)
                bundle["sales_orders"][0].update(order_status="OPEN", paid_amount=ZERO)
            self.insert_bundle(company, bundle, data)
            return True
        if company == "scc":
            return self.scc(name, data, g, local)
        if name == "inventory":
            inv = self.pick(list(tables["inventory"].values()))
            g.movement(
                inv,
                "receipt",
                self.rng.randint(5, 30),
                0,
                0,
                now,
                "purchase_receipt",
                source_document_type="purchase_receipt",
                reference_number=f'LIVE-RECEIPT-{g.ids["stock_movements"]+1}',
            )
            self.insert_bundle(company, {"stock_movements": g.drain_movements()}, data)
            return True
        if name == "draft":
            oid = g.id("orders")
            value = row(
                company,
                "orders",
                now,
                order_id=oid,
                order_number=f"R-ORD-{oid:012d}",
                order_request_key=f"LIVE-DRAFT-{oid}",
                channel="web",
                fulfillment_preference="ship",
                order_status="draft",
                currency_code="CAD",
                merchandise_subtotal=ZERO,
                discount_total=ZERO,
                merchandise_tax_total=ZERO,
                shipping_amount=ZERO,
                shipping_tax_amount=ZERO,
                order_total=ZERO,
            )
            tables["orders"][oid] = value
            return True
        if name == "delete_draft":
            order = self.pick(
                [o for o in tables["orders"].values() if o["order_status"] == "draft"]
            )
            if order is None:
                return False
            oid = order["order_id"]
            for table in ("order_items", "order_addresses", "orders"):
                for ident, value in list(tables[table].items()):
                    if value["order_id"] == oid:
                        del tables[table][ident]
            return True
        if name == "payment":
            payment = self.pick(
                [
                    p
                    for p in tables["payments"].values()
                    if p["operation_type"] == "capture"
                    and p["payment_status"] == "pending"
                ]
            )
            if payment is None:
                return False
            payment.update(
                payment_status="succeeded",
                processed_at=now,
                provider_transaction_id=(
                    f'LIVE-TXN-{payment["payment_id"]}'
                    if payment["payment_method"] != "cash"
                    else None
                ),
            )
            return True
        if name == "cancel":
            pending = [
                o
                for o in tables["orders"].values()
                if o["order_status"] in {"placed", "processing"}
                and not any(
                    p["order_id"] == o["order_id"]
                    and p["operation_type"] == "capture"
                    and p["payment_status"] == "succeeded"
                    for p in tables["payments"].values()
                )
            ]
            order = self.pick(pending)
            if order is None:
                return False
            oid = order["order_id"]
            for p in tables["payments"].values():
                if p["order_id"] == oid and p["payment_status"] == "pending":
                    p.update(
                        payment_status="failed",
                        failure_code="CANCEL_CONFIRMED",
                        processed_at=now,
                    )
            for auth in list(tables["payments"].values()):
                if (
                    auth["order_id"] == oid
                    and auth["operation_type"] == "authorization"
                    and auth["payment_status"] == "succeeded"
                ):
                    b: Bundle = defaultdict(list)
                    g.payment(
                        b,
                        oid,
                        "void",
                        auth["amount"],
                        now,
                        auth["payment_method"],
                        parent=auth["payment_id"],
                    )
                    self.insert_bundle(company, b, data)
            for line in tables["order_items"].values():
                if line["order_id"] == oid:
                    line.update(
                        quantity_cancelled=line["quantity_ordered"],
                        line_status="cancelled",
                    )
            for ship in tables["shipments"].values():
                if ship["order_id"] == oid:
                    ship.update(shipment_status="cancelled", cancelled_at=now)
                    for si in tables["shipment_items"].values():
                        if si["shipment_id"] == ship["shipment_id"]:
                            inv = self.inventory_for_shipment(tables, si, ship)
                            g.movement(
                                inv,
                                "release",
                                0,
                                -si["quantity"],
                                0,
                                now,
                                "allocation_release",
                                shipment_item_id=si["shipment_item_id"],
                            )
            order.update(order_status="cancelled", cancelled_at=now)
            self.insert_bundle(company, {"stock_movements": g.drain_movements()}, data)
            return True
        if name in {"shipment", "delivery"}:
            return self.ship(name, data, g, now)
        if name in {"return", "return_progress"}:
            return self.return_activity(name, data, g, now)
        raise ValueError(f"Unknown RMRG activity: {name}")

    def inventory_for_shipment(
        self, tables: dict[str, dict[int, Row]], si: Row, ship: Row
    ) -> Row:
        product = tables["order_items"][si["order_item_id"]]["product_id"]
        return next(
            inv
            for inv in tables["inventory"].values()
            if inv["product_id"] == product
            and inv["store_id"] == ship["origin_store_id"]
            and inv["warehouse_id"] == ship["origin_warehouse_id"]
        )

    def ship(self, name: str, data: Database, g: LiveGenerator, now: datetime) -> bool:
        tables = data["rmrg"]
        paid_orders = {
            p["order_id"]
            for p in tables["payments"].values()
            if p["operation_type"] == "capture" and p["payment_status"] == "succeeded"
        }
        ship = self.pick(
            [
                s
                for s in tables["shipments"].values()
                if (
                    s["shipment_status"] == "handed_over"
                    if name == "delivery"
                    else s["shipment_status"] in {"allocated", "ready"}
                    and s["order_id"] in paid_orders
                )
            ]
        )
        if ship is None:
            return False
        if name == "delivery":
            ship.update(shipment_status="delivered", delivered_at=now)
        elif ship["shipment_status"] == "allocated":
            ship.update(shipment_status="ready", ready_at=now)
        else:
            ship.update(
                shipment_status=(
                    "handed_over" if ship["fulfillment_type"] == "ship" else "delivered"
                ),
                handed_over_at=now,
                delivered_at=now if ship["fulfillment_type"] != "ship" else None,
                carrier=(
                    "synthetic_carrier" if ship["fulfillment_type"] == "ship" else None
                ),
                tracking_number=(
                    f'LIVE-{ship["shipment_id"]:012d}'
                    if ship["fulfillment_type"] == "ship"
                    else None
                ),
            )
            for si in tables["shipment_items"].values():
                if si["shipment_id"] == ship["shipment_id"]:
                    inv = self.inventory_for_shipment(tables, si, ship)
                    g.movement(
                        inv,
                        "sale",
                        -si["quantity"],
                        -si["quantity"],
                        0,
                        now,
                        "fulfillment",
                        shipment_item_id=si["shipment_item_id"],
                    )
            oid = ship["order_id"]
            for line in tables["order_items"].values():
                if line["order_id"] == oid:
                    handed = sum(
                        si["quantity"]
                        for si in tables["shipment_items"].values()
                        if si["order_item_id"] == line["order_item_id"]
                        and tables["shipments"][si["shipment_id"]]["handed_over_at"]
                        is not None
                    )
                    line["line_status"] = (
                        "fulfilled"
                        if handed
                        == line["quantity_ordered"] - line["quantity_cancelled"]
                        else "partially_fulfilled" if handed else "open"
                    )
            lines = [l for l in tables["order_items"].values() if l["order_id"] == oid]
            tables["orders"][oid]["order_status"] = (
                "fulfilled"
                if all(l["line_status"] == "fulfilled" for l in lines)
                else "partially_fulfilled"
            )
            self.insert_bundle("rmrg", {"stock_movements": g.drain_movements()}, data)
        return True

    def return_activity(
        self, name: str, data: Database, g: LiveGenerator, now: datetime
    ) -> bool:
        t = data["rmrg"]
        if name == "return":
            returned_orders = {r["order_id"] for r in t["returns"].values()}
            si = self.pick(
                [
                    s
                    for s in t["shipment_items"].values()
                    if s["order_id"] not in returned_orders
                    and t["shipments"][s["shipment_id"]]["shipment_status"]
                    == "delivered"
                ]
            )
            if si is None:
                return False
            rid, riid = g.id("returns"), g.id("return_items")
            receiving = self.rng.choice(list(t["stores"]))
            r = row(
                "rmrg",
                "returns",
                now,
                return_id=rid,
                return_number=f"R-RMA-{rid:012d}",
                order_id=si["order_id"],
                return_status="requested",
                return_channel="store",
                receiving_store_id=receiving,
                currency_code=t["orders"][si["order_id"]]["currency_code"],
                merchandise_refund_amount=ZERO,
                tax_refund_amount=ZERO,
                shipping_refund_amount=ZERO,
                shipping_tax_refund_amount=ZERO,
                refund_total=ZERO,
                requested_at=now,
            )
            ri = row(
                "rmrg",
                "return_items",
                now,
                return_item_id=riid,
                return_id=rid,
                order_id=si["order_id"],
                order_item_id=si["order_item_id"],
                shipment_item_id=si["shipment_item_id"],
                quantity_requested=1,
                quantity_authorized=0,
                quantity_received=0,
                quantity_restocked=0,
                quantity_disposed=0,
                reason_code="damaged" if self.rng.random() < 0.25 else "changed_mind",
                disposition="pending",
                merchandise_refund_amount=ZERO,
                tax_refund_amount=ZERO,
            )
            self.insert_bundle("rmrg", {"returns": [r], "return_items": [ri]}, data)
            return True
        r = self.pick(
            [
                r
                for r in t["returns"].values()
                if r["return_status"] in {"requested", "authorized", "received"}
            ]
        )
        if r is None:
            return False
        ri = next(
            i for i in t["return_items"].values() if i["return_id"] == r["return_id"]
        )
        line = t["order_items"][ri["order_item_id"]]
        inv = next(
            i
            for i in t["inventory"].values()
            if i["product_id"] == line["product_id"]
            and i["store_id"] == r["receiving_store_id"]
        )
        if r["return_status"] == "requested":
            net, tax = money(
                (line["gross_amount"] - line["discount_amount"])
                / line["quantity_ordered"]
            ), money(line["tax_amount"] / line["quantity_ordered"])
            ri.update(
                quantity_authorized=1,
                merchandise_refund_amount=net,
                tax_refund_amount=tax,
            )
            r.update(
                return_status="authorized",
                authorized_at=now,
                merchandise_refund_amount=net,
                tax_refund_amount=tax,
                refund_total=net + tax,
            )
        elif r["return_status"] == "authorized":
            ri.update(quantity_received=1, last_received_at=now)
            r.update(
                return_status="received", first_received_at=now, fully_received_at=now
            )
            g.movement(
                inv,
                "return",
                1,
                0,
                0,
                now,
                "customer_return",
                return_item_id=ri["return_item_id"],
            )
            g.movement(
                inv,
                "quarantine",
                0,
                0,
                1,
                now,
                "customer_return",
                return_item_id=ri["return_item_id"],
            )
        elif ri["disposition"] == "pending":
            dispose = ri["reason_code"] == "damaged"
            ri.update(
                disposition="dispose" if dispose else "restock",
                quantity_restocked=0 if dispose else 1,
                quantity_disposed=1 if dispose else 0,
                inspected_at=now,
            )
            g.movement(
                inv,
                "unquarantine",
                0,
                0,
                -1,
                now,
                "quality_release",
                return_item_id=ri["return_item_id"],
            )
            if dispose:
                g.movement(
                    inv,
                    "adjustment",
                    -1,
                    0,
                    0,
                    now,
                    "damage",
                    return_item_id=ri["return_item_id"],
                )
            capture = next(
                p
                for p in t["payments"].values()
                if p["order_id"] == r["order_id"]
                and p["operation_type"] == "capture"
                and p["payment_status"] == "succeeded"
            )
            b: Bundle = defaultdict(list)
            g.payment(
                b,
                r["order_id"],
                "refund",
                r["refund_total"],
                now,
                capture["payment_method"],
                parent=capture["payment_id"],
                status="pending",
                return_id=r["return_id"],
                components=[
                    (
                        ri["order_item_id"],
                        "merchandise",
                        ri["merchandise_refund_amount"],
                        ri["return_item_id"],
                    ),
                    (
                        ri["order_item_id"],
                        "tax",
                        ri["tax_refund_amount"],
                        ri["return_item_id"],
                    ),
                ],
            )
            self.insert_bundle("rmrg", b, data)
        else:
            refund = next(
                p
                for p in t["payments"].values()
                if p["return_id"] == r["return_id"] and p["payment_status"] == "pending"
            )
            refund.update(
                payment_status="succeeded",
                processed_at=now,
                provider_transaction_id=(
                    f'LIVE-TXN-{refund["payment_id"]}'
                    if refund["payment_method"] != "cash"
                    else None
                ),
            )
            r.update(return_status="closed", resolved_at=now)
        self.insert_bundle("rmrg", {"stock_movements": g.drain_movements()}, data)
        return True

    def scc(self, name: str, data: Database, g: LiveGenerator, local: datetime) -> bool:
        t = data["scc"]
        if name == "inventory":
            stock = self.pick(list(t["stock_balance"].values()))
            if stock is None:
                return False
            stock.update(
                quantity_on_hand=Decimal(self.rng.randint(-3, 60)).quantize(
                    Decimal("0.001")
                ),
                balance_as_of=local,
            )
            return True
        if name == "payment":
            order = self.pick(
                [o for o in t["sales_orders"].values() if o["order_status"] == "OPEN"]
            )
            if order is None:
                return False
            ident = g.id("payment_transactions")
            posting = row(
                "scc",
                "payment_transactions",
                local,
                payment_transaction_id=ident,
                sales_order_id=order["sales_order_id"],
                order_number_ref=order["order_number"],
                location_id=order["location_id"],
                receipt_number=f"RCPT-{ident%100:05d}",
                transaction_date=local.date(),
                transaction_time=local,
                transaction_type="REFUND" if order["total_amount"] < 0 else "PAYMENT",
                tender_code=self.rng.choice(["CASH", "CRD", "CHQ"]),
                amount=order["total_amount"],
                currency_text=order["currency_text"],
                reference_text=f"LIVE-POST-{ident}",
                posted_flag="Y",
            )
            t["payment_transactions"][ident] = posting
            order.update(order_status="PAID", paid_amount=posting["amount"])
            return True
        if name == "correct_invoice":
            line = self.pick(list(t["sales_order_lines"].values()))
            if line is None:
                return False
            line["quantity"] = (line["quantity"] or Decimal("1.000")) + Decimal("1.000")
            line["line_amount"] = money(
                line["quantity"] * (line["unit_price"] or ZERO)
                - (line["discount_amount"] or ZERO)
            )
            order = t["sales_orders"][line["sales_order_id"]]
            lines = [
                l
                for l in t["sales_order_lines"].values()
                if l["sales_order_id"] == line["sales_order_id"]
            ]
            order["subtotal_amount"] = sum(
                (l["line_amount"] or ZERO for l in lines), ZERO
            )
            if self.rng.random() >= self.config.messy_fraction:
                order["tax_amount"] = money(order["subtotal_amount"] * Decimal("0.05"))
                order["total_amount"] = (
                    order["subtotal_amount"]
                    - (order["discount_amount"] or ZERO)
                    + (order["tax_amount"] or ZERO)
                    + (order["freight_amount"] or ZERO)
                )
            return True
        if name == "correct_posting":
            posting = self.pick(list(t["payment_transactions"].values()))
            if posting is None:
                return False
            posting["posted_flag"] = "Y" if posting["posted_flag"] != "Y" else "N"
            return True
        if name == "delete_abandoned":
            order = self.pick(
                [
                    o
                    for o in t["sales_orders"].values()
                    if o["order_status"] == "OPEN"
                    and not any(
                        p["sales_order_id"] == o["sales_order_id"]
                        for p in t["payment_transactions"].values()
                    )
                ]
            )
            if order is None:
                return False
            for table in ("sales_order_lines", "sales_orders"):
                for ident, value in list(t[table].items()):
                    if value["sales_order_id"] == order["sales_order_id"]:
                        del t[table][ident]
            return True
        if name == "delete_customer":
            if len(t["customer_master"]) <= 12:
                return False
            customer = self.pick(
                [
                    c
                    for c in t["customer_master"].values()
                    if c["active_flag"] in {"N", "0"} and c["customer_type"] != "WALKIN"
                ]
            )
            if customer is None:
                return False
            del t["customer_master"][customer["customer_id"]]
            return True
        raise ValueError(f"Unknown SCC activity: {name}")
