"""Rate-controlled continuous source changes; local durable mode is the CLI default."""

import argparse
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
import signal
import threading
import time
from typing import Callable

from .activity import Activity
from .changes import load_seed
from .config import Config, environment
from .persistence import FileStore

LOG = logging.getLogger(__name__)
WEIGHTS = {
    "rmrg": {
        "new_customer": 4,
        "update_customer": 7,
        "new_order": 17,
        "payment": 16,
        "shipment": 28,
        "delivery": 8,
        "inventory": 8,
        "cancel": 2,
        "return": 5,
        "return_progress": 18,
        "draft": 2,
        "delete_draft": 2,
    },
    "scc": {
        "new_customer": 5,
        "update_customer": 10,
        "new_order": 25,
        "payment": 22,
        "inventory": 12,
        "correct_invoice": 8,
        "correct_posting": 5,
        "delete_abandoned": 3,
        "delete_customer": 2,
    },
}


@dataclass(frozen=True)
class RunConfig:
    duration_seconds: float | None = 60.0
    transactions_per_second: float = 2.0
    max_transactions: int | None = None
    rmrg_weight: float = 3.0
    scc_weight: float = 1.0

    def __post_init__(self) -> None:
        for name in ("transactions_per_second", "rmrg_weight", "scc_weight"):
            v = getattr(self, name)
            if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.duration_seconds is not None and (
            type(self.duration_seconds) not in (int, float)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds <= 0
        ):
            raise ValueError(
                "Duration must be finite and positive; use --forever for an unlimited run"
            )
        if self.max_transactions is not None and (
            type(self.max_transactions) is not int or self.max_transactions <= 0
        ):
            raise ValueError("max_transactions must be a positive integer")


def run(
    activity: Activity,
    config: RunConfig,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool] | None = None,
) -> dict[str, int]:
    stop = stop or threading.Event()
    wait = wait or stop.wait
    started = clock()
    next_slot = started
    deadline = (
        started + config.duration_seconds
        if config.duration_seconds is not None
        else math.inf
    )
    metrics = {"committed": 0, "inserts": 0, "updates": 0, "deletes": 0, "skipped": 0}
    while (
        not stop.is_set()
        and clock() < deadline
        and (
            config.max_transactions is None
            or metrics["committed"] < config.max_transactions
        )
    ):
        delay = max(0.0, next_slot - clock())
        if delay and wait(min(delay, max(0.0, deadline - clock()))):
            break
        if stop.is_set() or clock() >= deadline:
            break
        company = activity.rng.choices(
            ["rmrg", "scc"], [config.rmrg_weight, config.scc_weight]
        )[0]
        names = WEIGHTS[company]
        name = activity.rng.choices(list(names), list(names.values()))[0]
        tx = activity.plan(company, name)
        if tx is None:
            metrics["skipped"] += 1
        elif activity.store.commit(tx):
            metrics["committed"] += 1
            for change in tx.changes:
                metrics[change.operation + "s"] += 1
            LOG.info(
                json.dumps(
                    {
                        "event": "source_transaction",
                        "sequence": tx.sequence,
                        "company": company,
                        "activity": name,
                        "changes": len(tx.changes),
                    }
                )
            )
        # Backpressure: slow writes never build a queue or trigger catch-up bursts.
        next_slot = max(next_slot + 1 / config.transactions_per_second, clock())
    LOG.info(
        json.dumps(
            {
                "event": "simulation_stopped",
                **metrics,
                "sequence": activity.store.sequence,
            }
        )
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously mutate approved relational sources in a durable local mode"
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Completed KAN-24 snapshot, required only to initialize new local state",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="Local source state/journal directory, separate from immutable seed output",
    )
    parser.add_argument(
        "--workload-config",
        type=Path,
        help="Optional KAN-24 workload JSON for basket size, guest and SCC quality probabilities",
    )
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument(
        "--duration", type=float, default=60, help="Run seconds (default 60)"
    )
    duration.add_argument(
        "--forever", action="store_true", help="Run until SIGINT/SIGTERM"
    )
    parser.add_argument(
        "--rate", type=float, default=2, help="Maximum transaction attempts per second"
    )
    parser.add_argument(
        "--max-transactions", type=int, help="Optional limit on committed transactions"
    )
    parser.add_argument("--rmrg-weight", type=float, default=3)
    parser.add_argument("--scc-weight", type=float, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    stop = threading.Event()
    prior = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        cfg = RunConfig(
            None if args.forever else args.duration,
            args.rate,
            args.max_transactions,
            args.rmrg_weight,
            args.scc_weight,
        )
        env = environment()
        if args.snapshot and args.state_dir.resolve() == args.snapshot.resolve():
            raise ValueError(
                "State directory must differ from the immutable seed snapshot"
            )
        baseline = (
            load_seed(args.snapshot, env)
            if args.snapshot and not (args.state_dir / "baseline.json").exists()
            else None
        )
        with FileStore(args.state_dir, env, baseline) as store:
            workload = (
                Config.load(args.workload_config) if args.workload_config else Config()
            )
            run(Activity(store, workload), cfg, stop)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        LOG.error(
            json.dumps(
                {
                    "event": "simulation_failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        raise SystemExit(1) from exc
    finally:
        for sig, handler in prior.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
