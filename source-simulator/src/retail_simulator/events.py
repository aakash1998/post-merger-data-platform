"""Generate a saved event plan and deliver it through a rate-controlled producer."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import signal
import threading
import time
from typing import Any, Callable
import uuid

from .changes import load_seed
from .config import environment
from .event_contract import Record
from .event_generation import EventConfig, generate_records
from .event_producer import LocalProducer, Producer, publish
from .snapshot import encode

LOG = logging.getLogger(__name__)


def validate_plan(plan: dict[str, Any], env: str) -> None:
    if plan["environment"] != env or plan["version"] != 1:
        raise ValueError("Event plan environment/version mismatch")
    checksum = hashlib.sha256(encode(plan["deliveries"]).encode()).hexdigest()
    if plan["sha256"] != checksum:
        raise ValueError("Event plan checksum mismatch")
    for n, entry in enumerate(plan["deliveries"], 1):
        if entry["sequence"] != n:
            raise ValueError("Noncontiguous plan")
        Record(**entry["record"]).validate(env)


def prepare(snapshot: Path, env: str, cfg: EventConfig) -> dict[str, Any]:
    data = load_seed(snapshot, env)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    deliveries = generate_records(
        data, env, manifest["fingerprint"], run_id, started, cfg
    )
    plan = {
        "version": 1,
        "environment": env,
        "run_id": run_id,
        "config": asdict(cfg),
        "generated_at": started.isoformat(),
        "snapshot_fingerprint": manifest["fingerprint"],
        "sha256": hashlib.sha256(encode(deliveries).encode()).hexdigest(),
        "deliveries": deliveries,
    }
    validate_plan(plan, env)
    return plan


def run(
    plan: dict[str, Any],
    producer: Producer,
    env: str,
    rate: float = 5.0,
    duration: float | None = 60.0,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool] | None = None,
) -> dict[str, int]:
    validate_plan(plan, env)
    if isinstance(producer, LocalProducer) and len(
        list(producer.root.glob("*.json"))
    ) > len(plan["deliveries"]):
        raise ValueError("Local history extends beyond the saved plan")
    if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("Rate must be finite and positive")
    if duration is not None and (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("Duration must be finite and positive")
    stop = stop or threading.Event()
    wait = wait or stop.wait
    next_slot = clock()
    deadline = next_slot + duration if duration is not None else math.inf
    counts = {"acknowledged": 0, "replayed": 0}
    try:
        for delivery in plan["deliveries"]:
            if stop.is_set() or clock() >= deadline:
                break
            # Verified local prefix replays do not consume the rate/duration budget.
            record = Record(**delivery["record"])
            seq = delivery["sequence"]
            if (
                isinstance(producer, LocalProducer)
                and (producer.root / f"{seq:012d}.json").exists()
            ):
                producer.send(seq, record)
                counts["replayed"] += 1
                continue
            delay = min(max(0, next_slot - clock()), max(0, deadline - clock()))
            if delay and wait(delay):
                break
            if stop.is_set() or clock() >= deadline:
                break
            sent = producer.send(seq, record)
            counts["acknowledged" if sent else "replayed"] += 1
            LOG.info(
                json.dumps(
                    {
                        "event": "business_event_acknowledged",
                        "sequence": seq,
                        "topic": record.topic,
                        "edge_case": delivery["edge_case"],
                    }
                )
            )
            next_slot = max(next_slot + 1 / rate, clock())
    finally:
        producer.flush()
    LOG.info(json.dumps({"event": "event_delivery_stopped", **counts}))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate/replay versioned retail business events locally"
    )
    parser.add_argument(
        "--snapshot", type=Path, help="KAN-24 snapshot; required for a new plan"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Dedicated event plan/delivery directory",
    )
    parser.add_argument(
        "--config", type=Path, help="EventConfig JSON; used only for new plans"
    )
    parser.add_argument("--rate", type=float, default=5)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument(
        "--until-complete",
        action="store_true",
        help="Stop after the finite plan or a signal",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        env = environment()
        if args.snapshot and (
            args.output.resolve() == args.snapshot.resolve()
            or args.output.resolve().is_relative_to(args.snapshot.resolve())
        ):
            raise ValueError("Event output must be outside immutable seed snapshot")
        with LocalProducer(args.output / "deliveries", env) as producer:
            path = args.output / "plan.json"
            if path.exists():
                if args.snapshot or args.config:
                    raise ValueError(
                        "Existing plan: omit snapshot/config to resume; use another output for new generation"
                    )
                plan = json.loads(path.read_text(encoding="utf-8"))
            else:
                if any(producer.root.glob("*.json")):
                    raise ValueError(
                        "Existing deliveries require their original saved plan"
                    )
                if args.snapshot is None:
                    raise ValueError("New event plan requires --snapshot")
                cfg = (
                    EventConfig(**json.loads(args.config.read_text(encoding="utf-8")))
                    if args.config
                    else EventConfig()
                )
                plan = prepare(args.snapshot, env, cfg)
                publish(path, plan)
            run(
                plan,
                producer,
                env,
                args.rate,
                None if args.until_complete else args.duration,
                stop,
            )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        LOG.error(
            json.dumps(
                {
                    "event": "event_generator_failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        raise SystemExit(1) from exc
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
