"""Topic-policy, fail-closed provisioning, retention and exact readback tests."""

from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from retail_simulator.config import Config
from retail_simulator.event_contract import expected_topics
from retail_simulator.kafka_topics import (
    AivenAPI,
    ApiError,
    KafkaSettings,
    TopicPolicy,
    check_topic_names,
    reconcile,
    smoke_records,
    validate_topic_configs,
    verify_message,
)
from retail_simulator.snapshot import generate

ROOT = Path(__file__).resolve().parents[2]


def entry(value, readonly=False, source="DYNAMIC_TOPIC_CONFIG"):
    return NS(value=str(value), is_read_only=readonly, source=NS(name=source))


def topic_configs(retention=259200000, readonly=False, source="DYNAMIC_TOPIC_CONFIG"):
    return {
        "cleanup.policy": entry("delete"),
        "retention.ms": entry(retention, readonly, source),
        "retention.bytes": entry(-1),
    }


class FakeAdmin:
    def __init__(self):
        self.topics = {"__consumer_offsets": NS(error=None, partitions={})}
        self.configs = {}

    def add(self, name, partitions=1, retention=259200000):
        self.topics[name] = NS(
            error=None,
            partitions={
                i: NS(error=None, leader=0, replicas=[0, 1]) for i in range(partitions)
            },
        )
        self.configs[name] = topic_configs(retention)

    def list_topics(self, timeout):
        return NS(topics=self.topics)


class FakeAPI:
    def __init__(self, policy, admin):
        self.admin = admin
        self.changes = []
        self.retention_denied = False
        self.info = {
            "service_name": policy.service,
            "service_type": "kafka",
            "state": "RUNNING",
            "plan": "free-0",
            "components": [
                {
                    "component": "kafka",
                    "kafka_authentication_method": "sasl",
                    "host": "kafka.test",
                    "port": 12345,
                }
            ],
            "user_config": {
                "kafka": {"auto_create_topics_enable": False},
                "kafka_authentication_methods": {"sasl": True},
            },
        }

    def service(self):
        return self.info

    def topics(self):
        return [
            {"topic_name": name}
            for name in self.admin.topics
            if not name.startswith("__")
        ]

    def request(self, method, suffix="", body=None):
        self.changes.append((method, body))
        self.info["user_config"]["kafka"].update(body["user_config"]["kafka"])
        return {"service": self.info}

    def create(self, name, policy, platform_retention=False):
        self.changes.append(("create", name))
        self.admin.add(name)

    def configure(self, name, retention):
        self.changes.append(("configure", name, retention))
        if self.retention_denied and retention is not None:
            raise ApiError(400, True)
        self.admin.configs[name]["cleanup.policy"] = entry("delete")
        if retention is not None:
            self.admin.configs[name]["retention.ms"] = entry(retention)


class KafkaTopicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = TopicPolicy.load(ROOT / "infrastructure/config/test.json", "test")
        self.settings = KafkaSettings(
            "test",
            self.policy.service,
            "project",
            "api-secret",
            "kafka.test:12345",
            "user",
            "password-secret",
            str(self.root / "ca.pem"),
        )
        self.admin = FakeAdmin()
        self.api = FakeAPI(self.policy, self.admin)
        self.patch = patch(
            "retail_simulator.kafka_topics.effective_configs",
            side_effect=lambda admin, names: {
                name: admin.configs[name] for name in names
            },
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_exact_environment_separated_topic_policy(self):
        self.assertEqual(self.policy.topics, expected_topics("test"))
        with self.assertRaises(ValueError):
            TopicPolicy.load(ROOT / "infrastructure/config/dev.json", "test")
        for key, value in [
            ("partitions", 2),
            ("cleanup_policy", "compact"),
            ("allow_auto_create_topics", True),
            ("target_retention_ms", 86400000),
            ("topics", ["extra"]),
        ]:
            raw = json.loads((ROOT / "infrastructure/config/test.json").read_text())
            raw["kafka"][key] = value
            path = self.root / "bad.json"
            path.write_text(json.dumps(raw))
            with self.subTest(key=key), self.assertRaises(ValueError):
                TopicPolicy.load(path, "test")

    def test_tls_scram_and_environment_credentials_fail_closed(self):
        config = self.settings.client_config()
        self.assertEqual(config["security.protocol"], "SASL_SSL")
        self.assertEqual(config["sasl.mechanism"], "SCRAM-SHA-256")
        self.assertTrue(config["enable.ssl.certificate.verification"])
        self.assertEqual(config["ssl.endpoint.identification.algorithm"], "https")
        self.assertNotIn("password-secret", repr(self.settings))
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            ValueError, "PMDP_KAFKA_SERVICE"
        ):
            KafkaSettings.from_env(self.policy)

    def test_supplied_connection_aliases_and_conflicts(self):
        ca = self.root / "ca.pem"
        ca.write_text("test CA")
        values = {
            "PMDP_KAFKA_SERVICE": self.policy.service,
            "PMDP_AIVEN_PROJECT": "project",
            "PMDP_AIVEN_TOKEN": "token",
            "PMDP_KAFKA_BOOTSTRAP_SERVERS": "kafka.test:12345",
            "PMDP_KAFKA_USERNAME": "user",
            "PMDP_KAFKA_PASSWORD": "secret",
            "PMDP_KAFKA_CA": str(ca),
        }
        with patch.dict(os.environ, values, clear=True):
            settings = KafkaSettings.from_env(self.policy)
            self.assertEqual(settings.username, "user")
            self.assertEqual(settings.password, "secret")
            self.assertEqual(settings.ca, str(ca))
            os.environ["PMDP_KAFKA_SASL_PASSWORD"] = "different"
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                KafkaSettings.from_env(self.policy)

    def test_partial_creation_restart_and_free_retention_rejection(self):
        original = self.api.create

        def fail_second(name, policy, platform_retention=False):
            if name == policy.topics[1]:
                raise ApiError(504)
            original(name, policy, platform_retention)

        with patch.object(
            self.api, "create", side_effect=fail_second
        ), self.assertRaises(ApiError):
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertIn(self.policy.topics[0], self.admin.topics)
        report = reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(len(report["topics"]), 5)
        self.assertEqual(self.api.changes.count(("create", self.policy.topics[0])), 1)
        # An explicit platform refusal allows the existing inherited retention;
        # subsequent read-only validation independently checks broker evidence.
        for name in self.policy.topics:
            self.admin.configs[name] = topic_configs(86400000, source="DEFAULT_CONFIG")
        self.api.retention_denied = True
        report = reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertTrue(
            all(t["actual_retention_ms"] == 86400000 for t in report["topics"])
        )
        self.assertEqual(
            reconcile(self.api, self.admin, self.settings, self.policy), report
        )

    def test_wrong_replication_rejected_before_mutations(self):
        self.admin.add(self.policy.topics[0])
        self.admin.topics[self.policy.topics[0]].partitions[0].replicas = [0]
        with self.assertRaisesRegex(ValueError, "Replication"):
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(self.api.changes, [])

    def test_first_provision_and_exact_replay_without_topic_changes(self):
        report = reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(len(report["topics"]), 5)
        self.assertEqual(len(self.api.changes), 5)
        self.api.changes.clear()
        self.assertEqual(
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True),
            report,
        )
        self.assertEqual(self.api.changes, [])
        self.assertEqual(
            reconcile(self.api, self.admin, self.settings, self.policy), report
        )

    def test_unexpected_topic_rejected_before_any_mutations(self):
        self.admin.add("legacy-event-topic")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(self.api.changes, [])

    def test_wrong_partition_count_never_silently_accepted_or_changed(self):
        self.admin.add(self.policy.topics[0], partitions=2)
        with self.assertRaisesRegex(ValueError, "Partition"):
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(self.api.changes, [])

    def test_missing_topics_check_only_does_not_create(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            reconcile(self.api, self.admin, self.settings, self.policy)
        self.assertEqual(self.api.changes, [])

    def test_broker_auto_creation_explicitly_disabled(self):
        for name in self.policy.topics:
            self.admin.add(name)
        self.api.info["user_config"]["kafka"]["auto_create_topics_enable"] = True
        with self.assertRaisesRegex(ValueError, "automatic"):
            reconcile(self.api, self.admin, self.settings, self.policy)
        report = reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertFalse(report["auto_create_topics"])
        self.assertEqual(
            self.api.changes,
            [("PUT", {"user_config": {"kafka": {"auto_create_topics_enable": False}}})],
        )

    def test_retention_target_and_platform_enforcement_evidence(self):
        configs = {
            name: topic_configs(86400000, readonly=True) for name in self.policy.topics
        }
        report = validate_topic_configs(configs, self.policy, True, set())
        self.assertTrue(
            all(
                t["actual_retention_ms"] == 86400000
                and t["retention_source"] == "platform_enforced"
                for t in report
            )
        )
        with self.assertRaises(ValueError):
            validate_topic_configs(configs, self.policy, False, set())
        for name in configs:
            configs[name] = topic_configs(86400000, source="DEFAULT_CONFIG")
        self.assertEqual(
            validate_topic_configs(configs, self.policy, True, set()), report
        )
        for name in configs:
            configs[name] = topic_configs(86400000)
        with self.assertRaises(ValueError):
            validate_topic_configs(configs, self.policy, True, set())
        configs[self.policy.topics[0]] = topic_configs(604800000, readonly=True)
        with self.assertRaises(ValueError):
            validate_topic_configs(configs, self.policy, True, set(self.policy.topics))

    def test_mutable_retention_is_reconciled_and_rerun_safe(self):
        for name in self.policy.topics:
            self.admin.add(name, retention=86400000)
        report = reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertTrue(
            all(t["actual_retention_ms"] == 259200000 for t in report["topics"])
        )
        self.assertEqual(len(self.api.changes), 5)
        self.api.changes.clear()
        reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(self.api.changes, [])

    def test_wrong_service_endpoint_is_rejected_before_mutations(self):
        self.api.info["components"][0]["host"] = "other.test"
        with self.assertRaisesRegex(ValueError, "Bootstrap"):
            reconcile(self.api, self.admin, self.settings, self.policy, apply=True)
        self.assertEqual(self.api.changes, [])

    def test_api_error_does_not_expose_token_or_response(self):
        api = AivenAPI(self.settings)
        error = HTTPError(
            "https://api.aiven.io",
            400,
            "error",
            {},
            io.BytesIO(
                b'{"message":"retention cannot be changed on free tier", "secret":"api-secret"}'
            ),
        )
        with patch("retail_simulator.kafka_topics.urlopen", side_effect=error):
            with self.assertRaises(ApiError) as result:
                api.request("GET")
        self.assertTrue(result.exception.retention_restricted)
        self.assertNotIn("api-secret", str(result.exception))

    def test_smoke_reuses_complete_payloads_and_checks_exact_offsets_headers(self):
        snapshot = self.root / "seed"
        manifest = generate(
            Config(
                rmrg_customers=12,
                scc_customers=12,
                rmrg_products=12,
                scc_products=12,
                rmrg_orders=5,
                scc_orders=5,
            ),
            snapshot,
            "test",
        )
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        records = smoke_records(self.policy, "run-31", now, snapshot)
        self.assertEqual([r.topic for r in records], list(self.policy.topics))
        self.assertEqual(records, smoke_records(self.policy, "run-31", now, snapshot))
        for record in records:
            event = record.validate("test")
            self.assertTrue(event["provenance"]["validation_only"])
            self.assertNotIn("validation_only", event["payload"])
            self.assertTrue(event["payload"])
            message = NS(
                error=lambda: None,
                topic=lambda: record.topic,
                partition=lambda: 0,
                offset=lambda: 42,
                key=lambda: record.key.encode(),
                value=lambda: record.value.encode(),
                headers=lambda: [
                    ("event_id", event["event_id"].encode()),
                    ("event_version", b"1"),
                    ("payload_version", b"1"),
                ],
            )
            verify_message(message, record, "test", 42)
            with self.assertRaisesRegex(ValueError, "offset"):
                verify_message(message, record, "test", 43)
            message.headers = lambda: []
            with self.assertRaisesRegex(ValueError, "headers"):
                verify_message(message, record, "test", 42)
        self.assertEqual(json.loads((snapshot / "manifest.json").read_text()), manifest)


if __name__ == "__main__":
    unittest.main()
