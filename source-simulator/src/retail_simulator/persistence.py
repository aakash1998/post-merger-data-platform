"""Atomic local source state and injectable SQL transaction persistence."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Protocol

from .changes import (
    Change,
    Database,
    Transaction,
    apply_changes,
    decode_row,
    validate_state,
)
from .contracts import SCHEMA, validate_row
from .snapshot import LOAD_ORDER, encode
from .validation import require


class Persistence(Protocol):
    data: Database
    sequence: int
    highwater: dict[str, dict[str, int]]

    def commit(self, transaction: Transaction) -> bool:
        """Atomically apply one source transaction; return false for an exact replay."""
        ...


def watermarks(data: Database) -> dict[str, dict[str, int]]:
    return {
        co: {table: max(rows, default=0) for table, rows in tables.items()}
        for co, tables in data.items()
    }


class MemoryStore:
    def __init__(self, data: Database) -> None:
        validate_state(data)
        self.data = data
        self.sequence = 0
        self.highwater = watermarks(data)
        self.last_transaction: Transaction | None = None

    def prepare(self, tx: Transaction) -> Database | None:
        require(
            tx.company in SCHEMA and set(tx.highwater) == set(SCHEMA[tx.company]),
            "Transaction company/highwater mismatch",
        )
        if tx.sequence == self.sequence and tx == self.last_transaction:
            return None
        require(
            tx.sequence == self.sequence + 1,
            "Unexpected transaction sequence; replan from committed state",
        )
        for table, ident in self.highwater[tx.company].items():
            require(
                tx.highwater[table] >= ident,
                "Identity highwater cannot regress after deletion",
            )
        for change in tx.changes:
            if change.before is None:
                require(
                    change.pk > self.highwater[tx.company][change.table]
                    and change.pk <= tx.highwater[change.table],
                    "New source identity must not be reused",
                )
        return apply_changes(self.data, tx)

    def publish(self, tx: Transaction, candidate: Database) -> None:
        self.data = candidate
        self.highwater[tx.company] = dict(tx.highwater)
        self.sequence = tx.sequence
        self.last_transaction = tx

    def commit(self, tx: Transaction) -> bool:
        candidate = self.prepare(tx)
        if candidate is None:
            return False
        self.publish(tx, candidate)
        return True


def atomic_write(path: Path, value: Any) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class FileStore(MemoryStore):
    """One durable journal file per transaction; a lifetime lock excludes other writers."""

    def __init__(self, root: Path, env: str, baseline: Database | None = None) -> None:
        import fcntl

        require(env in {"dev", "test"}, "Local simulator requires dev/test")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.lock = (root / ".writer.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._open(env, baseline)
        except BaseException:
            self.lock.close()
            raise

    def _open(self, env: str, baseline: Database | None) -> None:
        schema_hash = hashlib.sha256(encode(SCHEMA).encode()).hexdigest()
        baseline_path = self.root / "baseline.json"
        journal = self.root / "transactions"
        journal.mkdir(exist_ok=True)
        if not baseline_path.exists():
            require(baseline is not None, "New state directory requires --snapshot")
            require(
                not any(journal.iterdir()),
                "Cannot initialize over orphaned transactions",
            )
            validate_state(baseline)
            atomic_write(
                baseline_path,
                {
                    "format_version": 1,
                    "environment": env,
                    "schema_sha256": schema_hash,
                    "sources": {
                        co: {
                            table: list(rows.values()) for table, rows in tables.items()
                        }
                        for co, tables in baseline.items()
                    },
                },
            )
        value = json.loads(baseline_path.read_text(encoding="utf-8"))
        require(
            value["format_version"] == 1
            and value["environment"] == env
            and value["schema_sha256"] == schema_hash,
            "Local state environment/schema/version mismatch",
        )
        data: Database = {}
        for co, tables in value["sources"].items():
            data[co] = {}
            for table, rows in tables.items():
                pk = SCHEMA[co][table][0][0]
                typed = [decode_row(co, table, r) for r in rows]
                data[co][table] = {r[pk]: r for r in typed}
                require(len(typed) == len(data[co][table]), "Duplicate baseline PK")
        super().__init__(data)
        for path in sorted(journal.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            company = raw["company"]
            changes = tuple(
                Change(
                    c["table"],
                    c["pk"],
                    (
                        decode_row(company, c["table"], c["before"])
                        if c["before"] is not None
                        else None
                    ),
                    (
                        decode_row(company, c["table"], c["after"])
                        if c["after"] is not None
                        else None
                    ),
                )
                for c in raw["changes"]
            )
            tx = Transaction(
                raw["sequence"], company, raw["activity"], changes, raw["highwater"]
            )
            require(
                path.name == f"{tx.sequence:012d}.json",
                "Journal filename/sequence mismatch",
            )
            MemoryStore.commit(self, tx)

    def commit(self, tx: Transaction) -> bool:
        candidate = self.prepare(tx)
        if candidate is None:
            return False
        path = self.root / "transactions" / f"{tx.sequence:012d}.json"
        require(not path.exists(), "Journal sequence already occupied")
        atomic_write(path, asdict(tx))
        self.publish(tx, candidate)
        return True

    def close(self) -> None:
        self.lock.close()

    def __enter__(self) -> "FileStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class Cursor(Protocol):
    rowcount: int

    def execute(self, query: str, parameters: tuple[Any, ...]) -> Any: ...
    def fetchone(self) -> Any: ...
    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class DBAPIWriter:
    """Parameterized PG/MySQL writes to already-provisioned, exclusively controlled sources.

    Connection configuration/drivers and authoritative audit readback belong to deployment.
    This adapter is not a distributed local-journal + database commit coordinator.
    """

    def __init__(self, company: str, connection: Connection, namespace: str) -> None:
        import re

        require(
            company in SCHEMA and bool(re.fullmatch(r"[a-z][a-z0-9_]*", namespace)),
            "Invalid source namespace",
        )
        self.company, self.connection, self.namespace = company, connection, namespace

    def quote(self, value: str) -> str:
        mark = '"' if self.company == "rmrg" else "`"
        return f"{mark}{value}{mark}"

    def commit(self, tx: Transaction) -> None:
        require(tx.company == self.company, "A SQL transaction must target one source")
        for change in tx.changes:
            require(change.table in SCHEMA[self.company], "Unknown source table")
            if change.after is not None:
                validate_row(self.company, change.table, change.after)
                require(
                    change.after[SCHEMA[self.company][change.table][0][0]] == change.pk,
                    "Source identity cannot change",
                )
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "BEGIN" if self.company == "rmrg" else "START TRANSACTION", ()
            )
            # Verify before-images under row locks before changing anything.
            for c in sorted(tx.changes, key=lambda c: (c.table, c.pk)):
                require(c.table in SCHEMA[self.company], "Unknown source table")
                columns = [x[0] for x in SCHEMA[self.company][c.table]]
                table = f"{self.quote(self.namespace)}.{self.quote(c.table)}"
                cursor.execute(
                    f'SELECT {", ".join(map(self.quote,columns))} FROM {table} WHERE {self.quote(columns[0])} = %s FOR UPDATE',
                    (c.pk,),
                )
                actual = cursor.fetchone()
                actual_row = dict(zip(columns, actual)) if actual is not None else None
                require(
                    actual_row == c.before,
                    "Source changed since planning; reload before retry",
                )
            rank = {t: i for i, t in enumerate(LOAD_ORDER[self.company])}
            ordered = sorted(
                tx.changes,
                key=lambda c: (
                    0 if c.after is None else 1,
                    -rank[c.table] if c.after is None else rank[c.table],
                    c.pk,
                ),
            )
            for c in ordered:
                columns = [x[0] for x in SCHEMA[self.company][c.table]]
                pk = columns[0]
                table = f"{self.quote(self.namespace)}.{self.quote(c.table)}"
                if c.after is None:
                    cursor.execute(
                        f"DELETE FROM {table} WHERE {self.quote(pk)} = %s", (c.pk,)
                    )
                elif c.before is None:
                    validate_row(self.company, c.table, c.after)
                    # Controlled explicit IDs only; PG timestamps/versions are database-owned.
                    fields = [
                        name
                        for name in columns
                        if self.company != "rmrg"
                        or name not in {"created_at", "updated_at", "row_version"}
                    ]
                    cursor.execute(
                        f'INSERT INTO {table} ({", ".join(map(self.quote,fields))}) VALUES ({", ".join("%s" for _ in fields)})',
                        tuple(c.after[name] for name in fields),
                    )
                else:
                    fields = [
                        name
                        for name in columns[1:]
                        if c.before[name] != c.after[name]
                        and (
                            self.company != "rmrg"
                            or name
                            not in {
                                "created_at",
                                "created_by",
                                "updated_at",
                                "row_version",
                            }
                        )
                    ]
                    require(
                        bool(fields),
                        "SQL update must have a meaningful writable change",
                    )
                    cursor.execute(
                        f'UPDATE {table} SET {", ".join(self.quote(name)+" = %s" for name in fields)} WHERE {self.quote(pk)} = %s',
                        tuple(c.after[name] for name in fields) + (c.pk,),
                    )
                require(cursor.rowcount == 1, "Unexpected source write rowcount")
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        finally:
            cursor.close()
