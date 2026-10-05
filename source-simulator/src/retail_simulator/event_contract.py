"""Simulator business-event v1 contract; separate from database CDC."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .snapshot import encode

TYPES = {
    "rmrg": {
        "orders-placed",
        "orders-cancelled",
        "payments-resolved",
        "shipments-handed-over",
        "shipments-delivered",
        "returns-requested",
        "returns-received",
        "inventory-moved",
        "shopping-viewed",
        "shopping-added",
    },
    "scc": {
        "orders-entered",
        "payments-posted",
        "inventory-observed",
        "shopping-viewed",
        "shopping-added",
    },
}


def utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Event timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Record:
    topic: str
    key: str
    value: str

    def validate(self, env: str) -> dict[str, Any]:
        event = json.loads(self.value)
        company = event["company"]
        kind = event["event_type"]
        if env not in {"dev", "test"} or kind not in TYPES.get(company, set()):
            raise ValueError("Invalid environment/company/event type")
        domain, action = kind.split("-", 1)
        expected = f"pmdp-{env}-{company}-{domain}-{action}-v1"
        if self.topic != expected or self.key != event["aggregate_key"]:
            raise ValueError("Topic/key mismatch")
        if event["event_version"] != 1 or event["payload_version"] != 1:
            raise ValueError("Unsupported contract version")
        for name in ("occurred_at", "produced_at"):
            stamp = datetime.fromisoformat(event[name])
            if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError("UTC timestamps required")
        if not isinstance(event["payload"], dict) or not re.fullmatch(
            r"[0-9a-f]{64}", event["event_id"]
        ):
            raise ValueError("Invalid payload/event identity")
        instance = f"{company}-retail-{env}"
        prefix = f"{company}:{instance}:"
        if (
            event["source_instance"] != instance
            or not self.key.startswith(prefix)
            or len(self.key.removeprefix(prefix).split(":")) != 2
            or any(not token for token in self.key.removeprefix(prefix).split(":"))
            or event["environment"] != env
        ):
            raise ValueError("Source-qualified identity/environment required")
        return event

    def as_dict(self) -> dict[str, str]:
        return {"topic": self.topic, "key": self.key, "value": self.value}


def make_record(
    env: str,
    company: str,
    kind: str,
    aggregate: str,
    identity: str,
    occurred: datetime,
    produced: datetime,
    payload: dict[str, Any],
    provenance: dict[str, Any],
) -> Record:
    instance = f"{company}-retail-{env}"
    key = f"{company}:{instance}:{aggregate}"
    event = {
        "event_id": hashlib.sha256(f"{key}:{kind}:v1:{identity}".encode()).hexdigest(),
        "event_type": kind,
        "event_version": 1,
        "payload_version": 1,
        "environment": env,
        "company": company,
        "source_instance": instance,
        "aggregate_key": key,
        "occurred_at": utc(occurred),
        "produced_at": utc(produced),
        "producer": "pmdp-event-simulator/1",
        "payload": payload,
        "provenance": provenance,
    }
    domain, action = kind.split("-", 1)
    record = Record(
        f"pmdp-{env}-{company}-{domain}-{action}-v1", key, encode(event).strip()
    )
    record.validate(env)
    return record
