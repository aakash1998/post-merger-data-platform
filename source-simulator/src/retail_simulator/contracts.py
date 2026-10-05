"""Column/type contracts copied from the approved dictionaries; no DDL."""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from importlib.resources import files
import json
import re
from typing import Any

Row = dict[str, Any]
SCHEMA: dict[str, dict[str, list[list[Any]]]] = json.loads(
    files("retail_simulator").joinpath("schema.json").read_text(encoding="utf-8")
)
ZERO = Decimal("0.00")
VOCABULARIES = {
    ("customers", "preferred_language"): {"en-CA", "fr-CA", "en-US"},
    ("customers", "loyalty_tier"): {"none", "silver", "gold", "platinum"},
    ("customers", "lifecycle_status"): {"active", "inactive", "anonymized"},
    ("products", "lifecycle_status"): {"draft", "active", "discontinued"},
    ("products", "unit_of_measure"): {"each"},
    ("stores", "store_type"): {"full_service", "outlet", "popup"},
    ("stores", "lifecycle_status"): {"planned", "open", "temporarily_closed", "closed"},
    ("warehouses", "warehouse_type"): {"distribution", "fulfillment", "returns"},
    ("warehouses", "lifecycle_status"): {
        "planned",
        "active",
        "temporarily_closed",
        "closed",
    },
    ("orders", "channel"): {"store", "web", "mobile", "call_center"},
    ("orders", "fulfillment_preference"): {"ship", "pickup", "carryout", "mixed"},
    ("orders", "order_status"): {
        "draft",
        "placed",
        "processing",
        "partially_fulfilled",
        "fulfilled",
        "cancelled",
        "closed",
    },
    ("order_addresses", "address_role"): {"billing", "shipping"},
    ("order_items", "line_status"): {
        "open",
        "partially_fulfilled",
        "fulfilled",
        "cancelled",
        "closed",
    },
    ("order_items", "requested_fulfillment"): {"ship", "pickup", "carryout"},
    ("payments", "operation_type"): {"authorization", "capture", "refund", "void"},
    ("payments", "payment_method"): {"card", "cash", "gift_card", "wallet"},
    ("payments", "payment_status"): {"pending", "succeeded", "failed"},
    ("payment_allocations", "allocation_type"): {
        "merchandise",
        "tax",
        "shipping",
        "shipping_tax",
    },
    ("shipments", "fulfillment_type"): {"ship", "pickup", "carryout"},
    ("shipments", "shipment_status"): {
        "planned",
        "allocated",
        "ready",
        "handed_over",
        "delivered",
        "cancelled",
    },
    ("shipments", "shipping_address_role"): {"shipping"},
    ("returns", "return_status"): {
        "requested",
        "authorized",
        "partially_received",
        "received",
        "rejected",
        "cancelled",
        "closed",
    },
    ("returns", "return_channel"): {"store", "mail"},
    ("return_items", "reason_code"): {
        "changed_mind",
        "wrong_size",
        "damaged",
        "defective",
        "wrong_item",
        "other",
    },
    ("return_items", "disposition"): {"pending", "restock", "dispose", "mixed"},
    ("stock_movements", "movement_type"): {
        "opening",
        "receipt",
        "sale",
        "return",
        "transfer_out",
        "transfer_in",
        "adjustment",
        "reserve",
        "release",
        "quarantine",
        "unquarantine",
        "reversal",
    },
    ("stock_movements", "reason_code"): {
        "initial_load",
        "purchase_receipt",
        "fulfillment",
        "customer_return",
        "location_transfer",
        "cycle_count",
        "damage",
        "allocation",
        "allocation_release",
        "quality_release",
        "correction",
    },
    ("stock_movements", "source_document_type"): {
        "purchase_receipt",
        "cycle_count",
        "damage_report",
        "adjustment",
    },
}


def money(value: Any) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported value type {type(value)}")


def row(company: str, table: str, stamp: datetime, **values: Any) -> Row:
    result = {column: None for column, _, _ in SCHEMA[company][table]}
    if not values.keys() <= result.keys():
        raise ValueError(
            f"Unknown column in {company}.{table}: {values.keys() - result.keys()}"
        )
    result.update(values)
    result.update(created_at=stamp, updated_at=stamp, updated_by="seed-generator")
    if company == "rmrg":
        result.update(row_version=1, created_by="seed-generator")
    validate_row(company, table, result)
    return result


def validate_row(company: str, table: str, value: Row) -> None:
    columns = SCHEMA[company][table]
    if set(value) != {c[0] for c in columns}:
        raise ValueError(f"Column mismatch: {company}.{table}")
    for name, sqltype, nullable in columns:
        v = value[name]
        label = f"{company}.{table}.{name}"
        if v is None:
            if not nullable:
                raise ValueError(f"Required column {label}")
            continue
        kind = sqltype.lower()
        bounded = re.fullmatch(r"(?:varchar|char)\((\d+)\)", kind)
        decimal = re.fullmatch(r"(?:numeric|decimal)\((\d+),(\d+)\)", kind)
        if bounded:
            if not isinstance(v, str) or len(v) > int(bounded[1]):
                raise ValueError(f"Text length/type: {label}")
            if company == "rmrg" and not v.strip():
                raise ValueError(f"Blank mature-source text: {label}")
        elif decimal:
            p, s = int(decimal[1]), int(decimal[2])
            if (
                not isinstance(v, Decimal)
                or not v.is_finite()
                or abs(v) >= Decimal(10) ** (p - s)
            ):
                raise ValueError(f"Decimal range/type: {label}")
            if v != v.quantize(Decimal(10) ** -s):
                raise ValueError(f"Decimal scale: {label}")
        elif "int" in kind:
            bits = 16 if "smallint" in kind else 64 if "bigint" in kind else 32
            unsigned = "unsigned" in kind
            low, high = (
                (0, 2**bits - 1)
                if unsigned
                else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
            )
            if type(v) is not int or not low <= v <= high:
                raise ValueError(f"Integer range/type: {label}")
        elif kind == "boolean":
            if type(v) is not bool:
                raise ValueError(f"Boolean type: {label}")
        elif kind == "date":
            if type(v) is not date:
                raise ValueError(f"Date type: {label}")
        elif kind in {"datetime", "timestamp with time zone"}:
            if not isinstance(v, datetime) or (v.tzinfo is not None) != (
                company == "rmrg"
            ):
                raise ValueError(f"Timestamp timezone/type: {label}")
            if company == "scc" and v.microsecond:
                raise ValueError(f"Legacy timestamp precision: {label}")
        elif kind == "uuid":
            from uuid import UUID

            UUID(str(v))
        else:
            raise ValueError(f"Unrecognized approved type: {sqltype}")
        if company == "rmrg":
            allowed = VOCABULARIES.get((table, name))
            if allowed is not None and v not in allowed:
                raise ValueError(f"Unknown source vocabulary: {label}")
            if decimal and v < 0:
                raise ValueError(f"Negative mature-source decimal: {label}")
            if name == "tax_rate_percent" and not 0 <= v <= 100:
                raise ValueError("Tax rate outside approved range")
    if value[columns[0][0]] <= 0:
        raise ValueError(f"Nonpositive identity: {company}.{table}")
    if company == "rmrg":
        if value["row_version"] <= 0 or value["updated_at"] < value["created_at"]:
            raise ValueError("Invalid mature-source audit values")
        for k, v in value.items():
            if k.endswith("currency_code") and v not in ("CAD", "USD"):
                raise ValueError("Unsupported source currency")
            if k == "phone" or k == "contact_phone":
                if v is not None and not re.fullmatch(r"\+[1-9]\d{6,14}", v):
                    raise ValueError("Phone must be E.164")
    if table in {"order_items", "sales_order_lines"} and value["line_number"] <= 0:
        raise ValueError("Line number must be positive")
