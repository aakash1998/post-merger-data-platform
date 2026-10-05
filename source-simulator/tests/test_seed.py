"""Behavioral acceptance tests for both approved source contracts."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retail_simulator.config import Config, environment
from retail_simulator.contracts import SCHEMA, json_default, validate_row
from retail_simulator.generator import Generator
from retail_simulator.snapshot import generate, verify
from retail_simulator.validation import Validator

ROOT = Path(__file__).resolve().parents[2]
SMALL = Config(
    rmrg_customers=40,
    scc_customers=24,
    rmrg_products=24,
    scc_products=16,
    rmrg_orders=100,
    scc_orders=40,
    return_fraction=0.35,
    messy_fraction=0.45,
)


def dictionary(folder: str) -> dict[str, list[list[object]]]:
    root = ROOT / "docs" / "source-data-model" / folder
    audits = []
    for line in (root / "conventions.md").read_text().splitlines():
        fields = [x.strip() for x in line.split("|")[1:-1]]
        if len(fields) == 4 and fields[0] in {
            "created_at",
            "updated_at",
            "row_version",
            "created_by",
            "updated_by",
        }:
            audits.append([fields[0], fields[1], fields[2] == "Yes"])
    names = (
        ["tables.md"]
        if folder.startswith("stampede")
        else [
            "customers-and-catalog.md",
            "locations-and-inventory.md",
            "orders-and-payments.md",
            "fulfillment-and-returns.md",
        ]
    )
    tables = {}
    for name in names:
        current = None
        for line in (root / name).read_text().splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                tables[current] = []
            fields = [x.strip() for x in line.split("|")[1:-1]]
            if current and len(fields) == 4 and fields[2] in {"Yes", "No"}:
                tables[current].append([fields[0], fields[1], fields[2] == "Yes"])
    return {name: fields + audits for name, fields in tables.items()}


class SeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = Generator(SMALL)
        cls.data = deepcopy(cls.generator.masters)
        cls.data["rmrg"]["stock_movements"] = cls.generator.drain_movements()
        for company, stream in [
            ("rmrg", cls.generator.rmrg_orders()),
            ("scc", cls.generator.scc_orders()),
        ]:
            for b in stream:
                for table, rows in b.items():
                    cls.data[company].setdefault(table, []).extend(rows)
        cls.data["rmrg"]["inventory"] = deepcopy(
            cls.generator.masters["rmrg"]["inventory"]
        )

    def test_approved_dictionary_exact_columns_types_and_nullability(self) -> None:
        self.assertEqual(SCHEMA["rmrg"], dictionary("rocky-mountain-retail-group"))
        self.assertEqual(SCHEMA["scc"], dictionary("stampede-city-commerce"))
        self.assertEqual((len(SCHEMA["rmrg"]), len(SCHEMA["scc"])), (17, 7))

    def test_complete_snapshot_pk_fk_and_business_reconciliation(self) -> None:
        validator = Validator(self.data)
        for company, tables in self.data.items():
            self.assertEqual(set(tables), set(SCHEMA[company]))
            for table, rows in tables.items():
                self.assertTrue(rows, f"Empty default table {company}.{table}")
                pk = SCHEMA[company][table][0][0]
                self.assertEqual(len(rows), len({r[pk] for r in rows}))
                for r in rows:
                    validate_row(company, table, r)
            validator.bundle(company, tables)
        validator.finish()

    def test_financial_invariants_from_business_facts(self) -> None:
        d = self.data["rmrg"]
        for order in d["orders"]:
            lines = [l for l in d["order_items"] if l["order_id"] == order["order_id"]]
            self.assertEqual(
                order["order_total"],
                sum((l["line_total"] for l in lines), Decimal(0))
                + order["shipping_amount"]
                + order["shipping_tax_amount"],
            )
            succeeded = [
                p
                for p in d["payments"]
                if p["order_id"] == order["order_id"]
                and p["payment_status"] == "succeeded"
            ]
            captured = sum(
                (p["amount"] for p in succeeded if p["operation_type"] == "capture"),
                Decimal(0),
            )
            refunded = sum(
                (p["amount"] for p in succeeded if p["operation_type"] == "refund"),
                Decimal(0),
            )
            if order["order_status"] == "fulfilled":
                self.assertEqual(captured, order["order_total"])
                self.assertLessEqual(refunded, captured)
            elif order["order_status"] == "cancelled":
                self.assertEqual(captured, 0)

    def test_reject_cross_order_composite_fk_and_excess_refund(self) -> None:
        d = deepcopy(self.data["rmrg"])
        d["shipment_items"][0]["order_id"] = next(
            o["order_id"]
            for o in d["orders"]
            if o["order_id"] != d["shipment_items"][0]["order_id"]
        )
        with self.assertRaisesRegex(ValueError, "Broken FK"):
            Validator(self.data).bundle("rmrg", d)
        d = deepcopy(self.data["rmrg"])
        refund = next(p for p in d["payments"] if p["operation_type"] == "refund")
        refund["amount"] = Decimal("999999.00")
        with self.assertRaises(ValueError):
            Validator(self.data).bundle("rmrg", d)

    def test_reject_invalid_stock_and_broken_enforced_scc_fk(self) -> None:
        d = deepcopy(self.data["rmrg"])
        d["inventory"][0]["quantity_reserved"] = (
            d["inventory"][0]["quantity_on_hand"] + 1
        )
        with self.assertRaisesRegex(ValueError, "Inventory balance"):
            Validator(self.data).bundle("rmrg", d)
        d = deepcopy(self.data["scc"])
        d["sales_order_lines"][0]["sales_order_id"] = 999999
        with self.assertRaisesRegex(ValueError, "Broken FK"):
            Validator(self.data).bundle("scc", d)

    def test_scc_quality_evidence_preserved_and_typed(self) -> None:
        d = self.data["scc"]
        ids = {c["customer_id"] for c in d["customer_master"]}
        self.assertTrue(any(o["customer_id_ref"] not in ids for o in d["sales_orders"]))
        self.assertTrue(
            any(
                o["total_amount"]
                != o["subtotal_amount"]
                - o["discount_amount"]
                + o["tax_amount"]
                + o["freight_amount"]
                for o in d["sales_orders"]
            )
        )
        self.assertTrue(
            any(o["updated_at"] < o["created_at"] for o in d["sales_orders"])
        )
        pairs = Counter((s["item_id"], s["location_id"]) for s in d["stock_balance"])
        self.assertTrue(any(n > 1 for n in pairs.values()))
        self.assertTrue(any(s["quantity_on_hand"] is None for s in d["stock_balance"]))
        self.assertTrue(
            any(
                s["quantity_on_hand"] is not None and s["quantity_on_hand"] < 0
                for s in d["stock_balance"]
            )
        )
        self.assertTrue(any(l["quantity"] < 0 for l in d["sales_order_lines"]))
        self.assertTrue(
            any(p["sales_order_id"] is None for p in d["payment_transactions"])
        )
        value = dict(d["sales_order_lines"][0], quantity="1,234.50")
        with self.assertRaisesRegex(ValueError, "Decimal range/type"):
            validate_row("scc", "sales_order_lines", value)

    def test_matching_truth_does_not_override_source_identity(self) -> None:
        truth = self.generator.truth
        scenarios = {r["scenario"] for r in truth}
        self.assertTrue(
            {
                "exact_contact_name",
                "fuzzy_name_address",
                "duplicate_account",
                "shared_contact_false_match",
                "anonymous_shared_account",
                "anonymized_master",
                "same_gtin_each",
                "case_is_distinct_package",
                "reused_code_barcode_conflict",
                "weighted_goods_not_each",
                "unmatched",
            }
            <= scenarios
        )
        for label in truth:
            if label["same_entity"] is True and label["domain"] == "product":
                r = self.data["rmrg"]["products"][label["rmrg_source"]["pk"] - 1]
                s = self.data["scc"]["item_master"][label["scc_source"]["pk"] - 1]
                self.assertEqual(r["barcode"], s["barcode"])
                self.assertEqual(s["unit_code"], "EA")
                digits = r["barcode"]
                self.assertEqual(
                    sum(
                        int(v) * (1 if i % 2 == 0 else 3)
                        for i, v in enumerate(digits[:-1])
                    )
                    % 10,
                    (-int(digits[-1])) % 10,
                )
        for company, tables in self.data.items():
            for rows in tables.values():
                self.assertFalse(
                    any(
                        "enterprise_customer_id" in r or "same_entity" in r
                        for r in rows
                    )
                )

    def test_weighted_repeat_business_and_seasonality(self) -> None:
        g = Generator(replace(SMALL, rmrg_orders=1000, scc_orders=0))
        channels, customers, months, products = (
            Counter(),
            Counter(),
            Counter(),
            Counter(),
        )
        guest = 0
        for b in g.rmrg_orders():
            order = b["orders"][0]
            channels[order["channel"]] += 1
            months[order["placed_at"].month] += 1
            if order["customer_id"]:
                customers[order["customer_id"]] += 1
            else:
                guest += 1
            products.update(l["product_id"] for l in b["order_items"])
        self.assertGreater(channels["store"], channels["web"])
        self.assertGreater(months[11] + months[12], 300)
        self.assertTrue(100 < guest < 280)
        self.assertGreater(
            sum(v for k, v in customers.items() if k <= 7) / sum(customers.values()),
            0.60,
        )
        self.assertGreater(
            sum(v for k, v in products.items() if k <= 4) / sum(products.values()), 0.60
        )

    def test_reproducible_atomic_export_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "a", Path(directory) / "b"
            manifest = generate(SMALL, first, "test")
            self.assertEqual(manifest, generate(SMALL, second, "test"))
            self.assertEqual(manifest, generate(SMALL, first, "test"))
            self.assertEqual(len(manifest["files"]), 25)
            for name in manifest["files"]:
                self.assertEqual(
                    (first / name).read_bytes(), (second / name).read_bytes()
                )
            with self.assertRaisesRegex(ValueError, "different configuration"):
                generate(replace(SMALL, seed=25), first, "test")
            with (first / "rmrg/orders.jsonl").open("a") as stream:
                stream.write("{}\n")
            with self.assertRaisesRegex(ValueError, "incomplete or changed"):
                generate(SMALL, first, "test")

    def test_failed_validation_never_publishes_and_restart_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "snapshot"
            with patch.object(
                Validator, "finish", side_effect=ValueError("injected failure")
            ):
                with self.assertRaisesRegex(ValueError, "injected failure"):
                    generate(SMALL, target, "test")
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            manifest = generate(SMALL, target, "test")
            verify(target, manifest)

    def test_zero_order_profile_and_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = generate(
                replace(SMALL, rmrg_orders=0, scc_orders=0),
                Path(directory) / "snapshot",
                "test",
            )
            self.assertEqual(manifest["files"]["rmrg/orders.jsonl"]["rows"], 0)
            self.assertEqual(manifest["files"]["scc/sales_orders.jsonl"]["rows"], 0)
            self.assertEqual(
                json.loads(
                    json.dumps({"amount": Decimal("12.30")}, default=json_default)
                )["amount"],
                "12.30",
            )

    def test_invalid_configuration_and_environment_rejected(self) -> None:
        for params in [
            {"rmrg_orders": -1},
            {"scc_orders": True},
            {"overlap_fraction": 1.5},
            {"max_lines": 101},
            {"start_date": "2023-01-01"},
            {"open_fraction": 0.8, "cancel_fraction": 0.5},
        ]:
            with self.assertRaises((ValueError, TypeError)):
                Config(**params)
        with patch.dict(os.environ, {"PMDP_ENV": "prod"}):
            with self.assertRaisesRegex(ValueError, "dev or test"):
                environment()

    def test_boundary_workloads_keep_constraints(self) -> None:
        profiles = [
            replace(
                SMALL,
                rmrg_orders=15,
                scc_orders=10,
                max_lines=1,
                guest_fraction=1,
                return_fraction=1,
                open_fraction=0,
                cancel_fraction=0,
                overlap_fraction=1,
                messy_fraction=1,
            ),
            replace(
                SMALL,
                rmrg_orders=15,
                scc_orders=10,
                open_fraction=1,
                cancel_fraction=0,
                overlap_fraction=0,
                messy_fraction=0,
                days=1,
            ),
            replace(
                SMALL, rmrg_orders=15, scc_orders=0, open_fraction=0, cancel_fraction=1
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for i, profile in enumerate(profiles):
                with self.subTest(profile=i):
                    manifest = generate(profile, Path(directory) / str(i), "test")
                    self.assertEqual(
                        manifest["files"]["rmrg/orders.jsonl"]["rows"],
                        profile.rmrg_orders,
                    )


if __name__ == "__main__":
    unittest.main()
