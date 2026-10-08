# Infrastructure

Infrastructure and environment configuration for Aiven, AWS, Databricks, Snowflake, dbt, and Airflow/Astronomer.

Follow the [environment and naming conventions](../docs/environment-naming-conventions.md). KAN-31 implements [Aiven Kafka topic provisioning and validation](kafka/README.md), with explicit dev/test JSON policies under config/. KAN-33 implements [dev S3 raw landing provisioning and validation](s3/README.md), with the verified AWS target and resolved bucket in config/dev.json. Other infrastructure remains outside these implementations.

No credentials or certificates belong in this repository.
