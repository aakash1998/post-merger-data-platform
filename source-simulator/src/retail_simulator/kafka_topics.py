"""KAN-31: explicit Aiven topic reconciliation and verified Kafka round-trip.

Control-plane HTTPS creates/configures topics; data-plane SASL_SSL/SCRAM-SHA-256
reads effective broker settings and verifies all five approved transport domains.
No topic deletions, implicit creation, database writes or ingestion configuration.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from .changes import load_seed
from .config import environment
from .event_generation import EventConfig, facts, generate_records
from .event_contract import Record, expected_topics, make_record
from .event_producer import publish
from .snapshot import encode
from .validation import require

LOG = logging.getLogger(__name__)
TARGET_RETENTION_MS = 259200000


@dataclass(frozen=True)
class TopicPolicy:
    env: str
    service: str
    topics: tuple[str, ...]
    partitions: int
    retention_ms: int
    replication: int

    @classmethod
    def load(cls, path: Path, env: str) -> TopicPolicy:
        raw = json.loads(path.read_text(encoding="utf-8"))
        value = raw["kafka"]
        require(
            env in {"dev", "test"} and raw["environment"] == env,
            "Topic policy environment mismatch",
        )
        require(
            value["service"] == f"pmdp-{env}-enterprise-kafka",
            "Topic policy service mismatch",
        )
        topics = tuple(value["topics"])
        require(
            len(topics) == 5 and set(topics) == set(expected_topics(env)),
            "Policy must contain exactly the five approved topics",
        )
        require(
            type(value["partitions"]) is int and value["partitions"] == 1,
            "Exactly one partition per topic is required",
        )
        require(
            value["cleanup_policy"] == "delete"
            and value["allow_auto_create_topics"] is False,
            "Delete policy and disabled automatic creation required",
        )
        require(
            type(value["target_retention_ms"]) is int
            and value["target_retention_ms"] == TARGET_RETENTION_MS,
            "Three-day target retention required",
        )
        require(
            type(value["replication_factor"]) is int
            and 1 <= value["replication_factor"] <= 3,
            "Replication factor must be an integer from one to three",
        )
        return cls(
            env,
            value["service"],
            topics,
            value["partitions"],
            value["target_retention_ms"],
            value["replication_factor"],
        )


@dataclass(frozen=True, repr=False)
class KafkaSettings:
    env: str
    service: str
    project: str
    api_token: str
    bootstrap: str
    username: str
    password: str
    ca: str

    @classmethod
    def from_env(cls, policy: TopicPolicy) -> KafkaSettings:
        keys = (
            "PMDP_KAFKA_SERVICE",
            "PMDP_AIVEN_PROJECT",
            "PMDP_AIVEN_TOKEN",
            "PMDP_KAFKA_BOOTSTRAP_SERVERS",
            "PMDP_KAFKA_SASL_USERNAME",
            "PMDP_KAFKA_SASL_PASSWORD",
            "PMDP_KAFKA_SSL_CA",
        )
        aliases = {
            "PMDP_KAFKA_SASL_USERNAME": "PMDP_KAFKA_USERNAME",
            "PMDP_KAFKA_SASL_PASSWORD": "PMDP_KAFKA_PASSWORD",
            "PMDP_KAFKA_SSL_CA": "PMDP_KAFKA_CA",
        }
        values = []
        for key in keys:
            value = os.environ.get(key)
            alias = os.environ.get(aliases.get(key, ""))
            require(
                not (value and alias and value != alias),
                "Conflicting environment variables: " + key,
            )
            value = value or alias
            require(bool(value), "Missing environment variable: " + key)
            values.append(value)
        service, project, token, bootstrap, username, password, ca = values
        require(service == policy.service, "Connection service/environment mismatch")
        for address in bootstrap.split(","):
            match = re.fullmatch(r"([a-zA-Z0-9.-]+):(\d+)", address.strip())
            require(
                match is not None and 1 <= int(match[2]) <= 65535,
                "Bootstrap must contain host:port endpoints, without credentials/URIs",
            )
        ca_path = Path(ca)
        require(
            ca_path.is_absolute() and ca_path.is_file(),
            "Kafka CA must be an existing absolute PEM path",
        )
        return cls(
            policy.env,
            service,
            project,
            token,
            bootstrap,
            username,
            password,
            str(ca_path),
        )

    def client_config(self) -> dict[str, Any]:
        return {
            "bootstrap.servers": self.bootstrap,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "SCRAM-SHA-256",
            "sasl.username": self.username,
            "sasl.password": self.password,
            "ssl.ca.location": self.ca,
            "enable.ssl.certificate.verification": True,
            "ssl.endpoint.identification.algorithm": "https",
            "socket.timeout.ms": 30000,
            "log_level": 0,
        }


class ApiError(RuntimeError):
    def __init__(self, status: int, retention_restricted: bool = False) -> None:
        super().__init__(f"Aiven API request failed with HTTP {status}")
        self.status = status
        self.retention_restricted = retention_restricted


class AivenAPI:
    def __init__(self, settings: KafkaSettings) -> None:
        self.token = settings.api_token
        self.path = (
            "/v1/project/"
            + quote(settings.project, safe="")
            + "/service/"
            + quote(settings.service, safe="")
        )

    def request(
        self, method: str, suffix: str = "", body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request = Request(
            "https://api.aiven.io" + self.path + suffix,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "aivenv1 " + self.token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = json.load(response)
                require(not data.get("error"), "Aiven API returned an error")
                return data
        except HTTPError as exc:
            # Retain only a classification, never raw API bodies/service credentials.
            text = exc.read().decode("utf-8", errors="replace").lower()
            restricted = "retention" in text and any(
                word in text
                for word in ("fixed", "not supported", "not allowed", "cannot", "free")
            )
            raise ApiError(exc.code, restricted) from None

    def service(self) -> dict[str, Any]:
        return self.request("GET")["service"]

    def topics(self) -> list[dict[str, Any]]:
        return self.request("GET", "/topic")["topics"]

    def create(
        self, name: str, policy: TopicPolicy, platform_retention: bool = False
    ) -> None:
        body: dict[str, Any] = {
            "topic_name": name,
            "partitions": policy.partitions,
            "replication": policy.replication,
            "cleanup_policy": "delete",
            "min_insync_replicas": 1,
        }
        if not platform_retention:
            body.update(
                retention_hours=72, config={"retention_ms": policy.retention_ms}
            )
        self.request("POST", "/topic", body)

    def configure(self, name: str, retention_ms: int | None) -> None:
        body: dict[str, Any] = {"cleanup_policy": "delete"}
        if retention_ms is not None:
            body["config"] = {"retention_ms": retention_ms}
        self.request("PUT", "/topic/" + quote(name, safe=""), body)


def verify_service(service: dict[str, Any], settings: KafkaSettings) -> bool:
    require(
        service["service_name"] == settings.service
        and service["service_type"] == "kafka",
        "Aiven service identity/type mismatch",
    )
    require(service["state"] == "RUNNING", "Aiven Kafka service is not RUNNING")
    components = service.get("components", [])
    sasl_endpoints = {
        f"{c['host']}:{c['port']}"
        for c in components
        if c.get("component") == "kafka"
        and c.get("kafka_authentication_method") == "sasl"
    }
    require(
        bool(sasl_endpoints)
        and set(x.strip() for x in settings.bootstrap.split(",")) <= sasl_endpoints,
        "Bootstrap endpoint does not match the selected Aiven SASL service",
    )
    config = service.get("user_config", {})
    require(
        config.get("kafka_authentication_methods", {}).get("sasl", False) is True,
        "Aiven SASL authentication must be enabled",
    )
    require(
        config.get("kafka_sasl_mechanisms", {}).get("scram_sha_256", True) is True,
        "Aiven SCRAM-SHA-256 must be enabled",
    )
    return "free" in service.get("plan", "").lower()


class TopicNotReady(ValueError):
    """Only asynchronous missing/leader metadata is eligible for bounded retry."""


def check_topic_names(names: set[str], policy: TopicPolicy, complete: bool) -> None:
    unexpected = names - set(policy.topics)
    require(
        not unexpected,
        "Unexpected application topics; refusing deletion or partial reconciliation: "
        + ", ".join(sorted(unexpected)),
    )
    if complete:
        if names != set(policy.topics):
            raise TopicNotReady(
                "Missing expected topics: "
                + ", ".join(sorted(set(policy.topics) - names))
            )


def effective_configs(
    admin: Any,
    names: tuple[str, ...],
    resource_factory: Callable[[str], Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if resource_factory is None:
        from confluent_kafka.admin import ConfigResource, ResourceType

        resource_factory = lambda name: ConfigResource(ResourceType.TOPIC, name)
    resources = [resource_factory(name) for name in names]
    futures = admin.describe_configs(resources, request_timeout=30)
    return {
        name: futures[resource].result(timeout=30)
        for name, resource in zip(names, resources)
    }


def inspect_broker(
    admin: Any, policy: TopicPolicy, complete: bool = True
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    metadata = admin.list_topics(timeout=30)
    # Kafka internal topics are broker infrastructure, not application-topic quota.
    names = {name for name in metadata.topics if not name.startswith("__")}
    check_topic_names(names, policy, complete)
    for name in sorted(names):
        topic = metadata.topics[name]
        require(
            topic.error is None and len(topic.partitions) == policy.partitions,
            "Partition count/topic error mismatch: " + name,
        )
        for partition in topic.partitions.values():
            require(
                len(partition.replicas) == policy.replication,
                "Replication factor mismatch: " + name,
            )
            if partition.error is not None or partition.leader < 0:
                raise TopicNotReady("Topic partition is not ready: " + name)
    configs = effective_configs(admin, tuple(sorted(names))) if names else {}
    return metadata.topics, configs


def validate_topic_configs(
    configs: dict[str, dict[str, Any]],
    policy: TopicPolicy,
    free: bool,
    platform_retention: set[str],
) -> list[dict[str, Any]]:
    result = []
    for name in policy.topics:
        values = configs[name]
        require(
            values["cleanup.policy"].value == "delete",
            "Cleanup policy mismatch: " + name,
        )
        retention = int(values["retention.ms"].value)
        source = getattr(values["retention.ms"].source, "name", "")
        forced = (
            name in platform_retention
            or values["retention.ms"].is_read_only
            or (
                free
                and source
                in {
                    "DEFAULT_CONFIG",
                    "DYNAMIC_DEFAULT_BROKER_CONFIG",
                    "STATIC_BROKER_CONFIG",
                }
            )
        )
        require(
            retention == policy.retention_ms
            or (free and forced and 0 < retention <= policy.retention_ms),
            "Retention differs from target without platform-enforcement evidence: "
            + name,
        )
        result.append(
            {
                "topic": name,
                "partitions": policy.partitions,
                "replication_factor": policy.replication,
                "cleanup_policy": "delete",
                "target_retention_ms": policy.retention_ms,
                "actual_retention_ms": retention,
                "retention_source": "platform_enforced" if forced else "target",
                "retention_bytes": (
                    values.get("retention.bytes").value
                    if "retention.bytes" in values
                    else None
                ),
            }
        )
    return result


def reconcile(
    api: AivenAPI,
    admin: Any,
    settings: KafkaSettings,
    policy: TopicPolicy,
    apply: bool = False,
) -> dict[str, Any]:
    service = api.service()
    free = verify_service(service, settings)
    names = {
        t["topic_name"] for t in api.topics() if not t["topic_name"].startswith("__")
    }
    check_topic_names(names, policy, complete=not apply)
    # Inspect every existing topic before changing any service/topic setting.
    _, configs = inspect_broker(admin, policy, complete=not apply)
    auto = (
        service.get("user_config", {}).get("kafka", {}).get("auto_create_topics_enable")
    )
    if auto is not False:
        require(apply, "Broker automatic topic creation is not explicitly disabled")
        api.request(
            "PUT", body={"user_config": {"kafka": {"auto_create_topics_enable": False}}}
        )
        service = api.service()
        require(
            service.get("user_config", {})
            .get("kafka", {})
            .get("auto_create_topics_enable")
            is False,
            "Automatic topic creation did not disable",
        )
    forced: set[str] = set()
    for name in policy.topics:
        if name not in names:
            require(apply, "Expected topic is missing: " + name)
            LOG.info(
                encode(
                    {
                        "event": "topic_create",
                        "topic": name,
                        "partitions": policy.partitions,
                        "replication": policy.replication,
                    }
                ).strip()
            )
            try:
                api.create(name, policy)
            except ApiError as exc:
                if not (free and exc.status == 400 and exc.retention_restricted):
                    raise
                api.create(name, policy, platform_retention=True)
                forced.add(name)
        elif apply:
            current = configs[name]
            retention = int(current["retention.ms"].value)
            if current["retention.ms"].is_read_only:
                forced.add(name)
            if current["cleanup.policy"].value != "delete" or (
                retention != policy.retention_ms and name not in forced
            ):
                try:
                    LOG.info(
                        encode({"event": "topic_configure", "topic": name}).strip()
                    )
                    api.configure(name, None if name in forced else policy.retention_ms)
                except ApiError as exc:
                    if not (free and exc.status == 400 and exc.retention_restricted):
                        raise
                    forced.add(name)
                    if current["cleanup.policy"].value != "delete":
                        api.configure(name, None)
    # Topic creation is asynchronous; bounded polling emits progress, never accepts
    # a half-created topology. Re-running reconciles an already-created prefix.
    deadline = time.monotonic() + 90
    while True:
        try:
            _, configs = inspect_broker(admin, policy)
            break
        except TopicNotReady:
            if not apply or time.monotonic() >= deadline:
                raise
            LOG.info(
                encode(
                    {"event": "topic_metadata_wait", "service": policy.service}
                ).strip()
            )
            time.sleep(2)
    check_topic_names(
        {t["topic_name"] for t in api.topics() if not t["topic_name"].startswith("__")},
        policy,
        True,
    )
    final_service = api.service()
    verify_service(final_service, settings)
    require(
        final_service.get("user_config", {})
        .get("kafka", {})
        .get("auto_create_topics_enable")
        is False,
        "Broker auto-creation drift detected",
    )
    return {
        "event": "kafka_topics_validated",
        "environment": policy.env,
        "service": policy.service,
        "plan": service["plan"],
        "auto_create_topics": False,
        "topics": validate_topic_configs(configs, policy, free, forced),
    }


def smoke_records(
    policy: TopicPolicy, run_id: str, now: datetime, snapshot: Path
) -> list[Record]:
    """Preserve complete KAN-26 payloads; label validation in provenance only."""
    data = load_seed(snapshot, policy.env)
    fingerprint = json.loads((snapshot / "manifest.json").read_text())["fingerprint"]
    candidates = facts(data, policy.env, fingerprint, now)
    # Reuse the session generator with masters only, so no historical event can
    # starve shopping coverage; this never mutates or rewrites the seed.
    masters = {
        co: {
            table: (
                rows
                if table in {"products", "item_master", "customers", "customer_master"}
                else {}
            )
            for table, rows in tables.items()
        }
        for co, tables in data.items()
    }
    candidates += [
        Record(**entry["record"])
        for entry in generate_records(
            masters,
            policy.env,
            fingerprint,
            run_id,
            now,
            EventConfig(
                events=128,
                seed=31,
                duplicate_fraction=0,
                late_fraction=0,
                reorder_fraction=0,
            ),
        )
    ]
    chosen = {}
    for record in candidates:
        if record.topic not in chosen:
            event = record.validate(policy.env)
            aggregate = record.key.removeprefix(
                f"{event['company']}:{event['source_instance']}:"
            )
            chosen[record.topic] = make_record(
                policy.env,
                event["company"],
                event["event_type"],
                aggregate,
                "validation:" + run_id + ":" + event["event_id"],
                datetime.fromisoformat(event["occurred_at"]),
                now,
                event["payload"],
                {
                    **event["provenance"],
                    "validation_only": True,
                    "validation_run_id": run_id,
                    "ticket": "KAN-31",
                },
            )
    require(
        set(chosen) == set(policy.topics),
        "Smoke snapshot must cover commerce/inventory and both shopping domains",
    )
    return [chosen[name] for name in policy.topics]


def verify_message(message: Any, record: Record, env: str, offset: int) -> None:
    require(message.error() is None, "Kafka readback returned a broker error")
    require(
        message.topic() == record.topic
        and message.partition() == 0
        and message.offset() == offset,
        "Kafka readback topic/partition/offset mismatch",
    )
    require(
        message.key() == record.key.encode()
        and message.value() == record.value.encode(),
        "Kafka readback bytes differ",
    )
    record.validate(env)
    headers = dict(message.headers() or [])
    event = json.loads(record.value)
    require(
        headers.get("event_id") == event["event_id"].encode()
        and headers.get("event_version") == b"1"
        and headers.get("payload_version") == b"1",
        "Kafka readback headers differ",
    )


def smoke(
    settings: KafkaSettings, policy: TopicPolicy, snapshot: Path
) -> dict[str, Any]:
    from confluent_kafka import Consumer, Producer, TopicPartition, libversion

    require(
        tuple(map(int, libversion()[0].split(".")[:3])) >= (2, 6, 1),
        "librdkafka 2.6.1+ required for Aiven SCRAM",
    )
    config = settings.client_config()
    run_id = str(uuid.uuid4())
    records = smoke_records(policy, run_id, datetime.now(timezone.utc), snapshot)
    producer = Producer(
        {
            **config,
            "client.id": f"pmdp-{policy.env}-kan31-validation",
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": 30000,
        }
    )
    consumer = Consumer(
        {
            **config,
            "group.id": f"pmdp-{policy.env}-enterprise-validation-{run_id}",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "allow.auto.create.topics": False,
            "auto.offset.reset": "error",
        }
    )
    results = []
    try:
        for record in records:
            acknowledgement: list[tuple[Any, Any]] = []
            event = record.validate(policy.env)
            producer.produce(
                record.topic,
                key=record.key.encode(),
                value=record.value.encode(),
                partition=0,
                headers={
                    "event_id": event["event_id"].encode(),
                    "event_version": b"1",
                    "payload_version": b"1",
                },
                on_delivery=lambda error, message: acknowledgement.append(
                    (error, message)
                ),
            )
            remaining = producer.flush(timeout=35)
            require(
                remaining == 0
                and len(acknowledgement) == 1
                and acknowledgement[0][0] is None,
                "Test event did not receive broker acknowledgement",
            )
            sent = acknowledgement[0][1]
            offset = sent.offset()
            # Direct assignment to the acknowledged offset avoids old records,
            # rebalance delays, and committed offsets on real application groups.
            consumer.assign([TopicPartition(record.topic, 0, offset)])
            message = consumer.poll(timeout=30)
            require(message is not None, "Consumer test event timed out")
            verify_message(message, record, policy.env, offset)
            results.append(
                {
                    "topic": record.topic,
                    "partition": 0,
                    "offset": offset,
                    "event_type": event["event_type"],
                    "event_id": event["event_id"],
                }
            )
    finally:
        consumer.close()
        producer.flush(timeout=5)
    return {
        "event": "kafka_roundtrip_validated",
        "service": policy.service,
        "run_id": run_id,
        "records": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Explicit infrastructure/config/dev.json or test.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Reconcile topics/settings; default validates without mutations",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Publish/read back one labelled test event in each domain",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Existing KAN-24 snapshot required for --smoke; source files remain unchanged",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write sanitized validation evidence outside source data",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        require(
            not args.smoke or args.snapshot is not None,
            "--smoke requires an existing --snapshot",
        )
        env = environment()
        policy = TopicPolicy.load(args.config, env)
        settings = KafkaSettings.from_env(policy)
        from confluent_kafka.admin import AdminClient

        admin = AdminClient(settings.client_config())
        results = [reconcile(AivenAPI(settings), admin, settings, policy, args.apply)]
        LOG.info(encode(results[-1]).strip())
        if args.smoke:
            results.append(smoke(settings, policy, args.snapshot))
            LOG.info(encode(results[-1]).strip())
        if args.report:
            publish(
                args.report,
                {
                    "ticket": "KAN-31",
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "results": results,
                },
            )
    except Exception as exc:
        # No raw Kafka/API exceptions, endpoint strings, tokens or credentials.
        LOG.error(
            encode(
                {
                    "event": "kafka_validation_failed",
                    "error_type": type(exc).__name__,
                    "reason": (
                        str(exc)
                        if isinstance(exc, (ValueError, ApiError))
                        else "Kafka/API operation failed; inspect credentials, permissions and service readiness."
                    ),
                }
            ).strip()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
