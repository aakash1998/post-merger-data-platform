"""KAN-32 safety, replay, rollback, typed import and deployment contracts."""

from copy import deepcopy
from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from retail_simulator.config import Config
from retail_simulator.contracts import SCHEMA
from retail_simulator.deployment import (
    Target,
    read_snapshot,
    ordered_rows,
    load_company,
    ensure_schema,
)
from retail_simulator.snapshot import generate, LOAD_ORDER
from retail_simulator.source_ddl import statements, render
from retail_simulator.validation import FKS


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        self.connection.sql.append(sql)

    def executemany(self, sql, values):
        self.connection.sql.append(sql)
        table = sql.split(".")[1].split(" ")[0].strip('"`')
        cols = [c[0] for c in SCHEMA[self.connection.company][table]]
        pk = cols[0]
        for value in values:
            row = dict(zip(cols, value))
            self.connection.rows[table][row[pk]] = row

    def close(self):
        pass


class FakeConnection:
    def __init__(self, company, rows):
        self.company = company
        self.rows = deepcopy(rows)
        self.sql = []
        self.committed = self.rolled_back = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.snapshot = cls.root / "seed"
        generate(
            Config(
                rmrg_customers=12,
                scc_customers=12,
                rmrg_products=12,
                scc_products=12,
                rmrg_orders=12,
                scc_orders=6,
                return_fraction=0.5,
            ),
            cls.snapshot,
            "test",
        )
        cls.manifest, cls.data = read_snapshot(cls.snapshot, "test")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_ddl_artifacts_match_contract_and_fk_order(self):
        for co in SCHEMA:
            self.assertEqual(
                Path(__file__)
                .parents[1]
                .joinpath("src/retail_simulator/ddl", co + ".sql")
                .read_text(),
                render(co),
            )
            rank = {t: i for i, t in enumerate(LOAD_ORDER[co])}
            for table in SCHEMA[co]:
                for _, parent, _ in FKS[co].get(table, []):
                    self.assertLessEqual(rank[parent], rank[table])
            self.assertEqual(
                sum(s.startswith("CREATE TABLE") for s in statements(co)),
                len(SCHEMA[co]),
            )
        mysql = render("scc")
        self.assertNotIn("FOREIGN KEY (`customer_id_ref`)", mysql)
        self.assertNotIn("FOREIGN KEY (`item_id_ref`)", mysql)
        self.assertNotIn("CHECK (`amount`", mysql)
        self.assertNotIn("row_version", mysql)

    def test_environment_and_target_guards(self):
        with self.assertRaisesRegex(ValueError, "dev/test"):
            Target.from_env("rmrg", "prod")
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            ValueError, "PMDP_RMRG_POSTGRES_HOST"
        ):
            Target.from_env("rmrg", "dev")
        ca = self.root / "ca.pem"
        ca.write_text("test only")
        variables = {
            "PMDP_SCC_MYSQL_" + k: v
            for k, v in dict(
                HOST="host",
                PORT="3306",
                DATABASE="scc",
                USER="test",
                PASSWORD="secret",
                SERVICE="pmdp-test-scc-mysql",
                SSL_CA=str(ca),
            ).items()
        }
        with patch.dict(os.environ, variables, clear=True):
            target = Target.from_env("scc", "test")
            self.assertNotIn("secret", repr(target))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                Target.from_env("scc", "dev")
            os.environ["PMDP_SCC_MYSQL_DATABASE"] = "defaultdb"
            self.assertEqual(Target.from_env("scc", "test").database, "defaultdb")
            os.environ["PMDP_SCC_MYSQL_DATABASE"] = "unexpected"
            with self.assertRaisesRegex(ValueError, "must be scc or defaultdb"):
                Target.from_env("scc", "test")

    def test_typed_snapshot_and_checksum_rejection(self):
        self.assertIsInstance(
            next(iter(self.data["rmrg"]["products"].values()))["list_price"], Decimal
        )
        with self.assertRaisesRegex(ValueError, "environment"):
            read_snapshot(self.snapshot, "dev")
        file = self.snapshot / "scc/item_master.jsonl"
        original = file.read_bytes()
        try:
            file.write_bytes(original + b"{}\n")
            with self.assertRaisesRegex(ValueError, "incomplete or changed"):
                read_snapshot(self.snapshot, "test")
        finally:
            file.write_bytes(original)

    def test_self_references_topologically_ordered_and_cycle_rejected(self):
        rows = {
            1: {"category_id": 1, "parent_category_id": 9},
            9: {"category_id": 9, "parent_category_id": None},
        }
        self.assertEqual(
            [
                r["category_id"]
                for r in ordered_rows("rmrg", "product_categories", rows)
            ],
            [9, 1],
        )
        rows[9]["parent_category_id"] = 1
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            ordered_rows("rmrg", "product_categories", rows)

    def run_load(self, co, rows, check=False, validation=None):
        connection = FakeConnection(co, rows)
        with patch(
            "retail_simulator.deployment.read_tables",
            side_effect=lambda cur, *args, **kwargs: deepcopy(connection.rows),
        ), patch("retail_simulator.deployment.advance_counters"), patch(
            "retail_simulator.deployment.validate_state", side_effect=validation
        ):
            try:
                result = load_company(connection, co, self.data, check)
            except BaseException:
                self.last_connection = connection
                raise
        return connection, result

    def test_empty_load_preserves_final_inventory_and_all_ids(self):
        for co in SCHEMA:
            connection, result = self.run_load(co, {t: {} for t in SCHEMA[co]})
            self.assertTrue(connection.committed)
            self.assertEqual(connection.rows, self.data[co])
            self.assertEqual(result["action"], "loaded")
            self.assertFalse(
                any(
                    s.startswith("UPDATE")
                    or s.startswith("DELETE")
                    or s.startswith("ALTER")
                    for s in connection.sql
                )
            )

    def test_exact_replay_issues_no_inserts(self):
        connection, result = self.run_load("rmrg", self.data["rmrg"])
        self.assertEqual(result["action"], "exact_replay")
        self.assertFalse(any(s.startswith("INSERT") for s in connection.sql))

    def test_unexpected_existing_data_fails_without_overwrite(self):
        rows = deepcopy(self.data["rmrg"])
        next(iter(rows["inventory"].values()))["quantity_on_hand"] += 1
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            self.run_load("rmrg", rows)
        self.assertTrue(self.last_connection.rolled_back)
        self.assertFalse(any(s.startswith("INSERT") for s in self.last_connection.sql))

    def test_post_load_validation_failure_rolls_back(self):
        with self.assertRaisesRegex(ValueError, "relationship"):
            self.run_load(
                "scc",
                {t: {} for t in SCHEMA["scc"]},
                validation=ValueError("relationship invalid"),
            )
        self.assertTrue(self.last_connection.rolled_back)
        self.assertFalse(self.last_connection.committed)


if __name__ == "__main__":
    unittest.main()
