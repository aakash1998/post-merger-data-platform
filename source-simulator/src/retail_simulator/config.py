"""Workload configuration, independent of deployment credentials and targets."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import json
import os


@dataclass(frozen=True)
class Config:
    seed: int = 24
    start_date: str = "2025-01-01"
    days: int = 365
    rmrg_customers: int = 500
    scc_customers: int = 120
    rmrg_products: int = 100
    scc_products: int = 40
    rmrg_orders: int = 2000
    scc_orders: int = 500
    rmrg_stores: int = 4
    rmrg_warehouses: int = 2
    scc_locations: int = 3
    overlap_fraction: float = 0.45
    guest_fraction: float = 0.18
    return_fraction: float = 0.10
    open_fraction: float = 0.08
    cancel_fraction: float = 0.04
    messy_fraction: float = 0.15
    initial_stock: int = 80
    max_lines: int = 5

    def __post_init__(self) -> None:
        # Reject bool/float counts even though Python bool is an int subclass.
        expected = {
            "seed",
            "days",
            "rmrg_customers",
            "scc_customers",
            "rmrg_products",
            "scc_products",
            "rmrg_orders",
            "scc_orders",
            "rmrg_stores",
            "rmrg_warehouses",
            "scc_locations",
            "initial_stock",
            "max_lines",
        }
        if any(type(getattr(self, key)) is not int for key in expected):
            raise ValueError("Counts and seed must be integers")
        for key in expected - {"seed", "rmrg_orders", "scc_orders"}:
            if getattr(self, key) < 1:
                raise ValueError(f"{key} must be positive")
        if (
            min(
                self.rmrg_customers,
                self.scc_customers,
                self.rmrg_products,
                self.scc_products,
            )
            < 12
        ):
            raise ValueError(
                "At least 12 customers/products per source are needed for matching scenarios"
            )
        if min(self.rmrg_orders, self.scc_orders) < 0 or self.days > 3650:
            raise ValueError(
                "Orders must be nonnegative; date window is limited to 3650 days"
            )
        if self.max_lines > 100 or self.scc_locations > 65535:
            raise ValueError("max_lines <= 100 and scc_locations <= 65535 required")
        for key in (
            "overlap_fraction",
            "guest_fraction",
            "return_fraction",
            "open_fraction",
            "cancel_fraction",
            "messy_fraction",
        ):
            value = getattr(self, key)
            if type(value) not in (float, int) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be in [0, 1]")
        if self.open_fraction + self.cancel_fraction > 1:
            raise ValueError("Open and cancelled fractions must sum to <= 1")
        start = date.fromisoformat(self.start_date)
        if start < date(2024, 1, 1):
            raise ValueError(
                "Seed window must respect the SCC current-source archive boundary (2024-01-01)"
            )
        try:
            start + timedelta(days=self.days + 45)
        except OverflowError as exc:
            raise ValueError(
                "Order window and snapshot must fit valid calendar dates"
            ) from exc

    @classmethod
    def load(cls, path: Path) -> "Config":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def environment() -> str:
    value = os.environ.get("PMDP_ENV")
    if value not in {"dev", "test"}:
        raise ValueError(
            "Set PMDP_ENV explicitly to dev or test for synthetic seed generation"
        )
    return value
