"""Atomic, checksum-addressed export with bounded transaction memory."""

from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any, TextIO

from .config import Config
from .contracts import Row, SCHEMA, json_default
from .generator import Generator
from .validation import Validator

LOG = logging.getLogger(__name__)
LOAD_ORDER = {
    "rmrg": [
        "customers",
        "customer_addresses",
        "product_categories",
        "products",
        "stores",
        "warehouses",
        "inventory",
        "orders",
        "order_addresses",
        "order_items",
        "shipments",
        "shipment_items",
        "returns",
        "return_items",
        "payments",
        "payment_allocations",
        "stock_movements",
    ],
    "scc": [
        "customer_master",
        "item_master",
        "locations",
        "sales_orders",
        "sales_order_lines",
        "payment_transactions",
        "stock_balance",
    ],
}


def encode(value: Any) -> str:
    return (
        json.dumps(
            value,
            default=json_default,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


class Writer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.handles: dict[str, TextIO] = {}
        self.counts: dict[str, int] = {}
        self.hashes: dict[str, Any] = {}
        self.last_id: dict[str, int] = {}
        for company, tables in SCHEMA.items():
            (root / company).mkdir()
            for table in tables:
                self.open(f"{company}/{table}.jsonl")
        self.open("matching_truth.jsonl")

    def open(self, name: str) -> None:
        self.handles[name] = (self.root / name).open(
            "w", encoding="utf-8", newline="\n"
        )
        self.counts[name] = 0
        self.hashes[name] = hashlib.sha256()

    def write(self, name: str, value: Row) -> None:
        if name != "matching_truth.jsonl":
            company, table = name.removesuffix(".jsonl").split("/")
            ident = value[SCHEMA[company][table][0][0]]
            if ident <= self.last_id.get(name, 0):
                raise ValueError(f"Nonmonotonic/duplicate source identity: {name}")
            self.last_id[name] = ident
        data = encode(value)
        self.handles[name].write(data)
        self.counts[name] += 1
        self.hashes[name].update(data.encode("utf-8"))

    def bundle(self, company: str, bundle: dict[str, list[Row]]) -> None:
        for table, rows in bundle.items():
            for r in rows:
                self.write(f"{company}/{table}.jsonl", r)

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()


def verify(root: Path, manifest: dict[str, Any]) -> None:
    expected = set(manifest["files"]) | {"manifest.json"}
    if {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} != expected:
        raise ValueError("Existing snapshot has missing or unexpected files")
    for name, info in manifest["files"].items():
        hasher = hashlib.sha256()
        count = 0
        with (root / name).open("rb") as stream:
            for line in stream:
                hasher.update(line)
                count += 1
        if hasher.hexdigest() != info["sha256"] or count != info["rows"]:
            raise ValueError(f"Existing snapshot is incomplete or changed: {name}")


def generate(config: Config, output: Path, env: str) -> dict[str, Any]:
    if env not in {"dev", "test"}:
        raise ValueError("Synthetic snapshots require dev/test")
    contract_hash = hashlib.sha256(encode(SCHEMA).encode()).hexdigest()
    # Change this version when workload semantics change, even without schema changes.
    identity = {
        "generator_version": "0.1.0",
        "schema_sha256": contract_hash,
        "config": asdict(config),
        "environment": env,
    }
    fingerprint = hashlib.sha256(encode(identity).encode()).hexdigest()
    output = output.absolute()
    if output.exists():
        try:
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            if manifest["fingerprint"] != fingerprint:
                raise ValueError(
                    "Output already contains a different configuration/version; choose another directory"
                )
            verify(output, manifest)
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Output exists without a valid completed manifest"
            ) from exc
        LOG.info(
            json.dumps(
                {
                    "event": "snapshot_reused",
                    "output": str(output),
                    "fingerprint": fingerprint,
                }
            )
        )
        return manifest
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-", dir=output.parent
    ) as temporary:
        stage = Path(temporary) / "snapshot"
        stage.mkdir()
        generator = Generator(config)
        validator = Validator(generator.masters)
        writer = Writer(stage)
        try:
            for company, masters in generator.masters.items():
                validator.bundle(company, masters)
                writer.bundle(
                    company,
                    {t: rows for t, rows in masters.items() if t != "inventory"},
                )
            opening = {"stock_movements": generator.drain_movements()}
            validator.bundle("rmrg", opening)
            writer.bundle("rmrg", opening)
            for company, stream in [
                ("rmrg", generator.rmrg_orders()),
                ("scc", generator.scc_orders()),
            ]:
                for index, bundle in enumerate(stream, 1):
                    validator.bundle(company, bundle)
                    writer.bundle(company, bundle)
                    if index % 10000 == 0:
                        LOG.info(
                            json.dumps(
                                {
                                    "event": "seed_progress",
                                    "company": company,
                                    "orders": index,
                                }
                            )
                        )
            validator.finish()
            writer.bundle("rmrg", {"inventory": generator.masters["rmrg"]["inventory"]})
            for truth in generator.truth:
                writer.write("matching_truth.jsonl", truth)
        finally:
            writer.close()
        manifest = {
            **identity,
            "fingerprint": fingerprint,
            "snapshot_at": generator.snapshot.isoformat(),
            "source_instances": {
                company: f"{company}-retail-{env}" for company in SCHEMA
            },
            "cdc_tables": {company: list(tables) for company, tables in SCHEMA.items()},
            "load_order": LOAD_ORDER,
            "metrics": dict(generator.metrics),
            "validation": "Column/type/nullability, enforced FKs, per-order reconciliation, complete inventory ledger validated before publication",
            "files": {
                name: {
                    "rows": writer.counts[name],
                    "sha256": writer.hashes[name].hexdigest(),
                }
                for name in writer.handles
            },
        }
        (stage / "manifest.json").write_text(encode(manifest), encoding="utf-8")
        # Rename on the same filesystem publishes only a fully validated snapshot.
        # A concurrent producer's populated output causes rename to fail, not overwrite.
        stage.rename(output)
    LOG.info(
        json.dumps(
            {
                "event": "snapshot_completed",
                "output": str(output),
                "fingerprint": fingerprint,
                "rows": sum(writer.counts.values()),
            }
        )
    )
    return manifest
