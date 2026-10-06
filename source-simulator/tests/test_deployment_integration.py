"""Opt-in real-engine tests. Use only isolated, initially absent source namespaces.

PostgreSQL: PMDP_KAN32_TEST_POSTGRES_DSN (disposable database).
MySQL: PMDP_KAN32_TEST_MYSQL=1 plus PMDP_ENV=test and SCC Target variables.
Tests retain schemas/seed for inspection and never drop an existing namespace.
"""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

from retail_simulator.config import Config
from retail_simulator.deployment import (
    Target,
    read_snapshot,
    ensure_schema,
    load_company,
    namespace_exists,
)
from retail_simulator.snapshot import generate


class EngineTests(unittest.TestCase):
    def snapshot(self, root):
        path = Path(root) / "seed"
        generate(
            Config(
                rmrg_customers=12,
                scc_customers=12,
                rmrg_products=12,
                scc_products=12,
                rmrg_orders=24,
                scc_orders=8,
                return_fraction=0.5,
            ),
            path,
            "test",
        )
        return read_snapshot(path, "test")[1]

    def roundtrip(self, connection, company, data):
        with connection.cursor() as cursor:
            self.assertFalse(
                namespace_exists(cursor, company),
                "Integration target must have an absent source namespace",
            )
        connection.commit()
        ensure_schema(connection, company, "test")
        self.assertEqual(load_company(connection, company, data)["action"], "loaded")
        ensure_schema(connection, company, "test")
        self.assertEqual(
            load_company(connection, company, data)["action"], "exact_replay"
        )
        self.assertEqual(
            load_company(connection, company, data, check=True)["action"], "checked"
        )
        changed = deepcopy(data)
        table = "inventory" if company == "rmrg" else "stock_balance"
        next(iter(changed[company][table].values()))["quantity_on_hand"] = 999
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            load_company(connection, company, changed)
        load_company(connection, company, data, check=True)

    @unittest.skipUnless(
        os.environ.get("PMDP_KAN32_TEST_POSTGRES_DSN"),
        "No disposable PostgreSQL configured",
    )
    def test_postgres_load_constraints_audit_sequence_and_drift(self):
        import psycopg

        with tempfile.TemporaryDirectory() as root, psycopg.connect(
            os.environ["PMDP_KAN32_TEST_POSTGRES_DSN"]
        ) as connection:
            data = self.snapshot(root)
            self.roundtrip(connection, "rmrg", data)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO rmrg.product_categories(category_code,category_name,created_by,updated_by) VALUES ('KAN32-TEST','Test','integration','integration') RETURNING category_id,created_at,updated_at,row_version"
                )
                pk, created, updated, version = cursor.fetchone()
                self.assertGreater(pk, max(data["rmrg"]["product_categories"]))
                self.assertEqual(created, updated)
                self.assertEqual(version, 1)
                cursor.execute(
                    "UPDATE rmrg.product_categories SET category_name='Changed',updated_by='test' WHERE category_id=%s RETURNING created_at,updated_at,row_version",
                    (pk,),
                )
                created2, updated2, version2 = cursor.fetchone()
                self.assertEqual(created2, created)
                self.assertGreaterEqual(updated2, updated)
                self.assertEqual(version2, 2)
                cursor.execute(
                    "UPDATE rmrg.product_categories SET category_name='Changed' WHERE category_id=%s RETURNING row_version",
                    (pk,),
                )
                self.assertEqual(cursor.fetchone()[0], 2)
            connection.rollback()
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.Error):
                    cursor.execute(
                        "UPDATE rmrg.customers SET customer_id=999 WHERE customer_id=1"
                    )
            connection.rollback()
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.Error):
                    cursor.execute(
                        "UPDATE rmrg.inventory SET store_id=NULL,warehouse_id=NULL WHERE inventory_id=1"
                    )
            connection.rollback()
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.Error):
                    cursor.execute(
                        "UPDATE rmrg.customer_addresses SET customer_id=99999 WHERE customer_address_id=1"
                    )
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE rmrg.customers DISABLE TRIGGER customers_audit"
                )
                with self.assertRaisesRegex(ValueError, "differs"):
                    ensure_schema(connection, "rmrg", "test")
            # ensure_schema failure rolls back the deliberate drift.
            ensure_schema(connection, "rmrg", "test")

    @unittest.skipUnless(
        os.environ.get("PMDP_KAN32_TEST_MYSQL") == "1", "No disposable MySQL configured"
    )
    def test_mysql_load_constraints_legacy_evidence_and_auto_increment(self):
        import pymysql

        self.assertEqual(os.environ.get("PMDP_ENV"), "test")
        target = Target.from_env("scc", "test")
        with tempfile.TemporaryDirectory() as root:
            connection = target.connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
                    )
                connection.commit()
                data = self.snapshot(root)
                self.roundtrip(connection, "scc", data)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO scc.customer_master(customer_code) VALUES ('')"
                    )
                    self.assertGreater(
                        cursor.lastrowid, max(data["scc"]["customer_master"])
                    )
                    cursor.execute(
                        "UPDATE scc.stock_balance SET quantity_on_hand=-10 WHERE stock_balance_id=1"
                    )
                    cursor.execute(
                        "INSERT INTO scc.customer_master(customer_code) VALUES ('')"
                    )
                connection.rollback()
                with connection.cursor() as cursor:
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute(
                            "UPDATE scc.sales_order_lines SET line_number=0 WHERE sales_order_line_id=1"
                        )
                connection.rollback()
                with connection.cursor() as cursor:
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute(
                            "UPDATE scc.stock_balance SET item_id=999999 WHERE stock_balance_id=1"
                        )
                connection.rollback()
                with connection.cursor() as cursor:
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute(
                            "UPDATE scc.customer_master SET customer_id=999999 WHERE customer_id=1"
                        )
                connection.rollback()
            finally:
                connection.close()
