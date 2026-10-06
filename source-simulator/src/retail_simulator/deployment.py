"""Fail-closed, TLS-verified dev/test deployment of the KAN-24 seed snapshot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from .changes import Database, load_seed, validate_state
from .config import environment
from .contracts import SCHEMA
from .snapshot import LOAD_ORDER, encode
from .source_ddl import render, statements
from .validation import FKS, require

LOG = logging.getLogger(__name__)
PREFIX = {"rmrg": "PMDP_RMRG_POSTGRES_", "scc": "PMDP_SCC_MYSQL_"}


@dataclass(frozen=True, repr=False)
class Target:
    company: str
    env: str
    host: str
    port: int
    database: str
    user: str
    password: str
    ca: str
    service: str

    @classmethod
    def from_env(cls, company: str, env: str) -> Target:
        require(env in {"dev", "test"}, "Database seed deployment requires dev/test")
        prefix = PREFIX[company]
        values = {}
        for key in (
            "HOST",
            "PORT",
            "DATABASE",
            "USER",
            "PASSWORD",
            "SERVICE",
            "SSLROOTCERT" if company == "rmrg" else "SSL_CA",
        ):
            value = os.environ.get(prefix + key)
            require(bool(value), "Missing environment variable: " + prefix + key)
            values[key] = value
        role = "postgres" if company == "rmrg" else "mysql"
        require(
            values["SERVICE"] == f"pmdp-{env}-{company}-{role}",
            "Service/environment mismatch",
        )
        require(
            company != "scc" or values["DATABASE"] in {"scc", "defaultdb"},
            "SCC bootstrap database must be scc or defaultdb",
        )
        require(
            values["PORT"].isdigit() and 1 <= int(values["PORT"]) <= 65535,
            "Invalid database port",
        )
        require(
            not any(x in values["HOST"] for x in ("/", "@", " ", "\n")),
            "HOST must be a hostname, not a URI",
        )
        ca = Path(values["SSLROOTCERT" if company == "rmrg" else "SSL_CA"])
        require(
            ca.is_absolute() and ca.is_file(),
            "Aiven CA must be an existing absolute file path",
        )
        return cls(
            company,
            env,
            values["HOST"],
            int(values["PORT"]),
            values["DATABASE"],
            values["USER"],
            values["PASSWORD"],
            str(ca),
            values["SERVICE"],
        )

    def connect(self) -> Any:
        if self.company == "rmrg":
            import psycopg

            return psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
                sslmode="verify-full",
                sslrootcert=self.ca,
                connect_timeout=15,
                application_name="pmdp-kan32-loader",
            )
        import pymysql

        # Connect without a default database so approved scc can be created if absent.
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            charset="utf8mb4",
            autocommit=False,
            database=self.database if self.database != "scc" else None,
            ssl_ca=self.ca,
            ssl_verify_cert=True,
            ssl_verify_identity=True,
            connect_timeout=15,
            read_timeout=120,
            write_timeout=120,
        )


def read_snapshot(path: Path, env: str) -> tuple[dict[str, Any], Database]:
    require(env in {"dev", "test"}, "Seed deployment requires dev/test")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["environment"] == env, "Snapshot environment mismatch")
    require(
        manifest["generator_version"] == "0.1.0",
        "Unsupported snapshot generator version",
    )
    require(
        manifest["schema_sha256"]
        == hashlib.sha256(encode(SCHEMA).encode()).hexdigest(),
        "Snapshot column contract mismatch",
    )
    require(
        manifest["load_order"] == LOAD_ORDER,
        "Snapshot load order differs from approved FK order",
    )
    expected = {
        f"{co}/{table}.jsonl" for co, tables in SCHEMA.items() for table in tables
    } | {"matching_truth.jsonl"}
    require(set(manifest["files"]) == expected, "Snapshot file inventory mismatch")
    require(
        manifest["source_instances"] == {co: f"{co}-retail-{env}" for co in SCHEMA},
        "Snapshot source instance mismatch",
    )
    identity = {
        key: manifest[key]
        for key in ("generator_version", "schema_sha256", "config", "environment")
    }
    require(
        manifest["fingerprint"]
        == hashlib.sha256(encode(identity).encode()).hexdigest(),
        "Snapshot fingerprint mismatch",
    )
    data = load_seed(
        path, env
    )  # checksums, exact types, PK/FK and business/ledger reconciliation
    return manifest, data


def ordered_rows(
    company: str, table: str, rows: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Topologically sort self references; never assume IDs encode parent order."""
    refs = [
        child for child, parent, _ in FKS[company].get(table, []) if parent == table
    ]
    if not refs:
        return [rows[pk] for pk in sorted(rows)]
    dependencies = {
        pk: {r[cols[0]] for cols in refs if r[cols[0]] is not None}
        for pk, r in rows.items()
    }
    dependents: dict[int, list[int]] = {}
    for pk, parents in dependencies.items():
        for parent in parents:
            require(parent in rows, f"Missing self-reference: {company}.{table}")
            dependents.setdefault(parent, []).append(pk)
    ready = sorted(pk for pk, parents in dependencies.items() if not parents)
    result = []
    while ready:
        level, ready = ready, []
        for pk in level:
            result.append(rows[pk])
            for child in dependents.get(pk, []):
                dependencies[child].remove(pk)
                if not dependencies[child]:
                    ready.append(child)
        ready.sort()
    require(len(result) == len(rows), f"Cyclic self-reference: {company}.{table}")
    return result


def schema_digest(cursor: Any, company: str) -> str:
    """Fingerprint live definitions, excluding mutable counters and our receipt comment."""
    if company == "rmrg":
        queries = [
            "SELECT table_name, column_name, ordinal_position, data_type, udt_name, is_nullable, column_default, character_maximum_length, numeric_precision, numeric_scale, is_identity, identity_generation FROM information_schema.columns WHERE table_schema='rmrg' ORDER BY table_name, ordinal_position",
            "SELECT c.relname, con.conname, pg_get_constraintdef(con.oid), con.convalidated FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rmrg' ORDER BY c.relname, con.conname",
            "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='rmrg' ORDER BY tablename,indexname",
            "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rmrg' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
            "SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='rmrg' ORDER BY p.proname",
        ]
        definitions = []
        for query in queries:
            cursor.execute(query)
            definitions.append(cursor.fetchall())
    else:
        cursor.execute(
            "SELECT table_name, engine FROM information_schema.tables WHERE table_schema='scc' ORDER BY table_name"
        )
        tables = cursor.fetchall()
        require(
            {r[0] for r in tables} == set(SCHEMA["scc"])
            and all(r[1] == "InnoDB" for r in tables),
            "Unexpected SCC tables/engine",
        )
        definitions = []
        for table, _ in tables:
            cursor.execute(f"SHOW CREATE TABLE scc.`{table}`")
            sql = cursor.fetchone()[1]
            sql = re.sub(r" AUTO_INCREMENT=\d+", "", sql)
            sql = re.sub(r" COMMENT='(?:''|\\.|[^'])*'", "", sql)
            definitions.append(sql)
        cursor.execute(
            "SELECT trigger_name, event_manipulation, event_object_table, action_timing, action_statement, sql_mode FROM information_schema.triggers WHERE trigger_schema='scc' ORDER BY trigger_name"
        )
        definitions.append(cursor.fetchall())
    return hashlib.sha256(
        json.dumps(definitions, default=str, sort_keys=True).encode()
    ).hexdigest()


def namespace_exists(cursor: Any, company: str) -> bool:
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s",
        (company,),
    )
    return bool(cursor.fetchone()[0])


def deployment_receipt(company: str, env: str, digest: str) -> str:
    return json.dumps(
        {
            "ticket": "KAN-32",
            "environment": env,
            "ddl_sha256": hashlib.sha256(render(company).encode()).hexdigest(),
            "catalog_sha256": digest,
        },
        sort_keys=True,
    )


def ensure_schema(connection: Any, company: str, env: str, check: bool = False) -> None:
    cursor = connection.cursor()
    try:
        if not namespace_exists(cursor, company):
            require(not check, "Source namespace is absent")
            for sql in statements(company):
                cursor.execute(sql)
            receipt = deployment_receipt(company, env, schema_digest(cursor, company))
            if company == "rmrg":
                # PostgreSQL utility syntax does not accept a bound parameter here.
                cursor.execute(
                    "COMMENT ON SCHEMA rmrg IS '" + receipt.replace("'", "''") + "'"
                )
            else:
                cursor.execute("ALTER TABLE scc.customer_master COMMENT=%s", (receipt,))
            connection.commit()
            LOG.info(encode({"event": "schema_deployed", "company": company}).strip())
        else:
            if company == "rmrg":
                cursor.execute(
                    "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname='rmrg'"
                )
            else:
                cursor.execute(
                    "SELECT table_comment FROM information_schema.tables WHERE table_schema='scc' AND table_name='customer_master'"
                )
            row = cursor.fetchone()
            require(
                row is not None and row[0],
                "Existing namespace lacks KAN-32 deployment receipt; refusing adoption",
            )
            require(
                row[0]
                == deployment_receipt(company, env, schema_digest(cursor, company)),
                "Existing schema differs from deployed contract/environment",
            )
            connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.close()


def normalize(company: str, table: str, raw: tuple[Any, ...]) -> dict[str, Any]:
    row = dict(zip((c[0] for c in SCHEMA[company][table]), raw))
    for name, kind, _ in SCHEMA[company][table]:
        if isinstance(row[name], UUID):
            row[name] = str(row[name])
        if kind == "boolean":
            row[name] = bool(row[name])
    return row


def read_tables(
    cursor: Any, company: str, lock: bool = False
) -> dict[str, dict[int, dict[str, Any]]]:
    result = {}
    quote = '"' if company == "rmrg" else "`"
    for table in LOAD_ORDER[company]:
        fields = ", ".join(quote + c[0] + quote for c in SCHEMA[company][table])
        pk = SCHEMA[company][table][0][0]
        cursor.execute(
            f"SELECT {fields} FROM {company}.{quote}{table}{quote} ORDER BY {quote}{pk}{quote}"
            + (" FOR UPDATE" if lock else "")
        )
        rows = [normalize(company, table, r) for r in cursor.fetchall()]
        result[table] = {r[pk]: r for r in rows}
        require(len(rows) == len(result[table]), "Duplicate target identity")
    return result


def advance_counters(cursor: Any, company: str, tables: dict[str, Any]) -> None:
    for table, rows in tables.items():
        pk = SCHEMA[company][table][0][0]
        maximum = max(rows, default=0)
        if company == "rmrg":
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s,%s)", (f"rmrg.{table}", pk)
            )
            sequence = cursor.fetchone()[0]
            # The server supplies a sequence belonging to the approved table, never user SQL.
            cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
            value, called = cursor.fetchone()
            if value < maximum or (value == maximum and not called):
                cursor.execute("SELECT setval(%s,%s,true)", (sequence, maximum))
            cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
            value, called = cursor.fetchone()
            require(
                value + int(called) > maximum, "PostgreSQL sequence did not advance"
            )
        else:
            # InnoDB advances automatically on explicit positive IDs. ALTER TABLE here
            # would implicitly commit the entire load, so validate rather than alter.
            cursor.execute(
                "SELECT auto_increment FROM information_schema.tables WHERE table_schema='scc' AND table_name=%s",
                (table,),
            )
            value = cursor.fetchone()[0]
            require(
                value is not None and value > maximum,
                "MySQL auto-increment did not advance",
            )


def load_company(
    connection: Any, company: str, baseline: Database, check: bool = False
) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        if company == "rmrg":
            cursor.execute("SET LOCAL lock_timeout = '15s'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute(
                "LOCK TABLE "
                + ", ".join("rmrg." + t for t in LOAD_ORDER[company])
                + " IN ACCESS EXCLUSIVE MODE"
            )
        else:
            # Avoid cached information_schema counters when verifying explicit IDs.
            cursor.execute("SET SESSION information_schema_stats_expiry=0")
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cursor.execute("START TRANSACTION")
        actual = read_tables(cursor, company, lock=True)
        empty = not any(actual.values())
        expected = baseline[company]
        if empty and not check:
            for table in LOAD_ORDER[company]:
                columns = [c[0] for c in SCHEMA[company][table]]
                quote = '"' if company == "rmrg" else "`"
                sql = (
                    f"INSERT INTO {company}.{quote}{table}{quote} ("
                    + ", ".join(quote + c + quote for c in columns)
                    + ") VALUES ("
                    + ", ".join("%s" for _ in columns)
                    + ")"
                )
                rows = ordered_rows(company, table, expected[table])
                for offset in range(0, len(rows), 500):
                    cursor.executemany(
                        sql,
                        [
                            tuple(r[c] for c in columns)
                            for r in rows[offset : offset + 500]
                        ],
                    )
                LOG.info(
                    encode(
                        {
                            "event": "table_loaded",
                            "company": company,
                            "table": table,
                            "rows": len(rows),
                        }
                    ).strip()
                )
            actual = read_tables(cursor, company)
        require(
            actual == expected,
            f"Target {company} differs from snapshot; refusing overwrite",
        )
        validate_state({**baseline, company: actual})
        if not check:
            advance_counters(cursor, company, actual)
        else:
            # Check-only never repairs a counter.
            for table, rows in actual.items():
                maximum = max(rows, default=0)
                if company == "rmrg":
                    cursor.execute(
                        "SELECT pg_get_serial_sequence(%s,%s)",
                        (f"rmrg.{table}", SCHEMA[company][table][0][0]),
                    )
                    sequence = cursor.fetchone()[0]
                    cursor.execute(f"SELECT last_value,is_called FROM {sequence}")
                    value, called = cursor.fetchone()
                    require(value + int(called) > maximum, "Sequence is behind seed")
                else:
                    cursor.execute(
                        "SELECT auto_increment FROM information_schema.tables WHERE table_schema='scc' AND table_name=%s",
                        (table,),
                    )
                    require(
                        cursor.fetchone()[0] > maximum, "Auto-increment is behind seed"
                    )
        connection.commit()
        return {
            "event": "database_validated",
            "company": company,
            "action": "checked" if check else "loaded" if empty else "exact_replay",
            "row_counts": {t: len(r) for t, r in actual.items()},
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.close()


def deploy(target: Target, baseline: Database, check: bool = False) -> dict[str, Any]:
    connection = target.connect()
    cursor = connection.cursor()
    try:
        if target.company == "rmrg":
            cursor.execute("SHOW server_version_num")
            require(int(cursor.fetchone()[0]) >= 140000, "PostgreSQL 14+ required")
            cursor.execute("SELECT pg_try_advisory_lock(hashtext('pmdp-kan32-rmrg'))")
            require(
                cursor.fetchone()[0], "Another PostgreSQL deployment holds the lock"
            )
        else:
            cursor.execute("SELECT GET_LOCK('pmdp-kan32-scc', 0)")
            require(
                cursor.fetchone()[0] == 1, "Another MySQL deployment holds the lock"
            )
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
            require(
                match is not None
                and "MariaDB" not in version
                and tuple(map(int, match.groups())) >= (8, 0, 16),
                "MySQL 8.0.16+ with enforced CHECKs required",
            )
            cursor.execute(
                "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"
            )
            cursor.execute("SET SESSION innodb_lock_wait_timeout=15")
        connection.commit()
        ensure_schema(connection, target.company, target.env, check)
        return {
            **load_company(connection, target.company, baseline, check),
            "service": target.service,
        }
    finally:
        cursor.close()
        # Session advisory locks are automatically released even after failures.
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--company", choices=["rmrg", "scc", "all"], default="all")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Offline snapshot validation; no connection",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check existing schema, rows and counters without mutations",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        env = environment()
        manifest, baseline = read_snapshot(args.snapshot, env)
        LOG.info(
            encode(
                {
                    "event": "snapshot_validated",
                    "environment": env,
                    "fingerprint": manifest["fingerprint"],
                }
            ).strip()
        )
        if args.validate_only:
            return
        companies = list(SCHEMA) if args.company == "all" else [args.company]
        # Validate configuration for all requested targets before opening either.
        targets = [Target.from_env(company, env) for company in companies]
        for target in targets:
            LOG.info(encode(deploy(target, baseline, args.check)).strip())
    except Exception as exc:
        # Driver exceptions can contain connection details or rejected row values.
        # Emit only class and a generic instruction; no traceback/credentials/PII.
        LOG.error(
            encode(
                {
                    "event": "deployment_failed",
                    "error_type": type(exc).__name__,
                    "sqlstate": getattr(exc, "sqlstate", None),
                    "mysql_errno": (
                        exc.args[0] if exc.args and type(exc.args[0]) is int else None
                    ),
                    "message": (
                        str(exc)
                        if isinstance(exc, (ValueError, FileNotFoundError))
                        else "Database operation failed; inspect target permissions, connectivity and schema. No rows were overwritten."
                    ),
                }
            ).strip()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
