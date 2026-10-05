"""Business lifecycle, durable transaction and persistence acceptance tests."""

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import tempfile
import threading
import unittest
from unittest.mock import patch

from retail_simulator.activity import Activity
from retail_simulator.changes import Change, Transaction, validate_state
from retail_simulator.config import Config
from retail_simulator.contracts import SCHEMA
from retail_simulator.continuous import RunConfig, WEIGHTS, run
from retail_simulator.generator import Generator
from retail_simulator.persistence import DBAPIWriter, FileStore, MemoryStore

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
PROFILE = Config(
    rmrg_customers=24,
    scc_customers=16,
    rmrg_products=16,
    scc_products=12,
    rmrg_orders=0,
    scc_orders=0,
    max_lines=3,
)


def baseline():
    g = Generator(PROFILE)
    result = {co: {table: {} for table in tables} for co, tables in SCHEMA.items()}
    for co, tables in g.masters.items():
        for table, values in tables.items():
            pk = SCHEMA[co][table][0][0]
            result[co][table] = {r[pk]: deepcopy(r) for r in values}
    result["rmrg"]["stock_movements"] = {
        r["stock_movement_id"]: r for r in g.drain_movements()
    }
    return result


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(baseline())
        self.activity = Activity(self.store, PROFILE, random.Random(25))
        self.step = 0

    def commit(self, company, name):
        self.step += 1
        tx = self.activity.plan(company, name, NOW + timedelta(seconds=self.step))
        self.assertIsNotNone(tx, f"No eligible {company} {name}")
        self.assertTrue(self.store.commit(tx))
        return tx

    def fulfil(self):
        self.commit("rmrg", "new_order")
        self.commit("rmrg", "payment")
        while any(
            s["shipment_status"] in {"allocated", "ready"}
            for s in self.store.data["rmrg"]["shipments"].values()
        ):
            self.commit("rmrg", "shipment")
        while any(
            s["shipment_status"] == "handed_over"
            for s in self.store.data["rmrg"]["shipments"].values()
        ):
            self.commit("rmrg", "delivery")

    def test_order_payment_fulfillment_return_refund_lifecycle(self):
        original_stock = deepcopy(self.store.data["rmrg"]["inventory"])
        self.fulfil()
        tables = self.store.data["rmrg"]
        accepted = deepcopy(tables["order_items"])
        self.assertTrue(
            all(o["order_status"] == "fulfilled" for o in tables["orders"].values())
        )
        self.assertTrue(
            all(
                s["shipment_status"] == "delivered"
                for s in tables["shipments"].values()
            )
        )
        self.assertTrue(
            any(
                tables["inventory"][i]["quantity_on_hand"] < r["quantity_on_hand"]
                for i, r in original_stock.items()
            )
        )
        with patch.object(self.activity.rng, "random", return_value=0.0):
            self.commit("rmrg", "return")
        self.commit("rmrg", "return_progress")  # authorization
        self.commit("rmrg", "return_progress")  # receipt and quarantine
        self.assertEqual(
            sum(
                i["quantity_unavailable"]
                for i in self.store.data["rmrg"]["inventory"].values()
            ),
            1,
        )
        self.commit("rmrg", "return_progress")  # inspection/disposal and pending refund
        self.assertEqual(
            sum(
                i["quantity_unavailable"]
                for i in self.store.data["rmrg"]["inventory"].values()
            ),
            0,
        )
        self.assertTrue(
            any(
                p["operation_type"] == "refund" and p["payment_status"] == "pending"
                for p in self.store.data["rmrg"]["payments"].values()
            )
        )
        self.commit("rmrg", "return_progress")  # confirmed refund, closed RMA
        self.assertEqual(accepted, self.store.data["rmrg"]["order_items"])
        self.assertTrue(
            all(
                r["return_status"] == "closed"
                for r in self.store.data["rmrg"]["returns"].values()
            )
        )
        self.assertEqual(
            next(iter(self.store.data["rmrg"]["return_items"].values()))[
                "quantity_disposed"
            ],
            1,
        )
        validate_state(self.store.data)

    def test_cancel_resolves_capture_voids_authorization_and_releases_stock(self):
        initial = deepcopy(self.store.data["rmrg"]["inventory"])
        self.commit("rmrg", "new_order")
        total = next(iter(self.store.data["rmrg"]["orders"].values()))["order_total"]
        self.assertGreater(
            sum(
                i["quantity_reserved"]
                for i in self.store.data["rmrg"]["inventory"].values()
            ),
            0,
        )
        self.commit("rmrg", "cancel")
        tables = self.store.data["rmrg"]
        self.assertEqual(next(iter(tables["orders"].values()))["order_total"], total)
        self.assertTrue(
            all(i["quantity_reserved"] == 0 for i in tables["inventory"].values())
        )
        self.assertTrue(
            all(
                i["quantity_on_hand"] == initial[k]["quantity_on_hand"]
                for k, i in tables["inventory"].items()
            )
        )
        self.assertFalse(
            any(
                p["payment_status"] == "succeeded" and p["operation_type"] == "capture"
                for p in tables["payments"].values()
            )
        )
        self.assertTrue(
            all(
                s["shipment_status"] == "cancelled"
                for s in tables["shipments"].values()
            )
        )
        self.assertIsNone(
            self.activity.plan("rmrg", "shipment", NOW + timedelta(seconds=10))
        )

    def test_return_receipt_without_quarantine_is_rejected_atomically(self):
        self.fulfil()
        self.commit("rmrg", "return")
        self.commit("rmrg", "return_progress")
        tx = self.activity.plan("rmrg", "return_progress", NOW + timedelta(seconds=30))
        broken = []
        for change in tx.changes:
            if (
                change.table == "stock_movements"
                and change.after["movement_type"] == "quarantine"
            ):
                continue
            if change.table == "inventory":
                change = replace(
                    change,
                    after=dict(
                        change.after,
                        quantity_unavailable=change.before["quantity_unavailable"],
                    ),
                )
            broken.append(change)
        before = deepcopy(self.store.data)
        with self.assertRaisesRegex(ValueError, "quarantine"):
            self.store.commit(replace(tx, changes=tuple(broken)))
        self.assertEqual(before, self.store.data)

    def test_customer_updates_leave_order_snapshots_and_frozen_money_unchanged(self):
        self.commit("rmrg", "new_customer")
        self.commit("rmrg", "new_order")
        evidence = {
            t: deepcopy(self.store.data["rmrg"][t])
            for t in ("order_addresses", "order_items")
        }
        self.commit("rmrg", "update_customer")
        for table, values in evidence.items():
            self.assertEqual(values, self.store.data["rmrg"][table])
        line = next(iter(self.store.data["rmrg"]["order_items"].values()))
        changed = dict(
            line, unit_price=line["unit_price"] + 1, row_version=line["row_version"] + 1
        )
        tx = Transaction(
            self.store.sequence + 1,
            "rmrg",
            "invalid_price",
            (Change("order_items", line["order_item_id"], line, changed),),
            dict(self.store.highwater["rmrg"]),
        )
        with self.assertRaisesRegex(ValueError, "commercial line"):
            self.store.commit(tx)

    def test_deleted_draft_identity_is_never_reused(self):
        self.commit("rmrg", "draft")
        deleted = max(self.store.data["rmrg"]["orders"])
        self.commit("rmrg", "delete_draft")
        self.commit("rmrg", "draft")
        self.assertGreater(max(self.store.data["rmrg"]["orders"]), deleted)

    def test_scc_payment_corrections_and_child_first_abandoned_deletion(self):
        self.commit("scc", "new_order")
        self.commit("scc", "payment")
        self.commit("scc", "correct_invoice")
        self.commit("scc", "correct_posting")
        self.commit("scc", "new_order")
        deleted = self.commit("scc", "delete_abandoned")
        self.assertTrue(
            any(
                c.table == "sales_order_lines" and c.after is None
                for c in deleted.changes
            )
        )
        self.assertTrue(
            any(c.table == "sales_orders" and c.after is None for c in deleted.changes)
        )
        self.assertEqual(len(self.store.data["scc"]["sales_orders"]), 1)
        validate_state(self.store.data)

    def test_scc_logical_orphan_allowed_enforced_orphan_rejected(self):
        self.commit("scc", "new_order")
        customer = next(
            c
            for c in self.store.data["scc"]["customer_master"].values()
            if c["customer_type"] == "RETAIL"
        )
        order = next(iter(self.store.data["scc"]["sales_orders"].values()))
        updates = (
            Change(
                "customer_master",
                customer["customer_id"],
                customer,
                dict(customer, active_flag="N"),
            ),
            Change(
                "sales_orders",
                order["sales_order_id"],
                order,
                dict(order, customer_id_ref=customer["customer_id"]),
            ),
        )
        self.store.commit(
            Transaction(
                self.store.sequence + 1,
                "scc",
                "manual_legacy_correction",
                updates,
                dict(self.store.highwater["scc"]),
            )
        )
        self.commit("scc", "delete_customer")
        self.assertNotIn(
            customer["customer_id"], self.store.data["scc"]["customer_master"]
        )
        self.assertEqual(
            next(iter(self.store.data["scc"]["sales_orders"].values()))[
                "customer_id_ref"
            ],
            customer["customer_id"],
        )
        line = next(iter(self.store.data["scc"]["sales_order_lines"].values()))
        tx = Transaction(
            self.store.sequence + 1,
            "scc",
            "bad_parent",
            (
                Change(
                    "sales_order_lines",
                    line["sales_order_line_id"],
                    line,
                    dict(line, sales_order_id=999999),
                ),
            ),
            dict(self.store.highwater["scc"]),
        )
        with self.assertRaisesRegex(ValueError, "enforced FK"):
            self.store.commit(tx)

    def test_stale_transaction_rejected_and_exact_replay_has_one_effect(self):
        tx = self.activity.plan("rmrg", "new_customer", NOW)
        self.assertTrue(self.store.commit(tx))
        self.assertFalse(self.store.commit(tx))
        competing = replace(
            tx,
            activity="other",
            changes=tuple(
                (
                    replace(c, after=dict(c.after, first_name="Other"))
                    if c.table == "customers"
                    else c
                )
                for c in tx.changes
            ),
        )
        with self.assertRaisesRegex(ValueError, "sequence"):
            self.store.commit(competing)

    def test_local_restart_recovers_durable_commit_and_key_highwaters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with FileStore(root, "test", baseline()) as store:
                activity = Activity(store, PROFILE, random.Random(1))
                tx = activity.plan("rmrg", "draft", NOW)
                store.commit(tx)
                delete = activity.plan("rmrg", "delete_draft", NOW)
                # Failure after durable publication but before in-memory acknowledgment.
                with patch.object(
                    store, "publish", side_effect=OSError("lost acknowledgment")
                ):
                    with self.assertRaises(OSError):
                        store.commit(delete)
            with FileStore(root, "test") as restored:
                self.assertEqual(restored.sequence, 2)
                self.assertFalse(restored.commit(delete))
                self.assertFalse(restored.data["rmrg"]["orders"])
                new = Activity(restored, PROFILE).plan("rmrg", "draft", NOW)
                restored.commit(new)
                self.assertGreater(
                    max(restored.data["rmrg"]["orders"]), tx.changes[0].pk
                )
            with self.assertRaisesRegex(ValueError, "environment"):
                FileStore(root, "dev")

    def test_local_failed_write_and_second_writer_do_not_change_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with FileStore(root, "test", baseline()) as store:
                with self.assertRaises(BlockingIOError):
                    FileStore(root, "test")
                tx = Activity(store, PROFILE).plan("rmrg", "new_customer", NOW)
                with patch(
                    "retail_simulator.persistence.atomic_write",
                    side_effect=OSError("disk unavailable"),
                ):
                    with self.assertRaises(OSError):
                        store.commit(tx)
                self.assertEqual(store.sequence, 0)
                self.assertFalse(list((root / "transactions").glob("*.json")))

    def test_mixed_activity_preserves_consistency(self):
        counts = Counter()
        for step in range(240):
            co = self.activity.rng.choices(["rmrg", "scc"], [3, 1])[0]
            name = self.activity.rng.choices(
                list(WEIGHTS[co]), list(WEIGHTS[co].values())
            )[0]
            tx = self.activity.plan(co, name, NOW + timedelta(seconds=step))
            if tx:
                self.store.commit(tx)
                counts.update(c.operation for c in tx.changes)
        self.assertTrue(all(counts[k] > 0 for k in ("insert", "update", "delete")))
        validate_state(self.store.data)

    def test_rate_duration_and_stop_without_real_sleep(self):
        class Clock:
            value = 0.0
            waits = []

            def now(self):
                return self.value

            def wait(self, seconds):
                self.waits.append(seconds)
                self.value += seconds
                return False

        clock = Clock()
        # Scheduling is tested with a minimal planner, independent of business RNG.
        planner = type("Planner", (), {})()
        planner.rng = random.Random(1)
        planner.store = type("Store", (), {"sequence": 0})()
        planner.plan = lambda *_: None
        metrics = run(
            planner,
            RunConfig(duration_seconds=1, transactions_per_second=4),
            clock=clock.now,
            wait=clock.wait,
        )
        self.assertEqual(metrics["skipped"], 4)
        self.assertEqual(clock.waits, [0.25] * 4)
        stop = threading.Event()
        stop.set()
        self.assertEqual(run(planner, RunConfig(), stop)["committed"], 0)
        for parameters in (
            {"transactions_per_second": 0},
            {"duration_seconds": float("inf")},
            {"max_transactions": -1},
            {"rmrg_weight": 0},
        ):
            with self.assertRaises(ValueError):
                RunConfig(**parameters)


class FakeCursor:
    rowcount = 1

    def __init__(self, tx, company, fail=False):
        self.queries = []
        self.closed = False
        self.fail = fail
        self.rows = []
        for c in sorted(tx.changes, key=lambda c: (c.table, c.pk)):
            columns = [x[0] for x in SCHEMA[company][c.table]]
            self.rows.append(tuple(c.before[x] for x in columns) if c.before else None)

    def execute(self, query, parameters):
        self.queries.append((query, parameters))
        if self.fail and query.startswith(("INSERT", "UPDATE", "DELETE")):
            raise OSError("source write failed")

    def fetchone(self):
        return self.rows.pop(0)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.handle, self.committed, self.rolled_back = cursor, False, False

    def cursor(self):
        return self.handle

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class DatabaseAdapterTests(unittest.TestCase):
    def test_scc_delete_order_children_before_parent(self):
        store = MemoryStore(baseline())
        activity = Activity(store, PROFILE)
        store.commit(activity.plan("scc", "new_order", NOW))
        tx = activity.plan("scc", "delete_abandoned", NOW)
        connection = FakeConnection(FakeCursor(tx, "scc"))
        DBAPIWriter("scc", connection, "scc").commit(tx)
        deletes = [q for q, _ in connection.handle.queries if q.startswith("DELETE")]
        self.assertIn("sales_orders", deletes[-1])
        self.assertTrue(all("sales_order_lines" in q for q in deletes[:-1]))

    def test_parameterized_source_transactions_and_rollback(self):
        for co in ("rmrg", "scc"):
            store = MemoryStore(baseline())
            tx = Activity(store, PROFILE).plan(co, "new_customer", NOW)
            cursor = FakeCursor(tx, co)
            connection = FakeConnection(cursor)
            DBAPIWriter(co, connection, co).commit(tx)
            self.assertTrue(connection.committed)
            self.assertTrue(cursor.closed)
            for query, parameters in cursor.queries:
                self.assertNotIn("example.invalid", query)
                if query.startswith("INSERT"):
                    self.assertIn("%s", query)
                    if co == "rmrg":
                        self.assertNotIn('"row_version"', query)
                        self.assertNotIn('"created_at"', query)
            cursor = FakeCursor(tx, co, fail=True)
            connection = FakeConnection(cursor)
            with self.assertRaises(OSError):
                DBAPIWriter(co, connection, co).commit(tx)
            self.assertTrue(connection.rolled_back)
            self.assertFalse(connection.committed)
            self.assertTrue(cursor.closed)


if __name__ == "__main__":
    unittest.main()
