"""CLI entry point; logs contain metadata, never row contents."""

import argparse
import json
import logging
from pathlib import Path

from .config import Config, environment
from .snapshot import generate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate approved RMRG/SCC relational seed snapshots"
    )
    parser.add_argument(
        "--config", type=Path, help="JSON workload profile (defaults when omitted)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New snapshot directory; identical completed runs are verified/reused",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        config = Config.load(args.config) if args.config else Config()
        generate(config, args.output, environment())
    except (OSError, ValueError, TypeError) as exc:
        logging.error(json.dumps({"event": "seed_failed", "error": str(exc)}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
