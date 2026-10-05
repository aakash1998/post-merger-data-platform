# Post-Merger Enterprise Data Platform

A production-style data engineering project that unifies data after the acquisition of **Stampede City Commerce** by **Rocky Mountain Retail Group**.

## Business Problem

The two companies operate different source systems, schemas, identifiers, refresh patterns, and data-quality standards. Leadership needs one trusted platform for customer, sales, finance, inventory, and operational analytics without first replacing the operational applications.

See [merger analytics business questions](docs/merger-analytics-questions.md) for the proposed KPIs, source domains, and reporting marts.

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
