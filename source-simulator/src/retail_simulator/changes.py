"""Source transactions and state validation shared by persistence adapters."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import json
from typing import Any

from .contracts import Row, SCHEMA, validate_row
from .snapshot import verify
from .validation import FKS, UNIQUE, Validator, require, unique

Database = dict[str, dict[str, dict[int, Row]]]


def decode_row(company: str, table: str, value: Row) -> Row:
    result = dict(value)
    for name, sqltype, _ in SCHEMA[company][table]:
        if result[name] is None:
            continue
        kind = sqltype.lower()
        if kind.startswith(("decimal", "numeric")):
            result[name] = Decimal(result[name])
        elif kind in {"datetime", "timestamp with time zone"}:
            result[name] = datetime.fromisoformat(result[name])
        elif kind == "date":
            result[name] = date.fromisoformat(result[name])
    validate_row(company, table, result)
    return result


def load_seed(path: Path, env: str) -> Database:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["environment"] == env, "Seed and runtime environment must match")
    verify(path, manifest)
    result: Database = {
        company: {table: {} for table in tables} for company, tables in SCHEMA.items()
    }
    for company, tables in result.items():
        for table, rows in tables.items():
            pk = SCHEMA[company][table][0][0]
            with (path / company / f"{table}.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    value = decode_row(company, table, json.loads(line))
                    require(value[pk] not in rows, "Duplicate baseline identity")
                    rows[value[pk]] = value
    validate_state(result)
    return result


@dataclass(frozen=True)
class Change:
    table: str
    pk: int
    before: Row | None
    after: Row | None

    @property
    def operation(self) -> str:
        return (
            "insert"
            if self.before is None
            else "delete" if self.after is None else "update"
        )


@dataclass(frozen=True)
class Transaction:
    sequence: int
    company: str
    activity: str
    changes: tuple[Change, ...]
    highwater: dict[str, int]


def check_transition(company: str, change: Change, data: Database) -> None:
    old, new = change.before, change.after
    require(old is not None or new is not None, "Empty change")
    if new is not None:
        validate_row(company, change.table, new)
        require(
            new[SCHEMA[company][change.table][0][0]] == change.pk,
            "Source identity cannot change",
        )
    if company != "rmrg" or old is None:
        return
    if new is None:
        require(
            change.table in {"orders", "order_items", "order_addresses"},
            "RMRG operational history is retained",
        )
        oid = old.get("order_id")
        require(
            data["rmrg"]["orders"][oid]["order_status"] == "draft",
            "Only unaccepted drafts can be removed",
        )
        return
    require(
        new["created_at"] == old["created_at"]
        and new["created_by"] == old["created_by"],
        "Creation audit is immutable",
    )
    require(
        new["row_version"] == old["row_version"] + 1
        and new["updated_at"] >= old["updated_at"],
        "Audit version/time progression",
    )
    changed = {k for k in old if old[k] != new[k]} - {
        "updated_at",
        "updated_by",
        "row_version",
    }
    if change.table == "orders" and old["placed_at"] is not None:
        require(
            changed <= {"order_status", "cancelled_at", "closed_at"},
            "Accepted commercial header is immutable",
        )
    if (
        change.table == "order_items"
        and data["rmrg"]["orders"][old["order_id"]]["placed_at"] is not None
    ):
        require(
            changed <= {"quantity_cancelled", "line_status"},
            "Accepted commercial line is immutable",
        )
    if change.table == "payments":
        require(old["payment_status"] == "pending", "Terminal payment is immutable")
        require(
            changed
            <= {
                "payment_status",
                "failure_code",
                "processed_at",
                "provider_transaction_id",
            },
            "Payment request is immutable",
        )
        require(
            new["payment_status"] in {"succeeded", "failed"},
            "Payment must resolve once",
        )
    if change.table in {
        "stock_movements",
        "payment_allocations",
        "shipment_items",
        "order_addresses",
    }:
        require(
            not changed,
            "Posted lineage/commercial evidence is immutable in this simulator",
        )


def apply_changes(data: Database, tx: Transaction) -> Database:
    require(
        tx.company in SCHEMA and bool(tx.changes),
        "Transaction must have one company and changes",
    )
    result = dict(data)
    result[tx.company] = dict(data[tx.company])
    touched = {c.table for c in tx.changes}
    for table in touched:
        require(table in SCHEMA[tx.company], "Unknown source table")
        result[tx.company][table] = dict(data[tx.company][table])
    seen = set()
    for change in tx.changes:
        require(
            (change.table, change.pk) not in seen,
            "One final change per source row per transaction",
        )
        seen.add((change.table, change.pk))
        require(
            data[tx.company][change.table].get(change.pk) == change.before,
            "Stale before-image/conflicting writer",
        )
        check_transition(tx.company, change, data)
        if change.after is None:
            del result[tx.company][change.table][change.pk]
        else:
            result[tx.company][change.table][change.pk] = dict(change.after)
    validate_state(result, tx)
    return result


def validate_state(data: Database, tx: Transaction | None = None) -> None:
    companies = [tx.company] if tx else list(SCHEMA)
    masters = {
        co: {t: list(rows.values()) for t, rows in tables.items()}
        for co, tables in data.items()
    }
    for company in companies:
        tables = masters[company]
        keys: dict[tuple[str, tuple[str, ...]], set[tuple[Any, ...]]] = {}
        for table, rows in tables.items():
            if tx is None:
                for value in rows:
                    validate_row(company, table, value)
            for child, parent, columns in FKS[company].get(table, []):
                cache = (parent, columns)
                if cache not in keys:
                    keys[cache] = {tuple(p[c] for c in columns) for p in tables[parent]}
                for value in rows:
                    key = tuple(value[c] for c in child)
                    if all(v is not None for v in key):
                        require(
                            key in keys[cache],
                            f"Broken enforced FK: {company}.{table} -> {parent}",
                        )
            if company == "rmrg":
                for columns in UNIQUE.get(table, []):
                    unique(rows, columns)
        if company == "scc":
            unique(tables["sales_order_lines"], ("sales_order_id", "line_number"))
            continue
        validator = Validator(masters)
        validator.bundle(
            "rmrg",
            {
                t: tables[t]
                for t in (
                    "customers",
                    "customer_addresses",
                    "product_categories",
                    "products",
                    "stores",
                    "warehouses",
                    "inventory",
                )
            },
        )
        oids = (
            set(data["rmrg"]["orders"])
            if tx is None
            else {
                r["order_id"]
                for c in tx.changes
                for r in (c.before, c.after)
                if r is not None and "order_id" in r
            }
        )
        if tx:
            for change in tx.changes:
                if change.table == "stock_movements":
                    for movement in (change.before, change.after):
                        if movement is None:
                            continue
                        for key, parent in (
                            ("shipment_item_id", "shipment_items"),
                            ("return_item_id", "return_items"),
                        ):
                            if (
                                movement[key] is not None
                                and movement[key] in data["rmrg"][parent]
                            ):
                                oids.add(
                                    data["rmrg"][parent][movement[key]]["order_id"]
                                )
        for oid in oids:
            if oid not in data["rmrg"]["orders"]:
                continue
            bundle = {
                t: [r for r in rows if r.get("order_id") == oid]
                for t, rows in tables.items()
                if t not in {"stock_movements", "inventory"}
            }
            ship_ids = {r["shipment_item_id"] for r in bundle["shipment_items"]}
            return_ids = {r["return_item_id"] for r in bundle["return_items"]}
            bundle["stock_movements"] = [
                m
                for m in tables["stock_movements"]
                if m["shipment_item_id"] in ship_ids
                or m["return_item_id"] in return_ids
            ]
            validator.bundle("rmrg", bundle)
            if data["rmrg"]["orders"][oid]["order_status"] == "fulfilled":
                require(
                    all(
                        r["line_status"] in {"fulfilled", "closed", "cancelled"}
                        for r in bundle["order_items"]
                    ),
                    "Fulfilled order has outstanding lines",
                )
            for ri in bundle["return_items"]:
                inspection_balance = sum(
                    m["unavailable_delta"]
                    for m in bundle["stock_movements"]
                    if m["return_item_id"] == ri["return_item_id"]
                )
                require(
                    inspection_balance
                    == ri["quantity_received"]
                    - ri["quantity_restocked"]
                    - ri["quantity_disposed"],
                    "Return quarantine/disposition reconciliation",
                )
            for si in bundle["shipment_items"]:
                candidates = [
                    r
                    for r in bundle["return_items"]
                    if r["shipment_item_id"] == si["shipment_item_id"]
                    and data["rmrg"]["returns"][r["return_id"]]["return_status"]
                    not in {"rejected", "cancelled"}
                ]
                require(
                    sum(r["quantity_authorized"] for r in candidates) <= si["quantity"],
                    "Cumulative overreturn",
                )
            order = data["rmrg"]["orders"][oid]
            if order["order_status"] == "cancelled":
                require(
                    all(
                        r["quantity_cancelled"] == r["quantity_ordered"]
                        for r in bundle["order_items"]
                    ),
                    "Cancelled order quantities",
                )
                require(
                    not any(s["handed_over_at"] for s in bundle["shipments"]),
                    "Cannot cancel handed-over sale",
                )
        validator.rmrg(
            {
                "stock_movements": [
                    m
                    for m in tables["stock_movements"]
                    if m["shipment_item_id"] is None and m["return_item_id"] is None
                ]
            }
        )
        balances: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
        for movement in tables["stock_movements"]:
            for i, name in enumerate(
                ("quantity_delta", "reserved_delta", "unavailable_delta")
            ):
                balances[movement["inventory_id"]][i] += movement[name]
        for inv in tables["inventory"]:
            require(
                balances[inv["inventory_id"]]
                == [
                    inv["quantity_on_hand"],
                    inv["quantity_reserved"],
                    inv["quantity_unavailable"],
                ],
                "Inventory ledger reconciliation",
            )
