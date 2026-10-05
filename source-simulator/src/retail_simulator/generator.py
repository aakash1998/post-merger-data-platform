"""Weighted retail workloads; transaction facts stream one order at a time."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import random
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .config import Config
from .contracts import Row, ZERO, money, row

Bundle = dict[str, list[Row]]
FIRST = ("Alex", "Morgan", "Jordan", "Taylor", "Sam", "Casey", "Avery", "Robin")
LAST = ("Chen", "Singh", "Martin", "Brown", "Roy", "Wilson", "Campbell", "Nguyen")
CITIES = (
    ("Calgary", "AB", "T2P 1J9"),
    ("Edmonton", "AB", "T5J 0K1"),
    ("Red Deer", "AB", "T4N 1X5"),
    ("Lethbridge", "AB", "T1J 0N9"),
)
CATALOG = (
    ("Thermal Shirt", "APPAREL", "M", "Navy", "39.95"),
    ("Trail Bottle 500ml", "OUTDOOR", "500ml", "Green", "24.50"),
    ("Work Glove", "APPAREL", "L", "Black", "19.99"),
    ("Camping Mug", "OUTDOOR", "350ml", "Blue", "14.95"),
    ("Storage Box", "HOME", "10L", "Grey", "12.49"),
    ("Tea Towel", "HOME", "Standard", "White", "8.95"),
)


def gtin(i: int) -> str:
    """Synthetic checksum-valid EAN-13; not a claim of a GS1 assignment."""
    body = f"200{i:09d}"
    check = (-sum(int(v) * (1 if j % 2 == 0 else 3) for j, v in enumerate(body))) % 10
    return body + str(check)


class Generator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.random = random.Random(config.seed)
        self.start = datetime.combine(
            date.fromisoformat(config.start_date), datetime.min.time(), timezone.utc
        )
        self.snapshot = self.start + timedelta(days=config.days + 45)
        self.ids: dict[str, int] = defaultdict(int)
        self.masters: dict[str, Bundle] = {
            "rmrg": defaultdict(list),
            "scc": defaultdict(list),
        }
        self.truth: list[Row] = []
        self.balances: dict[tuple[int, str, int], Row] = {}
        self.pending_movements: list[Row] = []
        self.metrics: dict[str, int] = defaultdict(int)
        self.day_weights = [
            1.0
            + (1.8 if (self.start + timedelta(days=d)).month in (11, 12) else 0)
            + (0.5 if (self.start + timedelta(days=d)).weekday() >= 5 else 0)
            for d in range(config.days)
        ]
        self._masters()

    def id(self, table: str) -> int:
        self.ids[table] += 1
        return self.ids[table]

    def stamp(self) -> datetime:
        day = self.random.choices(range(self.config.days), weights=self.day_weights)[0]
        return self.start + timedelta(
            days=day,
            hours=self.random.randint(15, 23),
            minutes=self.random.randrange(60),
        )

    def weighted_id(self, count: int) -> int:
        # 20% of masters receive 65% of business; repeated customers and bestseller SKUs.
        if self.random.random() < 0.65:
            return self.random.randint(1, max(1, count // 5))
        return self.random.randint(1, count)

    def add(self, company: str, table: str, **values: Any) -> Row:
        stamp = self.start - timedelta(days=90)
        if company == "scc":
            stamp = stamp.astimezone(ZoneInfo("America/Edmonton")).replace(tzinfo=None)
        value = row(company, table, stamp, **values)
        self.masters[company][table].append(value)
        return value

    def label(
        self,
        domain: str,
        scenario: str,
        rmrg_id: int | None,
        scc_id: int | None,
        same_entity: bool | None,
    ) -> None:
        self.truth.append(
            {
                "domain": domain,
                "scenario": scenario,
                "rmrg_source": (
                    {
                        "company": "rmrg",
                        "table": "customers" if domain == "customer" else "products",
                        "pk": rmrg_id,
                    }
                    if rmrg_id
                    else None
                ),
                "scc_source": (
                    {
                        "company": "scc",
                        "table": (
                            "customer_master" if domain == "customer" else "item_master"
                        ),
                        "pk": scc_id,
                    }
                    if scc_id
                    else None
                ),
                "same_entity": same_entity,
                "provenance": "synthetic construction, not an approved enterprise mapping",
            }
        )

    def _masters(self) -> None:
        c = self.config
        for i in range(1, c.rmrg_customers + 1):
            first, last = (
                FIRST[(i - 1) % len(FIRST)],
                LAST[(i - 1) // len(FIRST) % len(LAST)],
            )
            anonymous = i == c.rmrg_customers
            customer = self.add(
                "rmrg",
                "customers",
                customer_id=i,
                customer_number=f"R-{i:08d}",
                first_name="Anonymized" if anonymous else first,
                last_name="Customer" if anonymous else last,
                email=None if anonymous else f"person{i}@example.invalid",
                phone=None if anonymous else f"+1403555{100+i%100:04d}",
                preferred_language="en-CA",
                loyalty_tier=self.random.choices(
                    ["none", "silver", "gold", "platinum"], [55, 28, 14, 3]
                )[0],
                lifecycle_status="anonymized" if anonymous else "active",
                marketing_opt_in=not anonymous and self.random.random() < 0.35,
                registered_at=self.start - timedelta(days=365 + i),
                anonymized_at=self.start - timedelta(days=30) if anonymous else None,
            )
            if anonymous:
                continue
            city, region, postal = CITIES[(i - 1) % 4]
            self.add(
                "rmrg",
                "customer_addresses",
                customer_address_id=i,
                customer_id=i,
                address_label="Home",
                recipient_name=f"{first} {last}",
                address_line1=f"{100+i} Example Avenue",
                city=city,
                region=region,
                postal_code=postal,
                country_code="CA",
                phone=customer["phone"],
                is_default_shipping=True,
                is_default_billing=True,
            )
        customer_overlap = min(
            c.rmrg_customers - 1, int((c.scc_customers - 5) * c.overlap_fraction)
        )
        for i in range(1, c.scc_customers + 1):
            special = i > c.scc_customers - 5
            overlap = i <= customer_overlap
            original = self.masters["rmrg"]["customers"][
                (i - 1) % (c.rmrg_customers - 1)
            ]
            fuzzy = overlap and i % 3 == 0
            value = self.add(
                "scc",
                "customer_master",
                customer_id=i,
                customer_code=f"C{i:05d}",
                customer_name=(
                    f"{original['last_name']}, {original['first_name'][0]}."
                    if fuzzy
                    else (
                        f"{original['first_name']} {original['last_name']}"
                        if overlap
                        else f"Legacy Account {i}"
                    )
                ),
                customer_type="RETAIL",
                email_address=(
                    original["email"]
                    if overlap and not fuzzy
                    else f"legacy{i}@example.invalid"
                ),
                phone_number=f"403-555-{100+i%100:04d}" if overlap else None,
                address_text=(
                    f"{100+i} EXAMPLE AVE" if overlap else f"{200+i} Sample Rd"
                ),
                city=CITIES[(i - 1) % 4][0],
                province="Alberta",
                postal_code=CITIES[(i - 1) % 4][2].replace(" ", ""),
                country="Canada",
                customer_group="Regular",
                credit_limit=ZERO,
                active_flag="Y",
            )
            if overlap:
                self.label(
                    "customer",
                    "fuzzy_name_address" if fuzzy else "exact_contact_name",
                    i,
                    i,
                    True,
                )
            elif not special:
                self.label("customer", "unmatched", None, i, None)
            slot = i - (c.scc_customers - 5)
            if special:
                if slot == 1:
                    value.update(
                        customer_code="WALKIN",
                        customer_name="CASH CUSTOMER",
                        customer_type="WALKIN",
                        email_address=None,
                        address_text=None,
                    )
                    self.label("customer", "anonymous_shared_account", None, i, None)
                elif slot == 2:
                    value.update(
                        customer_code=" c00001 ",
                        customer_name="Different Person",
                        email_address="person1@example.invalid",
                    )
                    self.label("customer", "shared_contact_false_match", 1, i, False)
                elif slot == 3:
                    original = self.masters["scc"]["customer_master"][0]
                    value.update(
                        {
                            k: original[k]
                            for k in (
                                "customer_code",
                                "customer_name",
                                "email_address",
                                "phone_number",
                                "address_text",
                            )
                        }
                    )
                    self.label(
                        "customer",
                        "duplicate_account",
                        1 if customer_overlap else None,
                        i,
                        True if customer_overlap else None,
                    )
                elif slot == 4:
                    value.update(
                        customer_code="TRADE",
                        customer_name="Example Hardware Ltd",
                        customer_type="TRADE",
                        credit_limit=money(5000),
                    )
                    self.label("customer", "organization_not_person", None, i, None)
                else:
                    value.update(
                        customer_code="",
                        email_address="not-an-email",
                        province="Alta",
                        active_flag="?",
                        created_at=None,
                        updated_at=None,
                    )
                    self.label("customer", "malformed_missing", None, i, None)
        self.label("customer", "anonymized_master", c.rmrg_customers, None, None)
        for i, name in enumerate(("RETAIL", "APPAREL", "OUTDOOR", "HOME"), 1):
            self.add(
                "rmrg",
                "product_categories",
                category_id=i,
                category_code=name,
                parent_category_id=None if i == 1 else 1,
                category_name=name.title(),
                sort_order=i,
                is_active=True,
            )
        for i in range(1, c.rmrg_products + 1):
            name, dept, size, color, price = CATALOG[(i - 1) % len(CATALOG)]
            self.add(
                "rmrg",
                "products",
                product_id=i,
                sku=f"RM-{i:07d}",
                category_id={"APPAREL": 2, "OUTDOOR": 3, "HOME": 4}[dept],
                product_name=f"{name} Model {i}",
                description=f"{name}, {color}, {size}",
                brand="Prairie Goods",
                style_code=f"STYLE-{(i-1)//3+1:05d}",
                size_label=size,
                color_name=color,
                barcode=gtin(i),
                unit_of_measure="each",
                list_price=money(price),
                standard_cost=money(Decimal(price) * Decimal("0.58")),
                currency_code="CAD",
                weight_kg=Decimal("0.350"),
                lifecycle_status="active",
                launched_at=self.start - timedelta(days=100),
            )
        product_overlap = min(
            c.rmrg_products, int((c.scc_products - 5) * c.overlap_fraction)
        )
        for i in range(1, c.scc_products + 1):
            p = self.masters["rmrg"]["products"][(i - 1) % c.rmrg_products]
            overlap = i <= product_overlap
            value = self.add(
                "scc",
                "item_master",
                item_id=i,
                item_code=f"I{i:05d}",
                item_description=(
                    p["product_name"].upper() if overlap else f"SCC TOOL {i}"
                ),
                department_code="APP" if overlap else "MISC",
                department_name="General",
                brand_name=p["brand"] if overlap else "Local Supply",
                barcode=p["barcode"] if overlap else gtin(100000 + i),
                unit_code="EA",
                units_per_pack=Decimal("1.000"),
                selling_price=p["list_price"],
                last_cost=p["standard_cost"],
                active_flag="Y",
            )
            if overlap:
                self.label("product", "same_gtin_each", i, i, True)
            elif i <= c.scc_products - 5:
                self.label("product", "unmatched", None, i, None)
            slot = i - (c.scc_products - 5)
            if slot > 0:
                if slot == 1:
                    value.update(
                        item_description="THERMAL SHIRT CASE 12",
                        barcode=gtin(200001),
                        unit_code="CASE",
                        units_per_pack=Decimal("12.000"),
                        selling_price=money("420"),
                    )
                    self.label("product", "case_is_distinct_package", 1, i, False)
                elif slot == 2:
                    value.update(
                        item_description="BULK ROPE",
                        unit_code="KG",
                        units_per_pack=None,
                        barcode=None,
                    )
                    self.label("product", "weighted_goods_not_each", 1, i, False)
                elif slot == 3:
                    value.update(
                        item_code="I00001",
                        barcode=gtin(1),
                        item_description="DIFFERENT SIZE XL SHIRT",
                        unit_code="EA",
                    )
                    self.label("product", "reused_code_barcode_conflict", 1, i, False)
                elif slot == 4:
                    value.update(
                        item_code="GEN",
                        item_description="ASSORTED GOODS",
                        brand_name=None,
                        barcode=None,
                        units_per_pack=Decimal("0.000"),
                    )
                    self.label("product", "generic_missing_pack", None, i, None)
                else:
                    value.update(
                        item_code=" old ",
                        barcode="000BAD",
                        active_flag="N",
                        selling_price=money("-1"),
                        updated_at=None,
                    )
                    self.label("product", "invalid_barcode_price", None, i, None)
        for table, count, prefix in (
            ("stores", c.rmrg_stores, "store"),
            ("warehouses", c.rmrg_warehouses, "warehouse"),
        ):
            for i in range(1, count + 1):
                city, region, postal = CITIES[(i - 1) % 4]
                extra = (
                    {
                        "supports_pickup": True,
                        "supports_ship_from_store": True,
                        "store_type": "outlet" if i % 3 == 0 else "full_service",
                    }
                    if table == "stores"
                    else {"accepts_returns": True, "warehouse_type": "fulfillment"}
                )
                self.add(
                    "rmrg",
                    table,
                    **{
                        f"{prefix}_id": i,
                        f"{prefix}_code": f"{prefix[:2].upper()}-{i:04d}",
                        f"{prefix}_name": f"{city} {prefix} {i}",
                        "address_line1": f"{100+i} Sample Road",
                        "city": city,
                        "region": region,
                        "postal_code": postal,
                        "country_code": "CA",
                        "timezone_name": "America/Edmonton",
                        "lifecycle_status": "open" if table == "stores" else "active",
                        "opened_on": (self.start - timedelta(days=1000)).date(),
                        **extra,
                    },
                )
        for i in range(1, c.scc_locations + 1):
            city, _, postal = CITIES[(i - 1) % 4]
            self.add(
                "scc",
                "locations",
                location_id=i,
                location_code=f"B{i:03d}",
                location_name=f"{city} Branch",
                location_type="DEPOT" if i == c.scc_locations else "SHOP",
                address_text=f"{300+i} Sample Rd",
                city=city,
                province="Alta",
                postal_code=postal,
                country="CAN",
                timezone_name=None if i == 1 else "America/Edmonton",
                active_flag="1",
            )
        for p in range(1, c.rmrg_products + 1):
            for kind, count in (
                ("store", c.rmrg_stores),
                ("warehouse", c.rmrg_warehouses),
            ):
                for loc in range(1, count + 1):
                    inv = self.add(
                        "rmrg",
                        "inventory",
                        inventory_id=self.id("inventory"),
                        product_id=p,
                        store_id=loc if kind == "store" else None,
                        warehouse_id=loc if kind == "warehouse" else None,
                        quantity_on_hand=0,
                        quantity_reserved=0,
                        quantity_unavailable=0,
                        reorder_point=10,
                        target_stock_level=80,
                        last_counted_at=self.start - timedelta(days=1),
                    )
                    self.balances[p, kind, loc] = inv
                    self.movement(
                        inv,
                        "opening",
                        c.initial_stock + self.random.randint(0, 40),
                        0,
                        0,
                        self.start - timedelta(days=1),
                        "initial_load",
                    )
        for item in self.masters["scc"]["item_master"]:
            for loc in range(1, c.scc_locations + 1):
                ident = self.id("stock_balance")
                dirty = self.random.random() < c.messy_fraction
                value = self.add(
                    "scc",
                    "stock_balance",
                    stock_balance_id=ident,
                    item_id=item["item_id"],
                    location_id=loc,
                    quantity_on_hand=(
                        Decimal("-3.000")
                        if dirty
                        else Decimal(self.random.randint(5, 60)).quantize(
                            Decimal("0.001")
                        )
                    ),
                    quantity_on_order=Decimal("0.000"),
                    quantity_allocated=Decimal("8.000") if dirty else Decimal("0.000"),
                    unit_code=item["unit_code"],
                    reorder_level=Decimal("5.000"),
                    last_count_date=(
                        self.start - timedelta(days=180 if dirty else 7)
                    ).date(),
                    balance_as_of=(self.start - timedelta(days=30)).replace(
                        tzinfo=None
                    ),
                )
                if dirty:
                    duplicate = dict(
                        value,
                        stock_balance_id=self.id("stock_balance"),
                        quantity_on_hand=None,
                        updated_at=None,
                    )
                    self.masters["scc"]["stock_balance"].append(duplicate)
                    self.metrics["scc_duplicate_stock_pairs"] += 1

    def movement(
        self,
        inv: Row,
        kind: str,
        qty: int,
        reserved: int,
        unavailable: int,
        stamp: datetime,
        reason: str,
        **refs: Any,
    ) -> None:
        ident = self.id("stock_movements")
        movement = row(
            "rmrg",
            "stock_movements",
            self.snapshot,
            stock_movement_id=ident,
            inventory_id=inv["inventory_id"],
            movement_key=f"SEED-MOVE-{ident:012d}",
            movement_type=kind,
            quantity_delta=qty,
            reserved_delta=reserved,
            unavailable_delta=unavailable,
            occurred_at=stamp,
            reason_code=reason,
            **refs,
        )
        inv["quantity_on_hand"] += qty
        inv["quantity_reserved"] += reserved
        inv["quantity_unavailable"] += unavailable
        if (
            min(inv["quantity_reserved"], inv["quantity_unavailable"]) < 0
            or inv["quantity_on_hand"]
            < inv["quantity_reserved"] + inv["quantity_unavailable"]
        ):
            raise ValueError("Ledger would produce invalid available stock")
        inv.update(updated_at=self.snapshot, row_version=inv["row_version"] + 1)
        self.pending_movements.append(movement)

    def drain_movements(self) -> list[Row]:
        result, self.pending_movements = self.pending_movements, []
        return result

    def reserve(self, inv: Row, qty: int, stamp: datetime) -> None:
        available = (
            inv["quantity_on_hand"]
            - inv["quantity_reserved"]
            - inv["quantity_unavailable"]
        )
        if available < qty:
            self.movement(
                inv,
                "receipt",
                max(qty, self.config.initial_stock),
                0,
                0,
                stamp - timedelta(minutes=1),
                "purchase_receipt",
                source_document_type="purchase_receipt",
                reference_number=f"RECEIPT-{self.ids['stock_movements']+1}",
            )
        self.movement(inv, "reserve", 0, qty, 0, stamp, "allocation")

    def rmrg_orders(self, order_stamp: datetime | None = None) -> Iterator[Bundle]:
        c, rng = self.config, self.random
        # Process chronological business events; sorting only O(days), never O(orders).
        day_counts: dict[datetime, int] = defaultdict(int)
        for _ in range(c.rmrg_orders):
            day_counts[self.stamp().replace(hour=0, minute=0)] += 1
        for day, count in sorted(day_counts.items()):
            for sequence in range(count):
                stamp = (
                    order_stamp
                    if order_stamp is not None
                    else day + timedelta(hours=15, seconds=sequence)
                )
                b: Bundle = defaultdict(list)
                oid = self.id("orders")
                customer_id = (
                    None
                    if rng.random() < c.guest_fraction
                    else self.weighted_id(c.rmrg_customers - 1)
                )
                customer = (
                    self.masters["rmrg"]["customers"][customer_id - 1]
                    if customer_id
                    else None
                )
                customer_id = customer["customer_id"] if customer else None
                channel = rng.choices(
                    ["store", "web", "mobile", "call_center"], [50, 30, 17, 3]
                )[0]
                store = rng.randint(1, c.rmrg_stores)
                choice = rng.random()
                state = (
                    "cancelled"
                    if choice < c.cancel_fraction
                    else (
                        "processing"
                        if choice < c.cancel_fraction + c.open_fraction
                        else "fulfilled"
                    )
                )
                modes = (
                    ["carryout"]
                    if channel == "store"
                    else [rng.choices(["ship", "pickup"], [80, 20])[0]]
                )
                if channel != "store" and rng.random() < 0.12 and c.max_lines >= 2:
                    modes = ["ship", "pickup"]
                line_count = max(
                    len(modes),
                    min(
                        c.max_lines, rng.choices([1, 2, 3, 4, 5], [43, 30, 17, 7, 3])[0]
                    ),
                )
                lines: list[Row] = []
                for line_number in range(1, line_count + 1):
                    p = self.masters["rmrg"]["products"][
                        self.weighted_id(c.rmrg_products) - 1
                    ]
                    qty = rng.choices([1, 2, 3, 5], [70, 22, 6, 2])[0]
                    gross = money(p["list_price"] * qty)
                    discount = money(
                        gross * (Decimal("0.10") if rng.random() < 0.20 else ZERO)
                    )
                    tax = money((gross - discount) * Decimal("0.05"))
                    mode = modes[(line_number - 1) % len(modes)]
                    line = row(
                        "rmrg",
                        "order_items",
                        self.snapshot,
                        order_item_id=self.id("order_items"),
                        order_id=oid,
                        line_number=line_number,
                        product_id=p["product_id"],
                        sku_snapshot=p["sku"],
                        product_name_snapshot=p["product_name"],
                        quantity_ordered=qty,
                        quantity_cancelled=qty if state == "cancelled" else 0,
                        unit_price=p["list_price"],
                        unit_cost_snapshot=p["standard_cost"],
                        gross_amount=gross,
                        discount_amount=discount,
                        tax_rate_percent=money(5),
                        tax_amount=tax,
                        line_total=gross - discount + tax,
                        line_status=(
                            "cancelled"
                            if state == "cancelled"
                            else "open" if state == "processing" else "fulfilled"
                        ),
                        requested_fulfillment=mode,
                        requested_pickup_store_id=store if mode == "pickup" else None,
                    )
                    lines.append(line)
                subtotal = sum((l["gross_amount"] for l in lines), ZERO)
                discount = sum((l["discount_amount"] for l in lines), ZERO)
                tax = sum((l["tax_amount"] for l in lines), ZERO)
                shipping = money("7.95") if "ship" in modes and subtotal < 100 else ZERO
                shiptax = money(shipping * Decimal("0.05"))
                total = subtotal - discount + tax + shipping + shiptax
                order = row(
                    "rmrg",
                    "orders",
                    self.snapshot,
                    order_id=oid,
                    order_number=f"R-ORD-{oid:012d}",
                    order_request_key=f"SEED-R-ORDER-{oid}",
                    customer_id=customer_id,
                    channel=channel,
                    origin_store_id=store if channel == "store" else None,
                    fulfillment_preference="mixed" if len(modes) > 1 else modes[0],
                    order_status=state,
                    currency_code="CAD",
                    contact_email=(
                        customer["email"]
                        if customer
                        else (
                            f"guest{oid}@example.invalid"
                            if channel != "store"
                            else None
                        )
                    ),
                    contact_phone=customer["phone"] if customer else None,
                    merchandise_subtotal=subtotal,
                    discount_total=discount,
                    merchandise_tax_total=tax,
                    shipping_amount=shipping,
                    shipping_tax_amount=shiptax,
                    order_total=total,
                    placed_at=stamp,
                    cancelled_at=(
                        stamp + timedelta(minutes=10) if state == "cancelled" else None
                    ),
                )
                b["orders"].append(order)
                b["order_items"].extend(lines)
                address_id = None
                for role in ["billing", "shipping"] if "ship" in modes else ["billing"]:
                    address_id_value = self.id("order_addresses")
                    if role == "shipping":
                        address_id = address_id_value
                    saved = (
                        next(
                            a
                            for a in self.masters["rmrg"]["customer_addresses"]
                            if a["customer_id"] == customer_id
                            and a["is_default_billing"]
                            and a["archived_at"] is None
                        )
                        if customer_id
                        else None
                    )
                    address = row(
                        "rmrg",
                        "order_addresses",
                        self.snapshot,
                        order_address_id=address_id_value,
                        order_id=oid,
                        address_role=role,
                        source_customer_id=customer_id,
                        source_customer_address_id=(
                            saved["customer_address_id"] if saved else None
                        ),
                        recipient_name=(
                            saved["recipient_name"] if saved else "Guest Recipient"
                        ),
                        address_line1=(
                            saved["address_line1"] if saved else "100 Example Avenue"
                        ),
                        city=saved["city"] if saved else "Calgary",
                        region="AB",
                        postal_code=saved["postal_code"] if saved else "T2P 1J9",
                        country_code="CA",
                        phone=customer["phone"] if customer else None,
                    )
                    b["order_addresses"].append(address)
                components = [
                    (
                        l["order_item_id"],
                        "merchandise",
                        l["gross_amount"] - l["discount_amount"],
                        None,
                    )
                    for l in lines
                ]
                components += [
                    (l["order_item_id"], "tax", l["tax_amount"], None) for l in lines
                ]
                components += [
                    (None, "shipping", shipping, None),
                    (None, "shipping_tax", shiptax, None),
                ]
                capture_id = None
                if state != "cancelled":
                    method = (
                        "cash" if channel == "store" and rng.random() < 0.25 else "card"
                    )
                    # Failed authorization attempts represent retries, never extra cash collection.
                    if method == "card" and rng.random() < 0.06:
                        self.payment(
                            b,
                            oid,
                            "authorization",
                            total,
                            stamp,
                            method,
                            status="failed",
                        )
                        self.metrics["rmrg_failed_payment_attempts"] += 1
                    auth = (
                        self.payment(b, oid, "authorization", total, stamp, method)
                        if method == "card"
                        else None
                    )
                    capture_id = self.payment(
                        b,
                        oid,
                        "capture",
                        total,
                        stamp + timedelta(minutes=1),
                        method,
                        parent=auth,
                        status="pending" if state == "processing" else "succeeded",
                        components=components,
                    )
                    allocations: dict[str, list[Row]] = defaultdict(list)
                    for line in lines:
                        allocations[line["requested_fulfillment"]].append(line)
                    for mode, allocated in allocations.items():
                        sid = self.id("shipments")
                        kind = (
                            "store"
                            if mode != "ship" or rng.random() < 0.20
                            else "warehouse"
                        )
                        loc = (
                            store
                            if kind == "store"
                            else rng.randint(1, c.rmrg_warehouses)
                        )
                        handover = stamp + timedelta(
                            hours=1 if mode == "carryout" else 24
                        )
                        delivered = (
                            handover + timedelta(days=3) if mode == "ship" else handover
                        )
                        shipment = row(
                            "rmrg",
                            "shipments",
                            self.snapshot,
                            shipment_id=sid,
                            shipment_number=f"R-SHP-{sid:012d}",
                            order_id=oid,
                            fulfillment_type=mode,
                            origin_store_id=loc if kind == "store" else None,
                            origin_warehouse_id=loc if kind == "warehouse" else None,
                            shipping_address_id=address_id if mode == "ship" else None,
                            shipping_address_role=(
                                "shipping" if mode == "ship" else None
                            ),
                            carrier=(
                                "synthetic_carrier"
                                if mode == "ship" and state == "fulfilled"
                                else None
                            ),
                            tracking_number=(
                                f"SEED-{sid:012d}"
                                if mode == "ship" and state == "fulfilled"
                                else None
                            ),
                            shipment_status=(
                                "allocated" if state == "processing" else "delivered"
                            ),
                            planned_at=stamp,
                            ready_at=(
                                handover - timedelta(minutes=10)
                                if state == "fulfilled"
                                else None
                            ),
                            handed_over_at=handover if state == "fulfilled" else None,
                            delivered_at=delivered if state == "fulfilled" else None,
                            expected_delivery_on=(
                                delivered.date() if mode == "ship" else None
                            ),
                        )
                        b["shipments"].append(shipment)
                        for line in allocated:
                            siid = self.id("shipment_items")
                            b["shipment_items"].append(
                                row(
                                    "rmrg",
                                    "shipment_items",
                                    self.snapshot,
                                    shipment_item_id=siid,
                                    shipment_id=sid,
                                    order_id=oid,
                                    order_item_id=line["order_item_id"],
                                    quantity=line["quantity_ordered"],
                                )
                            )
                            inv = self.balances[line["product_id"], kind, loc]
                            self.reserve(inv, line["quantity_ordered"], stamp)
                            if state == "fulfilled":
                                self.movement(
                                    inv,
                                    "sale",
                                    -line["quantity_ordered"],
                                    -line["quantity_ordered"],
                                    0,
                                    handover,
                                    "fulfillment",
                                    shipment_item_id=siid,
                                )
                    if state == "fulfilled" and rng.random() < c.return_fraction:
                        self.make_return(b, order, lines, capture_id, method, stamp)
                b["stock_movements"].extend(self.drain_movements())
                self.metrics[f"rmrg_{state}_orders"] += 1
                self.metrics[f"rmrg_channel_{channel}"] += 1
                yield b

    def payment(
        self,
        b: Bundle,
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
        pid = self.id("payments")
        b["payments"].append(
            row(
                "rmrg",
                "payments",
                self.snapshot,
                payment_id=pid,
                order_id=oid,
                payment_request_key=f"SEED-PAY-{pid}",
                parent_payment_id=parent,
                return_id=return_id,
                operation_type=operation,
                payment_method=method,
                provider="internal_cash" if method == "cash" else "synthetic_gateway",
                provider_transaction_id=(
                    f"SEED-TXN-{pid}"
                    if method != "cash" and status == "succeeded"
                    else None
                ),
                payment_status=status,
                amount=amount,
                currency_code="CAD",
                failure_code="DECLINED" if status == "failed" else None,
                attempted_at=stamp,
                processed_at=(
                    None if status == "pending" else stamp + timedelta(seconds=1)
                ),
            )
        )
        for line, kind, value, return_item in components or []:
            if value > 0:
                b["payment_allocations"].append(
                    row(
                        "rmrg",
                        "payment_allocations",
                        self.snapshot,
                        payment_allocation_id=self.id("payment_allocations"),
                        payment_id=pid,
                        order_id=oid,
                        order_item_id=line,
                        return_item_id=return_item,
                        return_id=return_id if return_item else None,
                        allocation_type=kind,
                        amount=value,
                    )
                )
        return pid

    def make_return(
        self,
        b: Bundle,
        order: Row,
        lines: list[Row],
        capture: int,
        method: str,
        stamp: datetime,
    ) -> None:
        line = self.random.choice(lines)
        shipped = next(
            si
            for si in b["shipment_items"]
            if si["order_item_id"] == line["order_item_id"]
        )
        shipment = next(
            s for s in b["shipments"] if s["shipment_id"] == shipped["shipment_id"]
        )
        rid, riid = self.id("returns"), self.id("return_items")
        qty = 1
        net = money(
            (line["gross_amount"] - line["discount_amount"])
            * qty
            / line["quantity_ordered"]
        )
        tax = money(line["tax_amount"] * qty / line["quantity_ordered"])
        request = shipment["delivered_at"] + timedelta(days=7)
        receive = request + timedelta(days=1)
        inspect = receive + timedelta(hours=1)
        disposal = self.random.random() < 0.25
        loc = self.random.randint(1, self.config.rmrg_stores)
        b["returns"].append(
            row(
                "rmrg",
                "returns",
                self.snapshot,
                return_id=rid,
                return_number=f"R-RMA-{rid:012d}",
                order_id=order["order_id"],
                return_status="closed",
                return_channel="store",
                receiving_store_id=loc,
                currency_code="CAD",
                merchandise_refund_amount=net,
                tax_refund_amount=tax,
                shipping_refund_amount=ZERO,
                shipping_tax_refund_amount=ZERO,
                refund_total=net + tax,
                requested_at=request,
                authorized_at=request + timedelta(hours=1),
                first_received_at=receive,
                fully_received_at=receive,
                resolved_at=inspect + timedelta(hours=1),
            )
        )
        b["return_items"].append(
            row(
                "rmrg",
                "return_items",
                self.snapshot,
                return_item_id=riid,
                return_id=rid,
                order_id=order["order_id"],
                order_item_id=line["order_item_id"],
                shipment_item_id=shipped["shipment_item_id"],
                quantity_requested=qty,
                quantity_authorized=qty,
                quantity_received=qty,
                quantity_restocked=0 if disposal else qty,
                quantity_disposed=qty if disposal else 0,
                reason_code="damaged" if disposal else "changed_mind",
                disposition="dispose" if disposal else "restock",
                merchandise_refund_amount=net,
                tax_refund_amount=tax,
                last_received_at=receive,
                inspected_at=inspect,
            )
        )
        inv = self.balances[line["product_id"], "store", loc]
        self.movement(
            inv, "return", qty, 0, 0, receive, "customer_return", return_item_id=riid
        )
        self.movement(
            inv,
            "quarantine",
            0,
            0,
            qty,
            receive,
            "damage" if disposal else "customer_return",
            return_item_id=riid,
        )
        self.movement(
            inv,
            "unquarantine",
            0,
            0,
            -qty,
            inspect,
            "quality_release",
            return_item_id=riid,
        )
        if disposal:
            self.movement(
                inv, "adjustment", -qty, 0, 0, inspect, "damage", return_item_id=riid
            )
        self.payment(
            b,
            order["order_id"],
            "refund",
            net + tax,
            inspect,
            method,
            parent=capture,
            return_id=rid,
            components=[
                (line["order_item_id"], "merchandise", net, riid),
                (line["order_item_id"], "tax", tax, riid),
            ],
        )
        self.metrics["rmrg_returned_orders"] += 1

    def scc_orders(self) -> Iterator[Bundle]:
        c, rng = self.config, self.random
        for _ in range(c.scc_orders):
            oid = self.id("sales_orders")
            stamp = (
                self.stamp()
                .astimezone(ZoneInfo("America/Edmonton"))
                .replace(tzinfo=None)
            )
            b: Bundle = defaultdict(list)
            dirty = rng.random() < c.messy_fraction
            customer = self.masters["scc"]["customer_master"][
                self.weighted_id(c.scc_customers) - 1
            ]
            if rng.random() < c.guest_fraction:
                customer = next(
                    v
                    for v in self.masters["scc"]["customer_master"]
                    if v["customer_type"] == "WALKIN"
                )
            loc = rng.randint(1, c.scc_locations)
            credit = dirty and oid % 3 == 0
            for number in range(
                1, min(c.max_lines, rng.choices([1, 2, 3], [60, 30, 10])[0]) + 1
            ):
                item = self.masters["scc"]["item_master"][
                    self.weighted_id(c.scc_products) - 1
                ]
                qty = (
                    Decimal("2.500")
                    if item["unit_code"] == "KG"
                    else Decimal(rng.choices([1, 2, 4], [75, 20, 5])[0]).quantize(
                        Decimal("0.001")
                    )
                )
                if credit:
                    qty = -qty
                price = item["selling_price"]
                net = money(qty * price)
                b["sales_order_lines"].append(
                    row(
                        "scc",
                        "sales_order_lines",
                        stamp,
                        sales_order_line_id=self.id("sales_order_lines"),
                        sales_order_id=oid,
                        line_number=number,
                        item_id_ref=(
                            c.scc_products + 999
                            if dirty and number == 1
                            else item["item_id"]
                        ),
                        item_code_ref="REUSED" if dirty else item["item_code"],
                        description_text=item["item_description"],
                        unit_code=item["unit_code"],
                        quantity=qty,
                        unit_price=price,
                        discount_amount=ZERO,
                        tax_amount=None if dirty else money(net * Decimal("0.05")),
                        line_amount=net,
                        line_status="" if dirty else "OK",
                    )
                )
            subtotal = sum((l["line_amount"] for l in b["sales_order_lines"]), ZERO)
            tax = money(subtotal * Decimal("0.05"))
            total = subtotal + tax
            b["sales_orders"].append(
                row(
                    "scc",
                    "sales_orders",
                    stamp,
                    sales_order_id=oid,
                    order_number=f"{oid%100:05d}",
                    business_date=stamp.date(),
                    entered_at=None if dirty else stamp,
                    location_id=loc,
                    till_code=f"T{oid%2+1}",
                    customer_id_ref=(
                        c.scc_customers + 999 if dirty else customer["customer_id"]
                    ),
                    customer_code_ref=customer["customer_code"],
                    customer_name_text=customer["customer_name"],
                    delivery_address_text=None,
                    sales_channel=rng.choices(["POS", "PHONE", "WEB"], [85, 12, 3])[0],
                    order_status="paid?" if dirty else "PAID",
                    currency_text="C$" if dirty else "CAD",
                    subtotal_amount=subtotal,
                    discount_amount=ZERO,
                    tax_amount=tax,
                    freight_amount=ZERO,
                    total_amount=total + money(7) if dirty else total,
                    paid_amount=ZERO if dirty else total,
                )
            )

            def posting(amount: Decimal, orphan: bool = False) -> None:
                ident = self.id("payment_transactions")
                value = row(
                    "scc",
                    "payment_transactions",
                    stamp,
                    payment_transaction_id=ident,
                    sales_order_id=None if orphan else oid,
                    order_number_ref=f"{oid%100:05d}",
                    location_id=loc,
                    receipt_number=f"RCPT-{oid%100:05d}",
                    transaction_date=stamp.date(),
                    transaction_time=None if dirty else stamp,
                    transaction_type="REFUND" if credit else "PAYMENT",
                    tender_code=rng.choices(["CASH", "CRD", "CHQ"], [55, 40, 5])[0],
                    amount=amount,
                    currency_text="$" if dirty else "CAD",
                    reference_text=f"IMPORT-{oid%50:04d}",
                    posted_flag="?" if dirty else "Y",
                    reversal_of_id_ref=99999999 if dirty and credit else None,
                )
                if dirty:
                    value.update(
                        created_at=None,
                        updated_at=stamp - timedelta(days=30),
                        updated_by="BATCH",
                    )
                b["payment_transactions"].append(value)

            posting(abs(total) if dirty and credit else total, orphan=dirty)
            if dirty and oid % 2 == 0:
                posting(total, orphan=True)
                self.metrics["scc_duplicate_cash_postings"] += 1
            if dirty:
                b["sales_orders"][0].update(updated_at=stamp - timedelta(days=7))
                self.metrics["scc_dirty_orders"] += 1
            yield b
