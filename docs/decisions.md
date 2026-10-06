# Architecture Decision Log

## ADR-001 — Keep both operational databases after acquisition
Rocky Mountain Retail Group remains on PostgreSQL and Stampede City Commerce remains on MySQL during the integration period. The project integrates data rather than migrating MySQL into PostgreSQL.

## ADR-002 — Cloud-first development
Managed/cloud services are preferred. Local Docker is not part of the initial architecture.

## ADR-003 — Managed CDC with AWS DMS
AWS DMS captures database changes and writes CDC data to Amazon S3. Kafka remains focused on event streaming.

## ADR-004 — Databricks and Snowflake have different responsibilities
Databricks is the engineering/lakehouse platform. Snowflake is the analytics serving warehouse. Avoid duplicating every transformation in both platforms.

## ADR-005 — dbt runs on Snowflake
dbt owns analytical transformations, tests, dimensional models, and marts in Snowflake.

## ADR-006 — Airflow orchestrates; it does not replace streaming
Airflow coordinates dependencies and scheduled workflows. CDC and event streams remain continuous.

## ADR-007 — Route Kafka events through five domain topics (KAN-31)
Aiven Free Kafka limits the service to five application topics. Keep Kafka and consolidate the fifteen company/event routes into RMRG commerce, inventory and shopping, and SCC commerce and activity. Preserve event_type, payloads, qualified source keys, event identities and versions. The [naming standard](environment-naming-conventions.md#kafka) defines the complete mapping. Provision one partition each with delete cleanup, target three-day retention where supported, and broker automatic topic creation disabled. Verify actual platform settings with the [runbook](../infrastructure/kafka/README.md); an unsupported partition count fails rather than changing the approved policy.
