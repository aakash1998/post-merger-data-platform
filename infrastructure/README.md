# Infrastructure

Infrastructure and environment configuration for Aiven, AWS, Databricks, Snowflake, dbt, and Airflow/Astronomer.

Follow the [environment and naming conventions](../docs/environment-naming-conventions.md). KAN-31 implements [Aiven Kafka topic provisioning and validation](kafka/README.md), with explicit dev/test JSON policies under config/. Other infrastructure remains outside this implementation.

No credentials or certificates belong in this repository.
