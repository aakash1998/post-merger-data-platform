# Aiven Kafka topics — KAN-31

The reconciler creates exactly the [five approved domain topics](../../docs/environment-naming-conventions.md#kafka) on `pmdp-dev-enterprise-kafka`, each with one partition, replication factor two (required by this Aiven service), delete cleanup and a target `retention.ms=259200000` (72 hours). It preserves all fifteen company/event types. Dev and test policies are separate JSON files; prod is rejected.

## Install and select connections

From the repository root, with Python 3.11+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e './source-simulator[kafka]'
set +x
set -a
source .env.local
set +a
```

The environment file and CA PEM must remain untracked. Do not enable shell tracing. Provide these variables through the shell; no connection defaults or credentials are supplied:

| Variable | Required value |
| --- | --- |
| PMDP_ENV | dev (or explicitly test with the matching policy/service) |
| PMDP_KAFKA_SERVICE | pmdp-dev-enterprise-kafka |
| PMDP_KAFKA_BOOTSTRAP_SERVERS | Aiven SASL hostname:port, comma-separated if necessary; no URI or embedded credentials |
| PMDP_KAFKA_SASL_USERNAME | Kafka SASL username; alias PMDP_KAFKA_USERNAME supported |
| PMDP_KAFKA_SASL_PASSWORD | Kafka SASL password; alias PMDP_KAFKA_PASSWORD supported |
| PMDP_KAFKA_SSL_CA | Absolute path to Aiven Kafka CA PEM; alias PMDP_KAFKA_CA supported |
| PMDP_AIVEN_PROJECT | Project containing the selected service |
| PMDP_AIVEN_TOKEN | API token permitted to inspect/update that service and manage its topics |

Canonical and alias values must agree if both are provided. API calls use HTTPS; Kafka clients use SASL_SSL, SCRAM-SHA-256 and verified TLS hostname/CA. Service identity, running state, SASL support and configured bootstrap endpoints are checked against Aiven before mutation. Optional confluent-kafka uses librdkafka 2.6.1+ for Aiven SCRAM compatibility.

## Provision, validate and test delivery

Find the existing KAN-24 snapshot directory containing manifest.json. It must match PMDP_ENV and include both commerce/inventory facts and product/customer masters. This example uses the standard generated location; pass the actual existing path, including an absolute path from another worktree if necessary.

```sh
# Create missing topics and reconcile mutable settings, then verify broker state.
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.kafka_topics \
  --config infrastructure/config/dev.json --apply \
  --report source-simulator/generated/kan31-topics.json

# Read-only configuration validation plus five explicit synthetic smoke records.
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.kafka_topics \
  --config infrastructure/config/dev.json --smoke \
  --snapshot source-simulator/generated/dev/seed-24 \
  --report source-simulator/generated/kan31-roundtrip.json

# Repeat apply: conforming topics/settings are left intact.
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.kafka_topics \
  --config infrastructure/config/dev.json --apply

# Configuration validation only: no topic/service/message writes.
PYTHONPATH=source-simulator/src .venv/bin/python -m retail_simulator.kafka_topics \
  --config infrastructure/config/dev.json
```

Installed entry point: `pmdp-kafka-topics`. For test, select PMDP_ENV=test, infrastructure/config/test.json and separate test connection settings. Successful execution exits zero and emits structured JSON; failures exit one. Reports publish atomically and contain configuration/validation evidence, never credentials or certificate contents.

The control plane disables `kafka.auto_create_topics_enable`, creates missing topics, and updates only cleanup/retention drift. Broker metadata and effective configs independently verify the exact application-topic set, partition readiness, delete policy and retention. Internal `__*` broker topics are excluded. Unexpected application topics and existing partition mismatches fail before any changes. There is no delete/repartition/overwrite option. A partially completed create sequence can be retried; run one reconciler per service at a time. Kafka/API failure stops the run; rerun only after correcting its cause.

`--smoke` publishes one valid KAN-26 event in each domain using existing seed facts/session generation. It retains complete payloads and source keys, adds `validation_only`, `validation_run_id` and `ticket=KAN-31` provenance, and assigns distinct validation event identities. Source files/databases are untouched. Each message must receive broker acknowledgement, then an isolated consumer directly reads the acknowledged topic/partition/offset and checks exact key/value bytes and version/identity headers. No application group offsets are committed. Smoke records remain until retention expiry; each smoke invocation intentionally appends five new validation records. Do not run it as a business data load.

## Free-tier limits and validation

[Aiven Free Kafka](https://aiven.io/docs/products/kafka/free-tier/kafka-free-tier) documents five topics and fixed retention, and currently describes two partitions per topic. The reconciler enforces the requested one partition and fails if the real service rejects it; it never substitutes two. Retention fallback is allowed only for Free services with explicit API restriction, read-only metadata or inherited broker defaults. Actual retention must be positive and at most the three-day target. Reports record actual retention and byte limits; a byte cap can expire data sooner. No unlimited or silently configurable retention drift is accepted. See [Free advanced parameters](https://aiven.io/docs/products/kafka/reference/advanced-params-free-tier) and [Aiven SASL support](https://aiven.io/docs/products/kafka/howto/kafka-sasl-auth).

Run offline regression validation:

```sh
PYTHONPATH=source-simulator/src .venv/bin/python -m unittest discover \
  -s source-simulator/tests -v
```

Tests cover all fifteen routes, all eight deterministic recipes, wrong environment/version/domain, unexpected topics/partitions, safe replay, TLS and secret handling, retention evidence, broker creation settings and exact smoke readback. Database integration tests are opt-in and outside KAN-31; no database schema, DMS, S3 or Databricks changes are made.

## Recorded development validation

[The KAN-31 validation record](kan-31-validation.md) captures the observed five topics, one partition each, replication two, delete cleanup, actual 72-hour retention, disabled automatic creation, five successful producer/consumer readbacks and a zero-mutation repeat apply.
