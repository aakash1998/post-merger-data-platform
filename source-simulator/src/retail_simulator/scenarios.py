"""Deterministic orchestration of the existing seed, activity and event generators."""

import argparse
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import random
import tempfile
from typing import Any

from .activity import Activity
from .changes import load_seed
from .config import Config, environment
from .event_contract import Record
from .event_generation import EventConfig
from .event_producer import LocalProducer, publish
from .events import create_plan, validate_plan
from .persistence import FileStore
from .snapshot import encode, generate

LOG = logging.getLogger(__name__)
VERSION = 1
RECIPES = {
    "normal": [
        ("rmrg", "new_customer"),
        ("scc", "new_customer"),
        ("rmrg", "fulfil"),
        ("scc", "new_order"),
        ("scc", "payment"),
        ("rmrg", "inventory"),
        ("scc", "inventory"),
    ],
    "duplicate_replay": [
        ("rmrg", "fulfil"),
        ("rmrg", "replay_last"),
        ("scc", "new_order"),
        ("scc", "payment"),
        ("scc", "replay_last"),
    ],
    "late_out_of_order": [
        ("rmrg", "fulfil"),
        ("rmrg", "return_refund"),
        ("scc", "new_order"),
        ("scc", "payment"),
    ],
    "customer_updates": [
        ("rmrg", "new_customer"),
        ("scc", "new_customer"),
        ("rmrg", "update_customer"),
        ("scc", "update_customer"),
    ],
    "cancellations": [("rmrg", "new_order"), ("rmrg", "cancel")],
    "returns_refunds": [("rmrg", "fulfil"), ("rmrg", "return_refund")],
    "inventory_changes": [("rmrg", "inventory"), ("scc", "inventory")],
    "scc_messy": [
        ("scc", "new_customer"),
        ("scc", "update_customer"),
        ("scc", "new_order"),
        ("scc", "correct_invoice"),
        ("scc", "payment"),
        ("scc", "correct_posting"),
        ("scc", "inventory"),
        ("scc", "new_order"),
        ("scc", "delete_abandoned"),
    ],
}
SEED_DEFAULTS = {
    "start_date": "2025-01-01",
    "days": 30,
    "rmrg_customers": 24,
    "scc_customers": 16,
    "rmrg_products": 16,
    "scc_products": 12,
    "rmrg_orders": 0,
    "scc_orders": 0,
    "rmrg_stores": 2,
    "rmrg_warehouses": 1,
    "scc_locations": 2,
    "max_lines": 3,
}


@dataclass(frozen=True)
class ScenarioConfig:
    name: str = "normal"
    seed: int = 27
    clock_start: str = "2025-04-01T12:00:00+00:00"
    step_seconds: int = 60
    rounds: int = 1
    event_count: int = 200
    seed_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in RECIPES:
            raise ValueError(f"Unknown scenario: {self.name}")
        for name in ("seed", "step_seconds", "rounds", "event_count"):
            value = getattr(self, name)
            if type(value) is not int or (name != "seed" and value < 1):
                raise ValueError(
                    f"{name} must be an integer; counts/step must be positive"
                )
        instant = datetime.fromisoformat(self.clock_start)
        if instant.utcoffset() is None or instant.utcoffset().total_seconds() != 0:
            raise ValueError("Scenario clock_start must include a UTC offset of zero")
        profile = self.profile()
        if profile.rmrg_orders or profile.scc_orders:
            raise ValueError(
                "Scenario recipes require a masters-only seed (both order counts zero)"
            )
        latest = datetime.fromisoformat(profile.start_date).replace(
            tzinfo=timezone.utc
        ) + timedelta(days=profile.days + 45)
        if instant < latest:
            raise ValueError(
                "Scenario clock must be on/after the seed snapshot boundary"
            )

    def profile(self) -> Config:
        if not isinstance(self.seed_config, dict) or "seed" in self.seed_config:
            raise ValueError(
                "seed_config must be an object; select seed at the scenario level"
            )
        profile = Config(**{**SEED_DEFAULTS, **self.seed_config, "seed": self.seed})
        # Named legacy-quality coverage is explicit, never a probabilistic promise.
        return (
            replace(profile, messy_fraction=1.0)
            if self.name == "scc_messy"
            else profile
        )

    def event_profile(self) -> EventConfig:
        edges = {
            "duplicate_fraction": 0.0,
            "late_fraction": 0.0,
            "reorder_fraction": 0.0,
        }
        if self.name == "duplicate_replay":
            edges["duplicate_fraction"] = 1.0
        elif self.name == "late_out_of_order":
            edges.update(late_fraction=0.5, reorder_fraction=0.5)
        return EventConfig(
            events=self.event_count,
            seed=self.seed,
            late_slots=15,
            reorder_slots=4,
            **edges,
        )


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def implementation_digest() -> str:
    root = Path(__file__).parent
    return digest(
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.iterdir())
            if p.suffix in {".py", ".json"}
        }
    )


def identity(cfg: ScenarioConfig, env: str) -> dict[str, Any]:
    if env not in {"dev", "test"}:
        raise ValueError("Scenarios require explicit dev/test")
    return {
        "scenario_version": VERSION,
        "environment": env,
        "config": asdict(cfg),
        "resolved_seed_config": asdict(cfg.profile()),
        "event_config": asdict(cfg.event_profile()),
        "implementation_sha256": implementation_digest(),
        "python_version": platform.python_version(),
    }


class Script:
    def __init__(
        self, store: FileStore, cfg: ScenarioConfig, fail_after: int | None = None
    ) -> None:
        self.store, self.cfg = store, cfg
        self.activity = Activity(store, cfg.profile(), random.Random(cfg.seed))
        self.now = datetime.fromisoformat(cfg.clock_start)
        self.trace: list[dict[str, Any]] = []
        self.fail_after = fail_after

    def checkpoint(self) -> None:
        if self.fail_after == len(self.trace):
            raise OSError(f"Injected scenario failure after {self.fail_after} commands")

    def command(self, company: str, name: str) -> None:
        self.now += timedelta(seconds=self.cfg.step_seconds)
        if name == "replay_last":
            tx = self.store.last_transaction
            if tx is None or tx.company != company or self.store.commit(tx):
                raise ValueError(
                    "Expected an exact last-transaction replay without a second effect"
                )
            self.trace.append(
                {
                    "company": company,
                    "command": name,
                    "sequence": tx.sequence,
                    "clock": self.now.isoformat(),
                    "result": "replayed",
                }
            )
            self.checkpoint()
            return
        tx = self.activity.plan(company, name, self.now)
        if tx is None:
            raise ValueError(
                f"Scenario command has no eligible/changed entity: {company}.{name}"
            )
        self.store.commit(tx)
        self.trace.append(
            {
                "company": company,
                "command": name,
                "sequence": tx.sequence,
                "clock": self.now.isoformat(),
                "result": "committed",
            }
        )
        self.checkpoint()

    def fulfil(self) -> None:
        self.command("rmrg", "new_order")
        self.command("rmrg", "payment")
        # KAN-25 chooses among eligible consignments; deterministic PRNG controls ties.
        limit = 3 * len(self.store.data["rmrg"]["shipments"]) + 1
        for _ in range(limit):
            states = {
                s["shipment_status"]
                for s in self.store.data["rmrg"]["shipments"].values()
            }
            if states & {"allocated", "ready"}:
                self.command("rmrg", "shipment")
            elif "handed_over" in states:
                self.command("rmrg", "delivery")
            else:
                return
        raise ValueError("Scenario fulfillment did not converge")

    def execute(self) -> None:
        for _ in range(self.cfg.rounds):
            for company, name in RECIPES[self.cfg.name]:
                if name == "fulfil":
                    self.fulfil()
                elif name == "return_refund":
                    self.command(company, "return")
                    for _ in range(4):
                        self.command(company, "return_progress")
                else:
                    self.command(company, name)


def inventory(root: Path) -> dict[str, dict[str, Any]]:
    return {
        str(p.relative_to(root)): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
        for p in sorted(root.rglob("*"))
        if p.is_file() and p != root / "scenario.json"
    }


def verify_bundle(root: Path, expected: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((root / "scenario.json").read_text(encoding="utf-8"))
    if manifest["manifest_sha256"] != digest(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    ):
        raise ValueError("Scenario manifest checksum mismatch")
    if manifest["identity"] != expected or manifest["fingerprint"] != digest(expected):
        raise ValueError(
            "Scenario configuration/implementation differs; choose a new output"
        )
    if manifest["files"] != inventory(root):
        raise ValueError("Scenario artifacts are missing, unexpected or corrupt")
    return manifest


def build(
    cfg: ScenarioConfig, output: Path, env: str, fail_after: int | None = None
) -> dict[str, Any]:
    if fail_after is not None and (type(fail_after) is not int or fail_after < 1):
        raise ValueError("fail_after must be a positive integer")
    resolved = identity(cfg, env)
    fingerprint = digest(resolved)
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / f".{output.name}.scenario.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Another scenario builder owns this output") from None
        if output.exists():
            return verify_bundle(output, resolved)
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}-", dir=output.parent
        ) as temporary:
            stage = Path(temporary) / "bundle"
            stage.mkdir()
            seed = generate(cfg.profile(), stage / "seed", env)
            baseline = load_seed(stage / "seed", env)
            with FileStore(stage / "database", env, baseline) as store:
                script = Script(store, cfg, fail_after)
                script.execute()
                final = {
                    co: {table: list(rows.values()) for table, rows in tables.items()}
                    for co, tables in store.data.items()
                }
                publish(stage / "final-state.json", final)
                publish(stage / "commands.json", script.trace)
                # Events include the completed scenario's milestones, not just the seed.
                plan = create_plan(
                    store.data,
                    env,
                    cfg.event_profile(),
                    digest(final),
                    fingerprint,
                    script.now + timedelta(seconds=cfg.step_seconds),
                )
                deliveries = plan["deliveries"]
                publish(stage / "events" / "plan.json", plan)
                with LocalProducer(stage / "events" / "deliveries", env) as producer:
                    for delivery in deliveries:
                        producer.send(
                            delivery["sequence"], Record(**delivery["record"])
                        )
                summary = {
                    "transactions": store.sequence,
                    "commands": len(script.trace),
                    "transaction_replays": sum(
                        c["result"] == "replayed" for c in script.trace
                    ),
                    "deliveries": len(deliveries),
                    "final_state_sha256": digest(final),
                }
            manifest = {
                "identity": resolved,
                "fingerprint": fingerprint,
                "seed_fingerprint": seed["fingerprint"],
                "summary": summary,
                "files": inventory(stage),
            }
            manifest["manifest_sha256"] = digest(manifest)
            publish(stage / "scenario.json", manifest)
            stage.rename(output)
            descriptor = os.open(output.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    LOG.info(
        json.dumps(
            {
                "event": "scenario_completed",
                "name": cfg.name,
                "fingerprint": fingerprint,
                **summary,
            }
        )
    )
    return manifest


def replay(cfg: ScenarioConfig, output: Path, env: str) -> dict[str, int]:
    """Validate source recovery and acknowledged event replay, without new effects."""
    manifest = verify_bundle(output, identity(cfg, env))
    with FileStore(output / "database", env) as store:
        recovered = {
            co: {table: list(rows.values()) for table, rows in tables.items()}
            for co, tables in store.data.items()
        }
        if digest(recovered) != manifest["summary"]["final_state_sha256"]:
            raise ValueError("Recovered source state differs from scenario final state")
        if store.last_transaction is None or store.commit(store.last_transaction):
            raise ValueError("Recovered source transaction replay changed state")
        transactions = store.sequence
    plan = json.loads((output / "events" / "plan.json").read_text(encoding="utf-8"))
    validate_plan(plan, env)
    with LocalProducer(output / "events" / "deliveries", env) as producer:
        for delivery in plan["deliveries"]:
            if producer.send(delivery["sequence"], Record(**delivery["record"])):
                raise ValueError("Replay unexpectedly created a delivery")
    verify_bundle(output, identity(cfg, env))
    return {
        "recovered_transactions": transactions,
        "replayed_deliveries": len(plan["deliveries"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run reproducible local retail scenarios"
    )
    parser.add_argument(
        "--list", action="store_true", help="List built-in scenario names"
    )
    parser.add_argument(
        "--scenario", choices=sorted(RECIPES), help="Overrides config name"
    )
    parser.add_argument("--seed", type=int, help="Overrides config seed")
    parser.add_argument("--config", type=Path, help="ScenarioConfig JSON")
    parser.add_argument(
        "--output", type=Path, help="Complete scenario bundle directory"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Recover/replay an existing bundle with no new effects",
    )
    parser.add_argument(
        "--fail-after-commands",
        type=int,
        help="Inject a failure after N script commands during a new build",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.list:
        print("\n".join(sorted(RECIPES)))
        return
    if args.output is None:
        parser.error("--output is required except with --list")
    try:
        raw = (
            json.loads(args.config.read_text(encoding="utf-8"))
            if args.config
            else (
                json.loads((args.output / "scenario.json").read_text(encoding="utf-8"))[
                    "identity"
                ]["config"]
                if args.replay
                else {}
            )
        )
        if args.scenario is not None:
            raw["name"] = args.scenario
        if args.seed is not None:
            raw["seed"] = args.seed
        cfg = ScenarioConfig(**raw)
        env = environment()
        if args.replay and args.fail_after_commands is not None:
            raise ValueError("Failure injection applies only to new builds, not replay")
        result = (
            replay(cfg, args.output, env)
            if args.replay
            else build(cfg, args.output, env, args.fail_after_commands)
        )
        LOG.info(
            json.dumps(
                {
                    "event": (
                        "scenario_replayed" if args.replay else "scenario_verified"
                    ),
                    "name": cfg.name,
                    **(result if args.replay else result["summary"]),
                }
            )
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        LOG.error(
            json.dumps(
                {
                    "event": "scenario_failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
