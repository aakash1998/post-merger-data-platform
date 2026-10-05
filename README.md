# Post-Merger Enterprise Data Platform

A production-style data engineering project that unifies data after the acquisition of **Stampede City Commerce** by **Rocky Mountain Retail Group**.

## Business Problem

The two companies operate different source systems, schemas, identifiers, refresh patterns, and data-quality standards. Leadership needs one trusted platform for customer, sales, finance, inventory, and operational analytics without first replacing the operational applications.

## Target Architecture

- Rocky Mountain Retail Group: Aiven PostgreSQL
- Stampede City Commerce: Aiven MySQL
- Event streaming: Aiven Kafka
- CDC: AWS DMS
- Landing/storage: Amazon S3
- Lakehouse processing: Databricks
- Table format: Delta Lake
- Warehouse/serving: Snowflake
- Transformations: dbt
- Orchestration: Apache Airflow / Astronomer

## Repository Layout

- `docs/` — architecture, decisions, data contracts, runbooks
- `source-simulator/` — Python source-data generator
- `infrastructure/` — cloud/IaC configuration
- `databricks/` — Bronze/Silver/Gold lakehouse code
- `snowflake/` — Snowflake setup and loading logic
- `dbt/` — dbt project for analytics models
- `airflow/` — DAGs and orchestration code
- `tests/` — cross-platform integration and data-quality tests

## Current Phase

**Phase 1: Source Data Model**

Do not build pipelines until the source schemas, keys, CDC scope, SCD rules, file contracts, and event schemas are agreed.

## Implementation Phases

This delivery sequence implements the [current architecture](docs/architecture.md) and [architecture decisions](docs/decisions.md), based on [KAN-19](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-19) and the existing epics linked below. Phase numbers describe dependency order, not Jira status or evidence that a phase is complete. Phase 1 remains current; this plan does not approve outstanding contracts.

| Phase / Jira epic | Major dependencies | Completion criteria | Gate before the next phase |
| --- | --- | --- | --- |
| 0. Project foundation — [KAN-1](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-1), Project Setup & Architecture | Locked platform architecture and business scope | Architecture, repository layout, environment/naming standards, and delivery sequence documented and reviewed. | Platform responsibilities and configuration conventions agreed before source modeling and service setup. |
| 1. Source contracts — [KAN-2](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-2), Source System Data Model | Phase 0; both companies' source requirements | PostgreSQL/MySQL schemas, stable source keys, cross-company identity rules, CDC scope/order/delete semantics, SCD1/SCD2 policies, CSV/JSON contracts, and Kafka event contracts agreed; assumptions and blocking decisions resolved. | Explicit agreement on all contracts, including schema evolution, audit metadata, history coverage, and late-data handling. Individual schema approval alone does not authorize ingestion. |
| 2. Source readiness — [KAN-4](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-4), Aiven Source Services; [KAN-3](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-3), Synthetic Data & Event Simulator | Phase 1 contracts; secure configuration and access | Aiven PostgreSQL for Rocky Mountain Retail Group, MySQL for Stampede City Commerce, and Kafka configured with approved schemas/topics. Repeatable Python simulator produces seed data, inserts/updates/deletes, CSV/JSON feeds, and contract-valid events. | Connectivity and CDC prerequisites verified; representative source data, files, and events available with repeatable scenario validation. |
| 3. CDC and file landing — [KAN-5](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-5), AWS S3 & DMS CDC Pipeline | Phase 2 database readiness and file fixtures; Phase 1 landing contracts | AWS DMS baseline and subsequent database changes land in S3; CSV/JSON feeds land under agreed contracts. Source identity, operation/order metadata, file identity, and reconciliation evidence retained. | Baseline plus inserts/updates/deletes reconcile to sources; restart and repeated file delivery preserve recoverable input without loss or double-counting. Kafka remains the direct event input to Databricks. |
| 4. Raw lakehouse — [KAN-6](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-6), Databricks Bronze Ingestion | Phase 3 S3 inputs; Phase 2 Kafka events; approved input contracts | Databricks ingests CDC, legacy files, and Kafka events into Bronze Delta tables, preserving raw payloads, source/ingestion audit metadata, and replay positions. Invalid input is traceable. | Representative inputs reconcile to Bronze; restart/replay is verified and raw evidence remains available for downstream recovery. |
| 5. Conformed lakehouse — [KAN-7](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-7), Databricks Silver CDC & SCD Processing | Phase 4 Bronze; approved keys, identity, quality, and history rules | Silver enforces schemas, standardizes and deduplicates data, applies keyed CDC including deletes, maintains SCD1/SCD2 history, and quarantines invalid records. | Tests demonstrate convergence under duplicates, replay, late/out-of-order changes, deletes, and approved schema changes; reconciliation and history checks pass, with unresolved identities retained explicitly. |
| 6. Business datasets — [KAN-8](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-8), Databricks Gold Business Layer | Phase 5 trusted Silver; agreed business definitions and cross-company mappings | Gold Delta datasets expose agreed grains and business measures for customer, sales, finance, inventory, and operations analytics, with lineage and documented source limitations. | Business reconciliation and quality checks pass; mapping ambiguity, unsupported measures, and historical coverage gaps are explicit and accepted before publication. |
| 7. Warehouse serving — [KAN-9](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-9), Snowflake Analytics Serving | Phase 6 curated datasets; secured Snowflake configuration | Curated data loads into Snowflake with audit metadata, controlled access, and repeatable incremental/backfill behavior. | Source-to-warehouse counts and measures reconcile; retries do not duplicate results and downstream dbt input contracts are stable. |
| 8. Analytics models — [KAN-10](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-10), dbt Transformation & Testing | Phase 7 Snowflake inputs; agreed analytical grains and definitions | dbt staging/intermediate models, dimensions, facts, marts, tests, and documentation run in Snowflake. Gold and dbt responsibilities follow the existing architecture decisions. | Model tests and business reconciliations pass; documented lineage, freshness expectations, and repeatable builds support orchestration. |
| 9. Coordinated operations — [KAN-11](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-11), Airflow Orchestration | Validated jobs and interfaces from Phases 3–8 | Airflow/Astronomer coordinates batch dependencies, Databricks jobs, Snowflake loads, and dbt runs/tests, with retries, quality gates, monitoring, and alerts. Continuous DMS/Kafka flows are monitored. | A scheduled end-to-end run succeeds; partial failures block dependent publication, and retries/backfills recover without duplicate business effects. |
| 10. Recovery and handover — [KAN-13](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-13), Failure & Recovery Testing; [KAN-14](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-14), Documentation & Final Demo | Phase 9 integrated workflow; all preceding validation evidence | End-to-end restart, replay, duplicates, deletes, late data, schema-change, and partial-failure scenarios pass. Runbooks, architecture/configuration documentation, and a reproducible final demo cover the approved scope. | Before handover, recovery outcomes reconcile, alerts and runbooks are exercised, and remaining limitations have named owners and acceptance. No later implementation phase is implied. |

### Requirements across phases

- [KAN-12](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-12), CI/CD, Security & Configuration, starts with the foundation and applies before each component is deployed: environment-driven configuration, secrets outside the repository, controlled access, and relevant automated validation/deployment checks.
- [KAN-15](https://aakashsworkspace-61d79316.atlassian.net/browse/KAN-15), Data Quality & Observability, starts with contract definitions and extends through each implemented layer: structured logging, source/ingestion lineage, reconciliation, freshness checks, quality gates, and actionable monitoring/alerts.
- Recovery tests and operational documentation grow with each component; Phase 10 proves the integrated result rather than deferring these requirements until the end.

Advance only when the preceding gate has recorded review and relevant validation evidence, with no unresolved blocker for the dependent work. Independent preparation may overlap (for example, simulator development and Aiven setup after contract agreement, or Airflow scaffolding once job interfaces are stable); it does not bypass a gate or authorize ingestion during Phase 1. Use the current repository company names where older Jira descriptions use earlier names; the architecture remains unchanged.
