"""Exact scenario reproducibility, business outcomes and recovery acceptance tests."""

from collections import Counter
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from retail_simulator.event_contract import Record
from retail_simulator.event_producer import LocalProducer
from retail_simulator.scenarios import (
    ScenarioConfig,
    RECIPES,
    build,
    identity,
    inventory,
    replay,
    verify_bundle,
)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build_case(self, name, **kwargs):
        cfg = ScenarioConfig(name=name, **kwargs)
        output = self.root / name
        result = build(cfg, output, "test")
        state = json.loads((output / "final-state.json").read_text())
        return cfg, output, result, state

    def test_every_named_scenario_exact_artifact_bytes_and_reuse(self):
        for name in RECIPES:
            with self.subTest(name=name):
                cfg = ScenarioConfig(name=name)
                first, second = self.root / (name + "-a"), self.root / (name + "-b")
                m1 = build(cfg, first, "test")
                m2 = build(cfg, second, "test")
                self.assertEqual(m1, m2)
                self.assertEqual(inventory(first), inventory(second))
                for filename in m1["files"]:
                    self.assertEqual(
                        (first / filename).read_bytes(),
                        (second / filename).read_bytes(),
                    )
                self.assertEqual(build(cfg, first, "test"), m1)

    def test_seed_clock_config_and_environment_control_identity(self):
        cfg, output, result, _ = self.build_case("normal")
        other = build(replace(cfg, seed=28), self.root / "other", "test")
        self.assertNotEqual(result["seed_fingerprint"], other["seed_fingerprint"])
        self.assertNotEqual(
            result["summary"]["final_state_sha256"],
            other["summary"]["final_state_sha256"],
        )
        for changed in (
            replace(cfg, seed=28),
            replace(cfg, step_seconds=120),
            replace(cfg, event_count=201),
            replace(cfg, rounds=2),
        ):
            with self.assertRaises(ValueError):
                build(changed, output, "test")
        with self.assertRaises(ValueError):
            build(cfg, output, "dev")
        with self.assertRaises(ValueError):
            build(cfg, self.root / "prod", "prod")

    def test_custom_profile_and_rounds(self):
        _, _, result, state = self.build_case(
            "normal",
            rounds=2,
            seed=99,
            seed_config={"rmrg_customers": 30, "max_lines": 2},
        )
        self.assertEqual(len(state["rmrg"]["customers"]), 32)
        self.assertEqual(len(state["rmrg"]["orders"]), 2)
        self.assertTrue(
            all(o["order_status"] == "fulfilled" for o in state["rmrg"]["orders"])
        )
        self.assertTrue(
            all(o["order_status"] == "PAID" for o in state["scc"]["sales_orders"])
        )
        self.assertGreater(result["summary"]["transactions"], 10)

    def test_cancellation_releases_all_reserved_units(self):
        _, _, _, state = self.build_case("cancellations", rounds=2)
        self.assertTrue(
            all(o["order_status"] == "cancelled" for o in state["rmrg"]["orders"])
        )
        self.assertTrue(
            all(i["quantity_reserved"] == 0 for i in state["rmrg"]["inventory"])
        )
        self.assertFalse(
            any(
                p["operation_type"] == "capture" and p["payment_status"] == "succeeded"
                for p in state["rmrg"]["payments"]
            )
        )
        self.assertTrue(
            any(
                m["movement_type"] == "release"
                for m in state["rmrg"]["stock_movements"]
            )
        )

    def test_returns_have_settled_refunds_and_no_quarantine_balance(self):
        _, output, _, state = self.build_case("returns_refunds", rounds=2)
        self.assertEqual(len(state["rmrg"]["returns"]), 2)
        self.assertTrue(
            all(r["return_status"] == "closed" for r in state["rmrg"]["returns"])
        )
        self.assertTrue(
            all(i["quantity_unavailable"] == 0 for i in state["rmrg"]["inventory"])
        )
        refunds = [
            p for p in state["rmrg"]["payments"] if p["operation_type"] == "refund"
        ]
        self.assertEqual(len(refunds), 2)
        self.assertTrue(all(p["payment_status"] == "succeeded" for p in refunds))
        events = json.loads((output / "events/plan.json").read_text())["deliveries"]
        self.assertTrue(
            any(
                Record(**e["record"]).validate("test")["event_type"]
                == "returns-received"
                for e in events
            )
        )

    def test_customer_and_inventory_scenarios_meaningfully_change_sources(self):
        _, output, _, state = self.build_case("customer_updates")
        trace = json.loads((output / "commands.json").read_text())
        self.assertEqual([r["command"] for r in trace].count("update_customer"), 2)
        journal = list((output / "database/transactions").glob("*.json"))
        self.assertTrue(
            any(
                json.loads(p.read_text())["activity"] == "update_customer"
                for p in journal
            )
        )
        _, _, _, state = self.build_case("inventory_changes", rounds=2)
        receipts = [
            m
            for m in state["rmrg"]["stock_movements"]
            if m["movement_type"] == "receipt"
        ]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(m["quantity_delta"] > 0 for m in receipts))

    def test_scc_quality_cases_and_child_first_deletion_use_existing_rules(self):
        cfg, output, _, state = self.build_case("scc_messy")
        self.assertEqual(cfg.profile().messy_fraction, 1)
        stocks = state["scc"]["stock_balance"]
        pairs = Counter((s["item_id"], s["location_id"]) for s in stocks)
        self.assertTrue(any(count > 1 for count in pairs.values()))
        self.assertTrue(
            any(
                s["quantity_on_hand"] is None or float(s["quantity_on_hand"]) < 0
                for s in stocks
            )
        )
        txs = [
            json.loads(p.read_text())
            for p in sorted((output / "database/transactions").glob("*.json"))
        ]
        corrected = next(t for t in txs if t["activity"] == "correct_posting")
        posting = next(
            c for c in corrected["changes"] if c["table"] == "payment_transactions"
        )
        self.assertNotEqual(
            posting["before"]["posted_flag"], posting["after"]["posted_flag"]
        )
        self.assertEqual(
            posting["before"]["updated_at"], posting["after"]["updated_at"]
        )
        deleted = next(t for t in txs if t["activity"] == "delete_abandoned")
        self.assertTrue(
            any(
                c["table"] == "sales_order_lines" and c["after"] is None
                for c in deleted["changes"]
            )
        )
        self.assertEqual(len(state["scc"]["sales_orders"]), 1)

    def test_duplicate_and_source_replay_have_no_double_business_effect(self):
        cfg, output, result, _ = self.build_case("duplicate_replay")
        self.assertEqual(result["summary"]["transaction_replays"], 2)
        events = json.loads((output / "events/plan.json").read_text())["deliveries"]
        counts = Counter(e["record"]["value"] for e in events)
        self.assertEqual(set(counts.values()), {2})
        before = inventory(output)
        replayed = replay(cfg, output, "test")
        self.assertEqual(
            replayed["recovered_transactions"], result["summary"]["transactions"]
        )
        self.assertEqual(replayed["replayed_deliveries"], 400)
        self.assertEqual(inventory(output), before)

    def test_late_recipe_inverts_same_aggregate_event_time(self):
        _, output, _, _ = self.build_case("late_out_of_order")
        entries = json.loads((output / "events/plan.json").read_text())["deliveries"]
        self.assertTrue(any("late" in e["edge_case"] for e in entries))
        seen = {}
        inversions = []
        for entry in entries:
            event = Record(**entry["record"]).validate("test")
            key = event["aggregate_key"]
            if key in seen and event["occurred_at"] < seen[key]:
                inversions.append(key)
            seen[key] = event["occurred_at"]
        self.assertTrue(inversions)

    def test_failed_build_discards_partial_output_and_restarts_identically(self):
        cfg = ScenarioConfig(name="returns_refunds")
        output = self.root / "restart"
        with patch.object(
            LocalProducer, "send", side_effect=OSError("simulated disk failure")
        ):
            with self.assertRaises(OSError):
                build(cfg, output, "test")
        self.assertFalse(output.exists())
        restarted = build(cfg, output, "test")
        clean = build(cfg, self.root / "clean", "test")
        self.assertEqual(restarted, clean)
        replay(cfg, output, "test")

    def test_command_failure_control_regenerates_without_partial_publication(self):
        cfg = ScenarioConfig(name="normal")
        output = self.root / "injected"
        with self.assertRaisesRegex(OSError, "after 3 commands"):
            build(cfg, output, "test", fail_after=3)
        self.assertFalse(output.exists())
        self.assertEqual(
            build(cfg, output, "test"), build(cfg, self.root / "uninterrupted", "test")
        )

    def test_corruption_missing_extra_and_implementation_drift_fail_closed(self):
        cfg, output, _, _ = self.build_case("normal")
        for file in (
            "final-state.json",
            "database/transactions/000000000001.json",
            "events/plan.json",
        ):
            target = output / file
            original = target.read_bytes()
            target.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                replay(cfg, output, "test")
            target.write_bytes(original)
        extra = output / "extra.json"
        extra.write_text("{}")
        with self.assertRaises(ValueError):
            build(cfg, output, "test")
        extra.unlink()
        with patch(
            "retail_simulator.scenarios.implementation_digest", return_value="changed"
        ):
            with self.assertRaises(ValueError):
                build(cfg, output, "test")
        verify_bundle(output, identity(cfg, "test"))
        path = output / "scenario.json"
        value = json.loads(path.read_text())
        value["summary"]["transactions"] = 999
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "manifest checksum"):
            replay(cfg, output, "test")

    def test_invalid_config_rejected_before_generation(self):
        for kw in (
            {"name": "unknown"},
            {"seed": True},
            {"rounds": 0},
            {"clock_start": "2025-04-01"},
            {"clock_start": "2024-01-01T00:00:00+00:00"},
            {"seed_config": {"seed": 4}},
            {"seed_config": {"rmrg_orders": 1}},
            {"seed_config": {"bogus": 1}},
        ):
            with self.subTest(config=kw), self.assertRaises((ValueError, TypeError)):
                ScenarioConfig(**kw)

    def test_cli_separate_processes_hash_seeds_and_replay(self):
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"name": "late_out_of_order", "event_count": 60}))
        outputs = [self.root / "process-a", self.root / "process-b"]
        for hashseed, output in zip(("1", "9824"), outputs):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "retail_simulator.scenarios",
                    "--config",
                    str(profile),
                    "--output",
                    str(output),
                ],
                env={**os.environ, "PMDP_ENV": "test", "PYTHONHASHSEED": hashseed},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(inventory(outputs[0]), inventory(outputs[1]))
        self.assertEqual(
            (outputs[0] / "scenario.json").read_bytes(),
            (outputs[1] / "scenario.json").read_bytes(),
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "retail_simulator.scenarios",
                "--output",
                str(outputs[0]),
                "--replay",
            ],
            env={**os.environ, "PMDP_ENV": "test"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scenario_replayed", result.stderr)


if __name__ == "__main__":
    unittest.main()
