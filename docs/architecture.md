# Architecture

See the rendered architecture diagram: [Architecture Diagram](architecture/architecture-diagram.md).

## Source Systems
- Rocky Mountain Retail Group -> Aiven PostgreSQL
- Stampede City Commerce -> Aiven MySQL
- Python source simulator -> seed data and live inserts/updates/deletes
- Aiven Kafka -> event-stream data
- CSV/JSON -> legacy and batch feeds

## CDC and Landing
- AWS DMS captures PostgreSQL/MySQL inserts, updates, and deletes.
- DMS writes CDC files to Amazon S3.
- Legacy CSV/JSON files also land in S3.
- Kafka events stream directly to Databricks.

## Databricks Lakehouse
- Bronze: raw CDC, files, events, audit metadata
- Silver: schema enforcement, cleaning, deduplication, standardization, CDC application, SCD1/SCD2, quarantine
- Gold: trusted business-ready datasets
- Delta Lake is the table/storage layer on object storage.

## Analytics
- Curated datasets are loaded into Snowflake.
- dbt runs against Snowflake for staging, intermediate models, dimensions, facts, marts, tests, and documentation.

## Orchestration
Apache Airflow / Astronomer coordinates batch dependencies, Databricks jobs, Snowflake loads, dbt runs/tests, monitoring, retries, and alerts. Streaming/CDC remains continuous and is monitored rather than implemented as an Airflow polling loop.
