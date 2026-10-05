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
- Use configuration rather than hardcoded environment-specific values, credentials, or secrets; prefer reusable logic over duplication.
- Pipelines must be idempotent, restartable, observable, and testable.
- Preserve source and ingestion audit metadata.
- Design for inserts, updates, deletes, duplicates, replays, schema changes, and late data.
- Use Python type hints and structured logging.
- Follow [environment and naming conventions](docs/environment-naming-conventions.md); select dev/test/prod explicitly through configuration and keep environment targets separate.
- Document assumptions and tradeoffs.
- Do not introduce new technologies without a clear reason.

## Standard Jira Ticket Workflow
For future implementation work, ticket-specific Jira instructions and scope override generic workflow wording.

1. Read the Jira ticket, this file, relevant repository documentation, and existing implementation before editing.
2. Create or switch to `feature/<JIRA-KEY>-<short-description>`; never implement directly on `main`.
3. Keep changes within the ticket's intended scope. Follow the approved architecture, source contracts, naming conventions, and repository decisions; do not redesign approved architecture or schemas unless the ticket explicitly requires it.
4. Add or update meaningful tests when applicable and run relevant validation before finishing.
5. Commit with the Jira key in the commit message and push the feature branch.
6. Add a concise Jira comment with the implementation summary, files changed, tests/validation and results, branch, commit SHA, and material remaining risks.
7. Hand off the branch for review and stop. Do not merge or mark the Jira ticket Done.

## Current Phase
Phase 1: Source Data Model. Do not build ingestion pipelines until schemas, keys, CDC scope, SCD rules, file contracts, and event contracts are agreed.
