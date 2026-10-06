"""Simulator business-event v1 contract; separate from database CDC."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .snapshot import encode

# KAN-31: transport domains share topics; event semantics/identities remain v1.
TOPIC_GROUPS = {
    "rmrg": {
        "commerce": (
            "orders-placed",
            "orders-cancelled",
            "payments-resolved",
            "shipments-handed-over",
            "shipments-delivered",
            "returns-requested",
            "returns-received",
        ),
        "inventory": ("inventory-moved",),
        "shopping": ("shopping-viewed", "shopping-added"),
    },
    "scc": {
        "commerce": ("orders-entered", "payments-posted"),
        "activity": ("inventory-observed", "shopping-viewed", "shopping-added"),
    },
}
TYPES = {
    company: {kind for kinds in groups.values() for kind in kinds}
    for company, groups in TOPIC_GROUPS.items()
}
ROUTES = {
    (company, kind): domain
    for company, groups in TOPIC_GROUPS.items()
    for domain, kinds in groups.items()
    for kind in kinds
}


def topic_name(env: str, company: str, kind: str) -> str:
    """Resolve an approved event to one of five environment-qualified topics."""
    if env not in {"dev", "test"} or (company, kind) not in ROUTES:
        raise ValueError("Invalid environment/company/event type")
    return f"pmdp-{env}-{company}-{ROUTES[(company, kind)]}-events-v1"


def expected_topics(env: str) -> tuple[str, ...]:
    if env not in {"dev", "test"}:
        raise ValueError("Kafka simulator topics require dev/test")
    return tuple(
        f"pmdp-{env}-{company}-{domain}-events-v1"
        for company, groups in TOPIC_GROUPS.items()
        for domain in groups
    )


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
        expected = topic_name(env, company, kind)
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
    record = Record(topic_name(env, company, kind), key, encode(event).strip())
    record.validate(env)
    return record
