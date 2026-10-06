"""Business event identity, source fidelity, delivery edges and recovery tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from retail_simulator.changes import load_seed
from retail_simulator.config import Config
from retail_simulator.event_contract import (
    Record,
    make_record,
    expected_topics,
    TYPES,
    topic_name,
)
from retail_simulator.event_generation import EventConfig, facts, generate_records
from retail_simulator.event_producer import KafkaProducerAdapter, LocalProducer
from retail_simulator.events import prepare, run, validate_plan
from retail_simulator.snapshot import generate, encode
import hashlib

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
PROFILE = Config(
    rmrg_customers=24,
    scc_customers=16,
    rmrg_products=16,
    scc_products=12,
    rmrg_orders=40,
    scc_orders=20,
    return_fraction=0.8,
    cancel_fraction=0.15,
    open_fraction=0.1,
)


def plan(entries):
    return {
        "version": 1,
        "environment": "test",
        "deliveries": entries,
        "sha256": hashlib.sha256(encode(entries).encode()).hexdigest(),
    }


class EventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.snapshot = Path(cls.tmp.name) / "seed"
        cls.manifest = generate(PROFILE, cls.snapshot, "test")
        cls.data = load_seed(cls.snapshot, "test")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def entries(self, **kwargs):
        return generate_records(
            self.data,
            "test",
            self.manifest["fingerprint"],
            "run-26",
            NOW,
            EventConfig(events=150, **kwargs),
        )

    def test_all_fifteen_event_types_route_to_exact_five_topics(self):
        expected = {
            "pmdp-dev-rmrg-commerce-events-v1": {
                "orders-placed",
                "orders-cancelled",
                "payments-resolved",
                "shipments-handed-over",
                "shipments-delivered",
                "returns-requested",
                "returns-received",
            },
            "pmdp-dev-rmrg-inventory-events-v1": {"inventory-moved"},
            "pmdp-dev-rmrg-shopping-events-v1": {"shopping-viewed", "shopping-added"},
            "pmdp-dev-scc-commerce-events-v1": {"orders-entered", "payments-posted"},
            "pmdp-dev-scc-activity-events-v1": {
                "inventory-observed",
                "shopping-viewed",
                "shopping-added",
            },
        }
        observed = {}
        for company, kinds in TYPES.items():
            for kind in sorted(kinds):
                record = make_record(
                    "dev",
                    company,
                    kind,
                    "order:1",
                    "occurrence",
                    NOW,
                    NOW,
                    {"original": "payload"},
                    {"original": "provenance"},
                )
                event = record.validate("dev")
                self.assertEqual(event["event_type"], kind)
                self.assertEqual(event["payload"], {"original": "payload"})
                self.assertEqual(event["provenance"], {"original": "provenance"})
                observed.setdefault(record.topic, set()).add(kind)
                self.assertEqual(
                    record,
                    make_record(
                        "dev",
                        company,
                        kind,
                        "order:1",
                        "occurrence",
                        NOW,
                        NOW,
                        {"original": "payload"},
                        {"original": "provenance"},
                    ),
                )
                legacy = f"pmdp-dev-{company}-{kind}-v1"
                with self.assertRaisesRegex(ValueError, "Topic/key mismatch"):
                    replace(record, topic=legacy).validate("dev")
                with self.assertRaises(ValueError):
                    replace(record, topic=record.topic.replace("dev", "test")).validate(
                        "dev"
                    )
        self.assertEqual(observed, expected)
        self.assertEqual(set(expected_topics("dev")), set(expected))
        self.assertEqual(sum(map(len, TYPES.values())), 15)
        self.assertEqual(len(expected_topics("test")), 5)
        with self.assertRaises(ValueError):
            topic_name("prod", "rmrg", "orders-placed")
        with self.assertRaises(ValueError):
            topic_name("dev", "scc", "orders-placed")

    def test_fact_payloads_match_source_and_do_not_mutate(self):
        original = deepcopy(self.data)
        records = facts(self.data, "test", self.manifest["fingerprint"], NOW)
        types = set()
        for record in records:
            event = record.validate("test")
            types.add(event["event_type"])
            co, table = event["company"], event["provenance"]["source_table"]
            source = self.data[co][table][int(event["provenance"]["source_pk"])]
            for name, value in event["payload"].items():
                self.assertEqual(value, json.loads(encode(source))[name])
            if co == "scc":
                self.assertTrue(event["provenance"]["timezone_assumed"])
                self.assertNotIn("shipments", event["event_type"])
                self.assertNotIn("returns", event["event_type"])
        self.assertTrue(
            {
                "orders-placed",
                "payments-resolved",
                "shipments-delivered",
                "returns-requested",
                "inventory-moved",
                "orders-entered",
                "payments-posted",
                "inventory-observed",
            }
            <= types
        )
        self.assertEqual(self.data, original)

    def test_stable_fact_identities_and_order_keys(self):
        first = facts(self.data, "test", "fingerprint", NOW)
        second = facts(self.data, "test", "fingerprint", NOW)
        self.assertEqual(first, second)
        for r in first:
            event = r.validate("test")
            oid = event["payload"].get("order_id") or event["payload"].get(
                "sales_order_id"
            )
            if oid is not None:
                self.assertEqual(
                    r.key, f"{event['company']}:{event['source_instance']}:order:{oid}"
                )
        self.assertNotEqual(first[0].key.split(":")[1], "rmrg-retail-prod")

    def test_missing_scc_instants_not_fabricated(self):
        data = deepcopy(self.data)
        for r in data["scc"]["sales_orders"].values():
            r["entered_at"] = None
        kinds = [
            r.validate("test")["event_type"] for r in facts(data, "test", "fp", NOW)
        ]
        self.assertNotIn("orders-entered", kinds)

    def test_exact_duplicates_and_actual_delivery_reordering(self):
        entries = self.entries(
            duplicate_fraction=1,
            late_fraction=0.5,
            reorder_fraction=0.5,
            late_slots=120,
            reorder_slots=5,
        )
        by_id = {}
        indices = []
        for entry in entries:
            record = Record(**entry["record"])
            ident = record.validate("test")["event_id"]
            if ident in by_id:
                self.assertEqual(record, by_id[ident])
            else:
                indices.append(entry["generation_index"])
            by_id[ident] = record
        self.assertEqual(len(entries), 300)
        self.assertEqual(len(by_id), 150)
        self.assertNotEqual(indices, sorted(indices))
        self.assertTrue(any("late" in e["edge_case"] for e in entries))
        last = {}
        inversions = []
        for entry in entries:
            if entry["edge_case"] == "duplicate":
                continue
            event = Record(**entry["record"]).validate("test")
            key = event["aggregate_key"]
            if key in last and event["occurred_at"] < last[key]:
                inversions.append(key)
            last[key] = event["occurred_at"]
        self.assertTrue(inversions, "Expected event-time inversion within an aggregate")
        self.assertEqual(
            entries,
            self.entries(
                duplicate_fraction=1,
                late_fraction=0.5,
                reorder_fraction=0.5,
                late_slots=120,
                reorder_slots=5,
            ),
        )

    def test_session_context_conversion_anonymous_and_source_ids(self):
        entries = self.entries(
            duplicate_fraction=0, late_fraction=0, reorder_fraction=0
        )
        sessions = {}
        for entry in entries:
            event = Record(**entry["record"]).validate("test")
            if event["provenance"]["mode"] != "synthetic_session":
                continue
            co, payload = event["company"], event["payload"]
            product_table, pid = (
                ("products", "product_id")
                if co == "rmrg"
                else ("item_master", "item_id")
            )
            self.assertIn(payload[pid], self.data[co][product_table])
            if payload["customer_id"] is not None:
                customer = self.data[co][
                    "customers" if co == "rmrg" else "customer_master"
                ][payload["customer_id"]]
                self.assertNotEqual(customer.get("customer_type"), "WALKIN")
            if event["event_type"] == "shopping-added":
                self.assertIn(event["aggregate_key"], sessions)
                self.assertGreaterEqual(
                    event["occurred_at"],
                    sessions[event["aggregate_key"]]["occurred_at"],
                )
            else:
                sessions[event["aggregate_key"]] = event
            self.assertLessEqual(event["occurred_at"], event["produced_at"])
        self.assertTrue(sessions)
        self.assertTrue(
            any(e["payload"]["customer_id"] is None for e in sessions.values())
        )

    def test_contract_environment_version_and_checksum_fail_closed(self):
        p = plan(self.entries())
        validate_plan(p, "test")
        with self.assertRaises(ValueError):
            validate_plan(p, "dev")
        changed = deepcopy(p)
        changed["deliveries"][0]["record"]["key"] += "corruption"
        with self.assertRaises(ValueError):
            validate_plan(changed, "test")
        record = Record(**p["deliveries"][0]["record"])
        payload = json.loads(record.value)
        payload["payload_version"] = 2
        with self.assertRaises(ValueError):
            replace(record, value=encode(payload)).validate("test")
        with self.assertRaises(ValueError):
            make_record(
                "test",
                "rmrg",
                "shopping-viewed",
                "session:1",
                "1",
                NOW.replace(tzinfo=None),
                NOW,
                {},
                {},
            )

    def test_rate_duration_stop_and_resume(self):
        p = plan(self.entries(duplicate_fraction=0))
        ticks = [0.0]

        def wait(delay):
            ticks[0] += delay
            return False

        with tempfile.TemporaryDirectory() as tmp:
            with LocalProducer(Path(tmp), "test") as producer:
                counts = run(
                    p,
                    producer,
                    "test",
                    rate=2,
                    duration=1,
                    clock=lambda: ticks[0],
                    wait=wait,
                )
                self.assertEqual(counts["acknowledged"], 2)
            ticks[0] = 0
            with LocalProducer(Path(tmp), "test") as producer:
                counts = run(
                    p,
                    producer,
                    "test",
                    rate=2,
                    duration=1,
                    clock=lambda: ticks[0],
                    wait=wait,
                )
                self.assertEqual(counts, {"acknowledged": 2, "replayed": 2})
            stopped = threading.Event()
            stopped.set()
            with LocalProducer(Path(tmp), "test") as producer:
                self.assertEqual(
                    run(p, producer, "test", stop=stopped)["acknowledged"], 0
                )

    def test_local_lost_ack_replay_corruption_and_writer_lock(self):
        record = Record(**self.entries()[0]["record"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with LocalProducer(root, "test") as producer:
                self.assertTrue(producer.send(1, record))
                with self.assertRaises(ValueError):
                    LocalProducer(root, "test")
            with LocalProducer(root, "test") as producer:
                self.assertFalse(producer.send(1, record))
                with self.assertRaises(ValueError):
                    producer.send(3, record)
            (root / "000000000001.json").write_text("{}")
            with LocalProducer(root, "test") as producer:
                with self.assertRaises(ValueError):
                    producer.send(1, record)

    def test_publish_failure_does_not_acknowledge(self):
        record = Record(**self.entries()[0]["record"])
        with tempfile.TemporaryDirectory() as tmp:
            with LocalProducer(Path(tmp), "test") as producer:
                with patch(
                    "retail_simulator.event_producer.os.replace",
                    side_effect=OSError("disk"),
                ):
                    with self.assertRaises(OSError):
                        producer.send(1, record)
                self.assertEqual(producer.sequence, 0)
                self.assertFalse((Path(tmp) / "000000000001.json").exists())
                self.assertTrue(producer.send(1, record))

    def test_missing_delivery_and_truncated_plan_rejected(self):
        entries = self.entries()
        record = Record(**entries[0]["record"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with LocalProducer(root, "test") as producer:
                producer.send(1, record)
                producer.send(2, Record(**entries[1]["record"]))
            with LocalProducer(root, "test") as producer:
                with self.assertRaises(ValueError):
                    run(plan(entries[:1]), producer, "test")
            (root / "000000000001.json").unlink()
            with self.assertRaises(ValueError):
                LocalProducer(root, "test")

    def test_kafka_boundary_exact_bytes_headers_and_ack_failure(self):
        record = Record(**self.entries()[0]["record"])
        calls = []

        class Ack:
            def result(self, timeout):
                self.timeout = timeout

        def submit(*args):
            calls.append(args)
            return Ack()

        flushed = []
        adapter = KafkaProducerAdapter("test", submit, lambda: flushed.append(True))
        self.assertTrue(adapter.send(1, record))
        self.assertEqual(
            calls[0][:3], (record.topic, record.key.encode(), record.value.encode())
        )
        self.assertEqual(calls[0][3]["payload_version"], b"1")

        class FailedAck:
            def result(self, timeout):
                raise TimeoutError("uncertain broker acknowledgement")

        adapter = KafkaProducerAdapter(
            "test", lambda *args: FailedAck(), lambda: flushed.append(True)
        )
        with self.assertRaises(TimeoutError):
            run(plan(self.entries()), adapter, "test")
        self.assertEqual(flushed, [True])

    def test_config_validation(self):
        for kwargs in (
            {"events": 0},
            {"seed": True},
            {"late_fraction": float("nan")},
            {"duplicate_fraction": 1.1},
            {"rmrg_weight": 0},
            {"late_slots": -1},
        ):
            with self.assertRaises(ValueError):
                EventConfig(**kwargs)

    def test_prepare_roundtrip_and_wrong_environment(self):
        p = prepare(self.snapshot, "test", EventConfig(events=10))
        validate_plan(json.loads(encode(p)), "test")
        self.assertEqual(p["snapshot_fingerprint"], self.manifest["fingerprint"])
        with self.assertRaises(ValueError):
            prepare(self.snapshot, "dev", EventConfig(events=10))


if __name__ == "__main__":
    unittest.main()
