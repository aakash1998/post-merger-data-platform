# KAN-31 validation — 2026-10-06 UTC

Real target: pmdp-dev-enterprise-kafka, Aiven free-0. Supplied untracked environment variables and CA were used; no credentials, endpoints or certificate contents are recorded in the evidence.

| Check | Observed result |
| --- | --- |
| Application topic set | Exactly the five approved domain topics; no extra application topics |
| Partitions | One per topic, active leader |
| Replication factor | Two per topic; Aiven explicitly rejected replication factor one |
| Cleanup | delete on all five |
| Retention | 259200000 ms (72 hours) on all five; target accepted, no platform fallback needed |
| Retention byte cap | -1 on all five (no configured topic byte cap) |
| Broker automatic topic creation | Explicitly false |
| TLS/authentication | Verified CA/hostname with SASL_SSL and SCRAM-SHA-256 |
| Producer acknowledgement / consumer readback | One valid labelled event per domain, exact bytes/key/version headers matched at partition 0, offset 0 |
| Repeat apply | Zero service/topic API mutations; all settings still valid |
| Regression suite | 80 tests run: 78 passed, two opt-in database integration tests skipped |
| Routing and determinism | All fifteen company/event types mapped; all eight KAN-27 recipes retain exact independent-run artifact reproduction |

Machine-readable timestamps, effective settings and delivery identities are in [kan-31-validation.json](kan-31-validation.json). The [runbook](README.md) documents reproducible installation, connection variables and execution.

The existing KAN-24 snapshot was located at `../post-merger-data-platform-1/source-simulator/generated/dev/seed-24` and supplied as --snapshot from this worktree. No seed/database writes occurred. Five smoke messages are intentionally retained in Kafka until expiry; provenance marks validation_only, validation_run_id and KAN-31.

Initial API requests returned HTTP 504 / timeout during provisioning. Subsequent runs inspected existing state and completed the remaining topics without deletion or duplicate creation. Final configuration-only validation, smoke validation and repeat-apply checks succeeded. Aiven documentation currently describes two partitions for Free Kafka, but this service accepted and independently reported one per topic; future partition drift fails validation.

No database schemas, DMS, S3, Databricks or ingestion configuration were changed. Legacy event-per-topic plans and prior scenario fingerprints require regeneration into new output directories; they are never rewritten in place. Remote event-generator checkpoints and sustained broker-failure recovery remain outside this ticket. The branch is handed off for review; no merge or Jira Done transition is performed.
