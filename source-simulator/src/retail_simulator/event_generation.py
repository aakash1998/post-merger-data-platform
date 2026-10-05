"""Replay real synthetic business facts and generate weighted shopping sessions."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import random
from typing import Any
from zoneinfo import ZoneInfo

from .changes import Database
from .event_contract import Record, make_record


@dataclass(frozen=True)
class EventConfig:
    events: int = 1000
    seed: int = 26
    duplicate_fraction: float = 0.05
    late_fraction: float = 0.10
    reorder_fraction: float = 0.10
    late_slots: float = 120.0
    reorder_slots: float = 5.0
    rmrg_weight: float = 3.0
    scc_weight: float = 1.0

    def __post_init__(self) -> None:
        if (
            type(self.events) is not int
            or self.events < 1
            or type(self.seed) is not int
        ):
            raise ValueError("events must be positive and seed must be an integer")
        for name in ("duplicate_fraction", "late_fraction", "reorder_fraction"):
            v = getattr(self, name)
            if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError(f"{name} must be in [0,1]")
        for name in ("late_slots", "reorder_slots", "rmrg_weight", "scc_weight"):
            v = getattr(self, name)
            if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be finite and positive")


def facts(
    data: Database, env: str, fingerprint: str, produced: datetime
) -> list[Record]:
    result: list[Record] = []

    def add(
        co: str,
        table: str,
        row: dict[str, Any],
        pk: str,
        kind: str,
        stamp: datetime | None,
        fields: tuple[str, ...],
        aggregate: str,
        assumed: bool = False,
    ) -> None:
        if stamp is None:
            return
        raw = stamp.isoformat()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo("America/Edmonton"))
            assumed = True
        result.append(
            make_record(
                env,
                co,
                kind,
                aggregate,
                f"{fingerprint}:{table}:{row[pk]}:{raw}",
                stamp,
                produced,
                {k: row[k] for k in fields},
                {
                    "mode": "seed_fact_replay",
                    "snapshot_fingerprint": fingerprint,
                    "source_table": table,
                    "source_pk": str(row[pk]),
                    "source_time_raw": raw,
                    "timezone_assumed": assumed,
                    "source_updated_at": (
                        row["updated_at"].isoformat() if row["updated_at"] else None
                    ),
                },
            )
        )

    for r in data["rmrg"]["orders"].values():
        fields = (
            "order_id",
            "order_number",
            "customer_id",
            "channel",
            "order_total",
            "currency_code",
        )
        key = f"order:{r['order_id']}"
        add(
            "rmrg",
            "orders",
            r,
            "order_id",
            "orders-placed",
            r["placed_at"],
            fields,
            key,
        )
        add(
            "rmrg",
            "orders",
            r,
            "order_id",
            "orders-cancelled",
            r["cancelled_at"],
            fields,
            key,
        )
    for r in data["rmrg"]["payments"].values():
        add(
            "rmrg",
            "payments",
            r,
            "payment_id",
            "payments-resolved",
            r["processed_at"],
            (
                "payment_id",
                "order_id",
                "parent_payment_id",
                "return_id",
                "operation_type",
                "payment_method",
                "payment_status",
                "amount",
                "currency_code",
                "failure_code",
            ),
            f"order:{r['order_id']}",
        )
    for r in data["rmrg"]["shipments"].values():
        fields = (
            "shipment_id",
            "order_id",
            "fulfillment_type",
            "origin_store_id",
            "origin_warehouse_id",
        )
        for kind, col in (
            ("shipments-handed-over", "handed_over_at"),
            ("shipments-delivered", "delivered_at"),
        ):
            add(
                "rmrg",
                "shipments",
                r,
                "shipment_id",
                kind,
                r[col],
                fields,
                f"order:{r['order_id']}",
            )
    for r in data["rmrg"]["returns"].values():
        fields = (
            "return_id",
            "order_id",
            "return_channel",
            "receiving_store_id",
            "receiving_warehouse_id",
        )
        for kind, col in (
            ("returns-requested", "requested_at"),
            ("returns-received", "fully_received_at"),
        ):
            add(
                "rmrg",
                "returns",
                r,
                "return_id",
                kind,
                r[col],
                fields,
                f"order:{r['order_id']}",
            )
    for r in data["rmrg"]["stock_movements"].values():
        if r["movement_type"] == "opening":
            continue  # Baseline loading is not new operational activity.
        add(
            "rmrg",
            "stock_movements",
            r,
            "stock_movement_id",
            "inventory-moved",
            r["occurred_at"],
            (
                "stock_movement_id",
                "inventory_id",
                "movement_type",
                "quantity_delta",
                "reserved_delta",
                "unavailable_delta",
                "reason_code",
            ),
            f"inventory:{r['inventory_id']}",
        )
    for r in data["scc"]["sales_orders"].values():
        add(
            "scc",
            "sales_orders",
            r,
            "sales_order_id",
            "orders-entered",
            r["entered_at"],
            (
                "sales_order_id",
                "order_number",
                "customer_id_ref",
                "customer_code_ref",
                "sales_channel",
                "total_amount",
                "currency_text",
                "business_date",
            ),
            f"order:{r['sales_order_id']}",
        )
    for r in data["scc"]["payment_transactions"].values():
        key = (
            f"order:{r['sales_order_id']}"
            if r["sales_order_id"] is not None
            else f"payment:{r['payment_transaction_id']}"
        )
        add(
            "scc",
            "payment_transactions",
            r,
            "payment_transaction_id",
            "payments-posted",
            r["transaction_time"],
            (
                "payment_transaction_id",
                "sales_order_id",
                "order_number_ref",
                "transaction_type",
                "tender_code",
                "amount",
                "currency_text",
                "posted_flag",
            ),
            key,
        )
    for r in data["scc"]["stock_balance"].values():
        add(
            "scc",
            "stock_balance",
            r,
            "stock_balance_id",
            "inventory-observed",
            r["balance_as_of"],
            (
                "stock_balance_id",
                "item_id",
                "location_id",
                "quantity_on_hand",
                "quantity_allocated",
                "unit_code",
            ),
            f"stock-balance:{r['stock_balance_id']}",
        )
    return sorted(
        result,
        key=lambda r: (r.validate(env)["occurred_at"], r.validate(env)["event_id"]),
    )


def generate_records(
    data: Database,
    env: str,
    fingerprint: str,
    run_id: str,
    started: datetime,
    cfg: EventConfig,
) -> list[dict[str, Any]]:
    rng = random.Random(cfg.seed)
    historical = facts(data, env, fingerprint, started)
    cursor = 0
    base: list[Record] = []
    session = 0
    while len(base) < cfg.events:
        if cursor < len(historical) and rng.random() < 0.65:
            base.append(historical[cursor])
            cursor += 1
            continue
        company = rng.choices(["rmrg", "scc"], [cfg.rmrg_weight, cfg.scc_weight])[0]
        products = list(
            data[company]["products" if company == "rmrg" else "item_master"].values()
        )
        customers = list(
            data[company][
                "customers" if company == "rmrg" else "customer_master"
            ].values()
        )
        if not products:
            raise ValueError(
                "Shopping activity requires product masters for both companies"
            )
        # Same bestseller skew as KAN-24: first 20% get 65% of interactions.
        pool = (
            products[: max(1, len(products) // 5)] if rng.random() < 0.65 else products
        )
        product = rng.choice(pool)
        customer = rng.choice(customers) if customers and rng.random() > 0.25 else None
        if (
            company == "scc"
            and customer
            and (customer["customer_type"] or "").strip().upper() == "WALKIN"
        ):
            customer = None
        pid = product["product_id" if company == "rmrg" else "item_id"]
        cid = customer["customer_id"] if customer else None
        session += 1
        sid = f"{run_id}-{session}"
        stamp = started - timedelta(seconds=cfg.events - len(base) + 30)
        payload = {
            "session_id": sid,
            "customer_id": cid,
            "product_id" if company == "rmrg" else "item_id": pid,
            "sku" if company == "rmrg" else "item_code": product[
                "sku" if company == "rmrg" else "item_code"
            ],
            "channel": "web" if company == "rmrg" else "assisted_store",
        }
        for kind, offset in (
            ("shopping-viewed", 0),
            ("shopping-added", rng.randint(2, 30)),
        ):
            if len(base) >= cfg.events or (offset and rng.random() > 0.35):
                break
            base.append(
                make_record(
                    env,
                    company,
                    kind,
                    f"session:{sid}",
                    sid,
                    stamp + timedelta(seconds=offset),
                    started,
                    {
                        **payload,
                        **(
                            {"quantity": rng.choices([1, 2, 3], [8, 2, 1])[0]}
                            if offset
                            else {}
                        ),
                    },
                    {"mode": "synthetic_session", "snapshot_fingerprint": fingerprint},
                )
            )
    deliveries: list[tuple[float, int, str, Record]] = []
    for i, record in enumerate(base):
        edge = "normal"
        delay = 0.0
        if rng.random() < cfg.late_fraction:
            delay += cfg.late_slots
            edge = "late"
        if rng.random() < cfg.reorder_fraction:
            delay += cfg.reorder_slots
            edge = "late+reordered" if delay > cfg.reorder_slots else "reordered"
        deliveries.append((i + delay, i, edge, record))
        if rng.random() < cfg.duplicate_fraction:
            deliveries.append((i + delay + 0.5, i, "duplicate", record))
    return [
        {"sequence": n, "generation_index": i, "edge_case": edge, "record": r.as_dict()}
        for n, (_, i, edge, r) in enumerate(
            sorted(deliveries, key=lambda v: (v[0], v[1])), 1
        )
    ]
