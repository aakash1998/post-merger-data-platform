# AGENTS.md

## Mission
Build a production-style post-merger enterprise data platform for:
- Company A: Rocky Mountain Retail Group
- Company B: Stampede City Commerce

## Locked Architecture
- Rocky Mountain Retail Group: PostgreSQL on Aiven
- Stampede City Commerce: MySQL on Aiven
- Streaming: Kafka on Aiven
- Database CDC: AWS DMS -> Amazon S3
- Batch/legacy files: CSV/JSON -> Amazon S3
- Lakehouse: Databricks
- Table format: Delta Lake
- Medallion layers: Bronze -> Silver -> Gold
- Analytics warehouse: Snowflake
- Analytics transformations/tests: dbt
- Orchestration: Apache Airflow / Astronomer

## Engineering Rules
- Production-style code; avoid tutorial-only shortcuts.
- Never hardcode credentials or secrets.
- Pipelines must be idempotent, restartable, observable, and testable.
- Preserve source and ingestion audit metadata.
- Design for inserts, updates, deletes, duplicates, replays, schema changes, and late data.
- Use Python type hints and structured logging.
- Add automated tests for meaningful behavior.
- Prefer configuration-driven logic over duplication.
- Follow [environment and naming conventions](docs/environment-naming-conventions.md); select dev/test/prod explicitly through configuration and keep environment targets separate.
- Document assumptions and tradeoffs.
- Do not introduce new technologies without a clear reason.

## Agent Workflow
For each Jira ticket:
1. Read this file and the relevant docs.
2. Inspect the existing implementation before editing.
3. Implement only the ticket's intended scope.
4. Add or update tests.
5. Run relevant validation commands.
6. Report assumptions, files changed, tests run, and remaining risks.

## Current Phase
Phase 1: Source Data Model. Do not build ingestion pipelines until schemas, keys, CDC scope, SCD rules, file contracts, and event contracts are agreed.
