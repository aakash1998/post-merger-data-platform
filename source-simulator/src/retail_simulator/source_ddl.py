"""Executable approved constraints; render reviewable, packaged SQL artifacts.

Cross-row transactional business commands remain the application's responsibility.
No trigger applies inventory deltas: controlled imports load the final snapshot.
"""

from pathlib import Path
from .contracts import SCHEMA, VOCABULARIES
from .snapshot import LOAD_ORDER
from .validation import FKS, UNIQUE

# Columns supporting composite ownership FKs, in addition to declared business keys.
OWNERSHIP = {
    "customer_addresses": [("customer_address_id", "customer_id")],
    "orders": [("order_id", "customer_id")],
    "order_addresses": [("order_address_id", "order_id", "address_role")],
    "order_items": [("order_item_id", "order_id")],
    "payments": [("payment_id", "order_id")],
    "shipments": [("shipment_id", "order_id")],
    "shipment_items": [("shipment_item_id", "order_item_id", "order_id")],
    "returns": [("return_id", "order_id")],
    "return_items": [("return_item_id", "return_id", "order_item_id", "order_id")],
}
# (unique, columns/expression, predicate). Explicit approved secondary/partial indexes.
INDEXES = {
    "customers": [
        (False, "lower(email)", "email IS NOT NULL"),
        (False, "lifecycle_status, customer_id", None),
    ],
    "customer_addresses": [
        (False, "customer_id, archived_at", None),
        (True, "customer_id", "is_default_shipping AND archived_at IS NULL"),
        (True, "customer_id", "is_default_billing AND archived_at IS NULL"),
    ],
    "product_categories": [
        (False, "parent_category_id, sort_order, category_id", None)
    ],
    "products": [
        (False, "category_id, lifecycle_status", None),
        (False, "style_code", "style_code IS NOT NULL"),
    ],
    "stores": [(False, "lifecycle_status, country_code, region", None)],
    "warehouses": [(False, "lifecycle_status, warehouse_type", None)],
    "inventory": [
        (False, "store_id, product_id", "store_id IS NOT NULL"),
        (False, "warehouse_id, product_id", "warehouse_id IS NOT NULL"),
    ],
    "orders": [
        (False, "customer_id, placed_at, order_id", None),
        (False, "origin_store_id, placed_at", None),
        (False, "order_status, placed_at", None),
        (False, "placed_at, order_id", None),
    ],
    "order_addresses": [
        (False, "source_customer_address_id, source_customer_id", None),
        (False, "order_id, source_customer_id", None),
    ],
    "order_items": [
        (False, "product_id, order_id", None),
        (False, "requested_pickup_store_id", "requested_pickup_store_id IS NOT NULL"),
    ],
    "payments": [
        (False, "order_id, attempted_at, payment_id", None),
        (False, "parent_payment_id, order_id", None),
        (False, "return_id, order_id", None),
        (False, "attempted_at", "payment_status = 'pending'"),
    ],
    "payment_allocations": [
        (
            True,
            "payment_id, order_item_id, allocation_type",
            "order_item_id IS NOT NULL AND return_item_id IS NULL",
        ),
        (
            True,
            "payment_id, return_item_id, allocation_type",
            "return_item_id IS NOT NULL",
        ),
        (True, "payment_id, allocation_type", "order_item_id IS NULL"),
        (False, "payment_id, order_id", None),
        (False, "order_item_id, order_id", None),
        (False, "return_item_id, return_id, order_item_id, order_id", None),
        (False, "order_id, payment_allocation_id", None),
    ],
    "shipments": [
        (False, "order_id, planned_at", None),
        (False, "origin_store_id, shipment_status", None),
        (False, "origin_warehouse_id, shipment_status", None),
        (False, "shipping_address_id, order_id, shipping_address_role", None),
        (False, "shipment_status, planned_at", None),
    ],
    "shipment_items": [
        (False, "shipment_id, order_id", None),
        (False, "order_item_id, order_id", None),
        (False, "order_id, shipment_item_id", None),
    ],
    "returns": [
        (False, "order_id, requested_at", None),
        (False, "receiving_store_id, return_status", None),
        (False, "receiving_warehouse_id, return_status", None),
        (False, "return_status, requested_at", None),
    ],
    "return_items": [
        (False, "return_id, order_id", None),
        (False, "order_item_id, order_id", None),
        (False, "shipment_item_id, order_item_id, order_id", None),
        (False, "order_id, return_item_id", None),
    ],
    "stock_movements": [
        (False, "inventory_id, occurred_at, stock_movement_id", None),
        (False, "shipment_item_id", "shipment_item_id IS NOT NULL"),
        (False, "return_item_id", "return_item_id IS NOT NULL"),
    ],
}
SCC_INDEXES = {
    "customer_master": ["customer_code", "email_address", "active_flag, customer_id"],
    "item_master": ["item_code", "barcode", "department_code, active_flag"],
    "locations": ["location_code", "location_type, active_flag"],
    "sales_orders": [
        "location_id, business_date, order_number",
        "business_date, sales_order_id",
        "order_number",
        "customer_id_ref",
        "customer_code_ref",
        "order_status, business_date",
    ],
    "sales_order_lines": ["item_id_ref", "item_code_ref"],
    "payment_transactions": [
        "sales_order_id, transaction_date",
        "location_id, transaction_date",
        "receipt_number",
        "order_number_ref",
        "reference_text",
        "reversal_of_id_ref",
    ],
    "stock_balance": ["item_id, location_id", "location_id, item_id", "balance_as_of"],
}
DEFAULTS = {
    "preferred_language": "'en-CA'",
    "loyalty_tier": "'none'",
    "marketing_opt_in": "false",
    "is_default_shipping": "false",
    "is_default_billing": "false",
    "sort_order": "0",
    "is_active": "true",
    "quantity_cancelled": "0",
    "created_at": "CURRENT_TIMESTAMP",
    "updated_at": "CURRENT_TIMESTAMP",
    "row_version": "1",
}
STATUS_DEFAULTS = {
    "orders": ("order_status", "draft"),
    "order_items": ("line_status", "open"),
    "shipments": ("shipment_status", "planned"),
    "returns": ("return_status", "requested"),
    "payments": ("payment_status", "pending"),
}
CHECKS = {
    "customers": [
        "(anonymized_at IS NOT NULL) = (lifecycle_status = 'anonymized')",
        "lifecycle_status <> 'anonymized' OR (email IS NULL AND phone IS NULL AND NOT marketing_opt_in)",
        "anonymized_at >= registered_at",
        "archived_at >= registered_at",
    ],
    "customer_addresses": [
        "archived_at IS NULL OR (NOT is_default_shipping AND NOT is_default_billing)",
        "archived_at >= created_at",
    ],
    "product_categories": [
        "parent_category_id <> category_id",
        "sort_order >= 0",
        "archived_at IS NULL OR NOT is_active",
        "archived_at >= created_at",
    ],
    "products": [
        "weight_kg > 0",
        "lifecycle_status <> 'active' OR launched_at IS NOT NULL",
        "(discontinued_at IS NOT NULL) = (lifecycle_status = 'discontinued')",
        "discontinued_at >= launched_at",
    ],
    "stores": [
        "lifecycle_status = 'planned' OR opened_on IS NOT NULL",
        "(closed_on IS NOT NULL) = (lifecycle_status = 'closed')",
        "closed_on >= opened_on",
    ],
    "warehouses": [
        "lifecycle_status = 'planned' OR opened_on IS NOT NULL",
        "(closed_on IS NOT NULL) = (lifecycle_status = 'closed')",
        "closed_on >= opened_on",
    ],
    "inventory": [
        "(store_id IS NULL) <> (warehouse_id IS NULL)",
        "quantity_on_hand >= 0",
        "quantity_reserved >= 0",
        "quantity_unavailable >= 0",
        "reorder_point >= 0",
        "target_stock_level >= reorder_point",
        "quantity_reserved::bigint + quantity_unavailable::bigint <= quantity_on_hand",
    ],
    "orders": [
        "(origin_store_id IS NOT NULL) = (channel = 'store')",
        "discount_total <= merchandise_subtotal",
        "order_total = merchandise_subtotal - discount_total + merchandise_tax_total + shipping_amount + shipping_tax_amount",
        "(placed_at IS NULL) = (order_status = 'draft')",
        "(cancelled_at IS NOT NULL) = (order_status = 'cancelled')",
        "(closed_at IS NOT NULL) = (order_status = 'closed')",
        "cancelled_at >= placed_at",
        "closed_at >= placed_at",
    ],
    "order_addresses": [
        "(source_customer_id IS NULL) = (source_customer_address_id IS NULL)"
    ],
    "order_items": [
        "line_number > 0",
        "quantity_ordered > 0",
        "quantity_cancelled BETWEEN 0 AND quantity_ordered",
        "gross_amount = quantity_ordered::numeric * unit_price",
        "discount_amount <= gross_amount",
        "tax_rate_percent BETWEEN 0 AND 100",
        "tax_amount = round((gross_amount - discount_amount) * tax_rate_percent / 100, 2)",
        "line_total = gross_amount - discount_amount + tax_amount",
        "(quantity_cancelled = quantity_ordered) = (line_status = 'cancelled')",
        "(requested_pickup_store_id IS NOT NULL) = (requested_fulfillment = 'pickup')",
    ],
    "payments": [
        "amount > 0",
        "parent_payment_id <> payment_id",
        "operation_type NOT IN ('refund','void') OR parent_payment_id IS NOT NULL",
        "operation_type <> 'authorization' OR parent_payment_id IS NULL",
        "return_id IS NULL OR operation_type = 'refund'",
        "payment_method <> 'cash' OR operation_type IN ('capture','refund')",
        "payment_status <> 'succeeded' OR payment_method = 'cash' OR provider_transaction_id IS NOT NULL",
        "(failure_code IS NOT NULL) = (payment_status = 'failed')",
        "(processed_at IS NULL) = (payment_status = 'pending')",
        "processed_at >= attempted_at",
    ],
    "payment_allocations": [
        "amount > 0",
        "(order_item_id IS NOT NULL) = (allocation_type IN ('merchandise','tax'))",
        "(return_id IS NULL) = (return_item_id IS NULL)",
        "return_item_id IS NULL OR order_item_id IS NOT NULL",
    ],
    "shipments": [
        "(origin_store_id IS NULL) <> (origin_warehouse_id IS NULL)",
        "fulfillment_type = 'ship' OR origin_store_id IS NOT NULL",
        "(shipping_address_id IS NOT NULL) = (fulfillment_type = 'ship')",
        "(shipping_address_role IS NOT NULL) = (fulfillment_type = 'ship')",
        "(carrier IS NULL) = (tracking_number IS NULL)",
        "fulfillment_type = 'ship' OR carrier IS NULL",
        "fulfillment_type <> 'ship' OR shipment_status NOT IN ('handed_over','delivered') OR carrier IS NOT NULL",
        "shipment_status NOT IN ('ready','handed_over','delivered') OR ready_at IS NOT NULL",
        "shipment_status NOT IN ('handed_over','delivered') OR handed_over_at IS NOT NULL",
        "shipment_status <> 'delivered' OR delivered_at IS NOT NULL",
        "shipment_status NOT IN ('planned','allocated','ready','cancelled') OR (handed_over_at IS NULL AND delivered_at IS NULL)",
        "(cancelled_at IS NOT NULL) = (shipment_status = 'cancelled')",
        "delivered_at IS NULL OR handed_over_at IS NOT NULL",
        "ready_at >= planned_at",
        "handed_over_at >= planned_at",
        "handed_over_at >= ready_at",
        "delivered_at >= handed_over_at",
        "cancelled_at >= planned_at",
        "fulfillment_type = 'ship' OR handed_over_at IS NULL OR (shipment_status = 'delivered' AND delivered_at = handed_over_at)",
    ],
    "shipment_items": ["quantity > 0"],
    "returns": [
        "(receiving_store_id IS NULL) <> (receiving_warehouse_id IS NULL)",
        "return_channel <> 'store' OR receiving_store_id IS NOT NULL",
        "refund_total = merchandise_refund_amount + tax_refund_amount + shipping_refund_amount + shipping_tax_refund_amount",
        "return_status NOT IN ('authorized','partially_received','received','closed') OR authorized_at IS NOT NULL",
        "return_status NOT IN ('partially_received','received','closed') OR first_received_at IS NOT NULL",
        "return_status NOT IN ('received','closed') OR fully_received_at IS NOT NULL",
        "return_status NOT IN ('requested','rejected','cancelled') OR (first_received_at IS NULL AND fully_received_at IS NULL)",
        "return_status <> 'rejected' OR authorized_at IS NULL",
        "(resolved_at IS NOT NULL) = (return_status IN ('rejected','cancelled','closed'))",
    ],
    "return_items": [
        "quantity_requested > 0",
        "quantity_authorized BETWEEN 0 AND quantity_requested",
        "quantity_received BETWEEN 0 AND quantity_authorized",
        "quantity_restocked >= 0",
        "quantity_disposed >= 0",
        "quantity_restocked::bigint + quantity_disposed::bigint <= quantity_received",
        "(last_received_at IS NOT NULL) = (quantity_received > 0)",
        "(inspected_at IS NULL) = (disposition = 'pending')",
        "inspected_at >= last_received_at",
        "disposition = 'pending' OR (quantity_received > 0 AND quantity_restocked::bigint + quantity_disposed::bigint = quantity_received)",
        "disposition <> 'restock' OR quantity_disposed = 0",
        "disposition <> 'dispose' OR quantity_restocked = 0",
        "disposition <> 'mixed' OR (quantity_restocked > 0 AND quantity_disposed > 0)",
        "quantity_authorized <> 0 OR (merchandise_refund_amount = 0 AND tax_refund_amount = 0)",
    ],
    "stock_movements": [
        "quantity_delta <> 0 OR reserved_delta <> 0 OR unavailable_delta <> 0",
        "(transfer_id IS NOT NULL) = (movement_type IN ('transfer_in','transfer_out'))",
        "(reverses_movement_id IS NOT NULL) = (movement_type = 'reversal')",
        "reverses_movement_id <> stock_movement_id",
        "shipment_item_id IS NULL OR return_item_id IS NULL",
        "movement_type <> 'sale' OR shipment_item_id IS NOT NULL",
        "movement_type <> 'return' OR return_item_id IS NOT NULL",
        "(source_document_type IS NULL) = (reference_number IS NULL)",
        "movement_type NOT IN ('opening','receipt','return','transfer_in') OR (quantity_delta > 0 AND reserved_delta = 0 AND unavailable_delta = 0)",
        "movement_type <> 'transfer_out' OR (quantity_delta < 0 AND reserved_delta = 0 AND unavailable_delta = 0)",
        "movement_type <> 'sale' OR (quantity_delta < 0 AND reserved_delta BETWEEN quantity_delta AND 0 AND unavailable_delta = 0)",
        "movement_type NOT IN ('reserve','release') OR (quantity_delta = 0 AND unavailable_delta = 0 AND ((movement_type = 'reserve' AND reserved_delta > 0) OR (movement_type = 'release' AND reserved_delta < 0)))",
        "movement_type NOT IN ('quarantine','unquarantine') OR (quantity_delta = 0 AND reserved_delta = 0 AND ((movement_type = 'quarantine' AND unavailable_delta > 0) OR (movement_type = 'unquarantine' AND unavailable_delta < 0)))",
        "movement_type <> 'adjustment' OR (quantity_delta <> 0 AND reserved_delta = 0 AND unavailable_delta = 0)",
    ],
}
# All present return milestones are ordered even when intermediate values are absent.
_times = [
    "requested_at",
    "authorized_at",
    "first_received_at",
    "fully_received_at",
    "resolved_at",
]
CHECKS["returns"] += [
    f"{b} >= {a}" for i, a in enumerate(_times) for b in _times[i + 1 :]
]

AUDIT_FUNCTION = """CREATE FUNCTION rmrg.maintain_audit() RETURNS trigger LANGUAGE plpgsql AS $audit$
BEGIN
    IF to_jsonb(NEW)->TG_ARGV[0] IS DISTINCT FROM to_jsonb(OLD)->TG_ARGV[0] THEN
        RAISE EXCEPTION 'Source primary key is immutable';
    END IF;
    IF NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
        RAISE EXCEPTION 'Creation audit is immutable';
    END IF;
    IF TG_TABLE_NAME = 'inventory' THEN
        IF (to_jsonb(NEW)->'product_id') IS DISTINCT FROM (to_jsonb(OLD)->'product_id')
           OR (to_jsonb(NEW)->'store_id') IS DISTINCT FROM (to_jsonb(OLD)->'store_id')
           OR (to_jsonb(NEW)->'warehouse_id') IS DISTINCT FROM (to_jsonb(OLD)->'warehouse_id') THEN
            RAISE EXCEPTION 'Inventory grain is immutable';
        END IF;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['updated_at','row_version','updated_by'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['updated_at','row_version','updated_by']) THEN
        NEW.updated_at := greatest(clock_timestamp(), OLD.updated_at);
        NEW.row_version := OLD.row_version + 1;
    ELSE
        NEW.updated_at := OLD.updated_at;
        NEW.row_version := OLD.row_version;
        NEW.updated_by := OLD.updated_by;
    END IF;
    RETURN NEW;
END
$audit$"""


def statements(company: str) -> list[str]:
    """DDL in FK-safe order, with no IF NOT EXISTS hiding unknown objects."""
    pg = company == "rmrg"
    quote = '"' if pg else "`"

    def q(value: str) -> str:
        return quote + value + quote

    result = [
        (
            "CREATE SCHEMA rmrg"
            if pg
            else "CREATE DATABASE scc CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
        )
    ]
    if pg:
        result.append(AUDIT_FUNCTION)
    for table in LOAD_ORDER[company]:
        columns = SCHEMA[company][table]
        pk = columns[0][0]
        definitions = []
        for name, kind, nullable in columns:
            suffix = ""
            if name == pk:
                suffix = (
                    " GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
                    if pg
                    else " AUTO_INCREMENT PRIMARY KEY"
                )
            elif pg:
                default = DEFAULTS.get(name)
                if STATUS_DEFAULTS.get(table, (None, None))[0] == name:
                    default = repr(STATUS_DEFAULTS[table][1])
                if default:
                    suffix += " DEFAULT " + default
            if not nullable:
                suffix += " NOT NULL"
            if not pg and name in {
                "customer_code",
                "item_code",
                "location_code",
                "customer_code_ref",
                "item_code_ref",
            }:
                kind += " COLLATE utf8mb4_bin"
            definitions.append(f"{q(name)} {kind}{suffix}")
        unique_keys = (
            (UNIQUE.get(table, []) + OWNERSHIP.get(table, []))
            if pg
            else (
                [("sales_order_id", "line_number")]
                if table == "sales_order_lines"
                else []
            )
        )
        indexes = (
            list(INDEXES.get(table, []))
            if pg
            else [(False, x, None) for x in SCC_INDEXES[table]]
        )
        # Nullable business keys use the exact partial predicates in the dictionaries.
        for key in unique_keys:
            nullable = {c[0] for c in columns if c[2]}
            if (
                pg
                and any(k in nullable for k in key)
                and key not in OWNERSHIP.get(table, [])
            ):
                indexes.append(
                    (
                        True,
                        ", ".join(key),
                        " AND ".join(f"{k} IS NOT NULL" for k in key if k in nullable),
                    )
                )
            else:
                definitions.append("UNIQUE (" + ", ".join(map(q, key)) + ")")
        for child, parent, parent_cols in FKS[company].get(table, []):
            definitions.append(
                f"FOREIGN KEY ({', '.join(map(q, child))}) REFERENCES {q(company)}.{q(parent)} ({', '.join(map(q, parent_cols))}) ON DELETE RESTRICT ON UPDATE RESTRICT"
            )
            prefixes = (
                [tuple(x.strip() for x in expr.split(",")) for _, expr, _ in indexes]
                + unique_keys
                + [(pk,)]
            )
            if not any(key[: len(child)] == child for key in prefixes):
                indexes.append((False, ", ".join(child), None))
        checks = (
            list(CHECKS[table])
            if pg
            else (["line_number > 0"] if table == "sales_order_lines" else [])
        )
        if pg:
            checks += [f"{pk} > 0", "row_version > 0", "updated_at >= created_at"]
            for name, kind, nullable in columns:
                if kind.startswith(("varchar", "char")):
                    checks.append(f"{q(name)} IS NULL OR btrim({q(name)}) <> ''")
                if kind.startswith("numeric") and name != "weight_kg":
                    checks.append(f"{q(name)} >= 0")
                if name == "currency_code":
                    checks.append("currency_code IN ('CAD','USD')")
                if name == "country_code":
                    checks.append("country_code ~ '^[A-Z]{2}$'")
                if name in {"phone", "contact_phone"}:
                    checks.append(f"{q(name)} ~ '^\\+[1-9][0-9]{{6,14}}$'")
                if name in {"email", "contact_email"}:
                    checks.append(f"{q(name)} = lower(btrim({q(name)}))")
                if name in {
                    "customer_number",
                    "category_code",
                    "sku",
                    "sku_snapshot",
                    "store_code",
                    "warehouse_code",
                    "order_number",
                    "shipment_number",
                    "return_number",
                    "style_code",
                }:
                    checks.append(
                        f"{q(name)} = upper(btrim({q(name)})) AND {q(name)} !~ '[^ -~]'"
                    )
                allowed = VOCABULARIES.get((table, name))
                if allowed:
                    checks.append(
                        f"{q(name)} IN ({', '.join(repr(v) for v in sorted(allowed))})"
                    )
        definitions += [
            f"CONSTRAINT {q(table + '_ck_' + str(i))} CHECK ({check})"
            for i, check in enumerate(checks)
        ]
        result.append(
            f"CREATE TABLE {q(company)}.{q(table)} (\n    "
            + ",\n    ".join(definitions)
            + "\n)"
            + (
                ""
                if pg
                else " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
            )
        )
        for i, (unique_index, expression, predicate) in enumerate(indexes):
            result.append(
                f"CREATE {'UNIQUE ' if unique_index else ''}INDEX {q(table + '_ix_' + str(i))} ON {q(company)}.{q(table)} ({expression})"
                + (" WHERE " + predicate if predicate else "")
            )
        if pg:
            result.append(
                f"CREATE TRIGGER {q(table + '_audit')} BEFORE UPDATE ON rmrg.{q(table)} FOR EACH ROW EXECUTE FUNCTION rmrg.maintain_audit('{pk}')"
            )
        else:
            result.append(
                f"CREATE TRIGGER scc.{q(table + '_immutable_pk')} BEFORE UPDATE ON scc.{q(table)} FOR EACH ROW BEGIN IF NEW.{q(pk)} <> OLD.{q(pk)} THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Source primary key is immutable'; END IF; END"
            )
    return result


def render(company: str) -> str:
    # MySQL client delimiters are only needed around trigger bodies. DBAPI uses statements().
    chunks = []
    for sql in statements(company):
        if company == "scc" and sql.startswith("CREATE TRIGGER"):
            chunks.append("DELIMITER $$\n" + sql + "$$\nDELIMITER ;")
        else:
            chunks.append(sql + ";")
    return (
        "-- KAN-32: generated from source_ddl.py and approved schema.json.\n"
        + "\n\n".join(chunks)
        + "\n"
    )


if __name__ == "__main__":
    for co in SCHEMA:
        Path(__file__).with_name("ddl").joinpath(co + ".sql").write_text(
            render(co), encoding="utf-8"
        )
