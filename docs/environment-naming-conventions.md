# Environment, naming and configuration conventions

KAN-18 standard for future implementation. Uses the locked architecture; does not provision resources, rename existing source objects or approve event/file contracts. Templates describe names/roles, not a requirement for a separate resource per role. Examples use dev; changing the environment token gives the corresponding test/prod name.

## Shared tokens and environments

| Token | Standard |
| --- | --- |
| Project | `pmdp` = post-merger data platform; `PMDP` in Snowflake/config identifiers |
| Company | `rmrg` = Rocky Mountain Retail Group; `scc` = Stampede City Commerce |
| Shared scope | `enterprise` for cross-company resources/datasets; not a third source company |
| Environment | Exactly `dev`, `test`, `prod`; uppercase DEV/TEST/PROD in Snowflake identifiers |
| Region/account | Actual configured AWS region and 12-digit account ID; examples are illustrative, not deployment selections |

`dev` is development/experimentation, `test` is repeatable integration/acceptance validation, and `prod` is production business workloads. Keep data targets and credentials environment-specific; names alone do not enforce access separation. Runtime environment is required, with no implicit fallback to prod or another environment. Synthetic fixtures belong in dev/test; cross-environment copies need explicit selection and appropriate data handling. This does not mandate a particular account/workspace topology.

For new infrastructure resource labels use `pmdp-<env>-<scope>-<role>` in lowercase ASCII letters/digits/hyphens. Examples: `pmdp-dev-rmrg-postgres`, `pmdp-dev-scc-mysql`, `pmdp-dev-enterprise-kafka`, `pmdp-dev-rmrg-dms`. Provider-specific names follow the templates below; enforce provider limits during later provisioning, shortening descriptive roles consistently when necessary. No credentials, customer identifiers or personal data in names.

Preserve source contracts: RMRG PostgreSQL schema stays `rmrg`; SCC MySQL database stays `scc`; source table names/PKs remain unchanged. Environment separation uses configured source services/instances, not renaming source schemas. Register logical source instances as `rmrg-retail-<env>` and `scc-retail-<env>`, consistent with KAN-22's prod examples; do not derive identity from transient hostnames. Existing resources are not silently renamed by this document.

## Amazon S3

General-purpose bucket template: `pmdp-<env>-<role>-<region>-<account-id>`, with role `landing` or `lakehouse`. Example: `pmdp-dev-landing-ca-central-1-123456789012`. Lowercase letters/digits/hyphens only; 3–63 characters and globally available in the AWS partition. Account/region qualification reduces collisions but does not guarantee availability: check during provisioning, and if necessary append a persisted short lowercase alphanumeric suffix within the length limit. The actual resolved bucket name belongs in config. See [AWS naming rules](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucketnamingrules.html).

| Bucket role | Prefix template | Example |
| --- | --- | --- |
| landing: database CDC | `cdc/<company>/<source-namespace>/<table>/` | `cdc/rmrg/rmrg/customers/`; `cdc/scc/scc/item_master/` |
| landing: batch/legacy | `batch/<company>/<dataset>/` | `batch/scc/returns_register/` |
| lakehouse: Delta storage | `<layer>/<scope>/<dataset>/` | `bronze/scc/customer_master/`; `gold/enterprise/customer_sales/` |

Layer is `bronze`, `silver` or `gold`; scope is rmrg/scc/enterprise. Environment is in the bucket, not repeated inside each prefix. Preserve approved snake_case source tables/dataset tokens; prefixes are lowercase and end with `/`. DMS-generated task/schema/table suffixes and batch/date/revision/file names must be agreed in the later capture/file contracts. Where DMS appends schema/table paths, configure the base so the resulting root follows this template without duplicating segments. These are logical storage roots, not a fabricated DMS payload/file layout. Keep database CDC in DMS -> S3 and business events in Kafka -> Databricks.

## Kafka

Business event topic template: `pmdp-<env>-<company>-<domain>-<event>-v<major>`. Use lowercase letters/digits/hyphens only, with tokens also hyphenated; do not mix dots/underscores into topic names. Examples: `pmdp-dev-rmrg-orders-created-v1`, `pmdp-test-scc-orders-created-v1`. The example event names do not approve event schemas or require new producers.

Use major-version suffixes for incompatible event contracts; compatible evolution stays in the existing topic under the agreed contract. No dates, Jira keys or customer IDs in topic names. Consumer group template: `pmdp-<env>-<scope>-<consumer>`, e.g. `pmdp-dev-rmrg-bronze-orders`. Environment must be explicit even when clusters are separated. Database CDC is not re-routed through Kafka. Partition/retention/schema compatibility settings belong to later contracts, not this naming ticket.

## Databricks

Catalog: `pmdp_<env>`. Schema: `<layer>_<scope>`, lowercase snake_case. Examples: `pmdp_dev.bronze_rmrg.customers`, `pmdp_dev.bronze_scc.customer_master`, `pmdp_test.silver_enterprise.customer_crosswalk`, `pmdp_prod.gold_enterprise.customer_sales`.

Layers are bronze/silver/gold; scopes are rmrg/scc/enterprise. Raw source table tokens stay unchanged in source-specific Bronze schemas; shared curated dataset names are descriptive snake_case. Environment is in the catalog, not the table. Use fully qualified catalog/schema/table names from config. Crosswalk/table examples describe naming only and do not create DDL or duplicate approved logical structures.

## Snowflake

Use uppercase **unquoted** identifiers, consistent with [Snowflake identifier resolution](https://docs.snowflake.com/en/sql-reference/identifiers-syntax). Database: `PMDP_<ENV>_ANALYTICS`. Schemas: `CURATED` for Databricks Gold deliveries, `STAGING`, `INTERMEDIATE`, `CORE` for dimensions/facts, and `MARTS` for dbt analytics. Examples: `PMDP_DEV_ANALYTICS.CURATED.CUSTOMER_SALES`, `PMDP_PROD_ANALYTICS.CORE.DIM_CUSTOMER`.

Warehouse template: `PMDP_<ENV>_<ROLE>_WH`, roles `LOAD`, `TRANSFORM`, `ANALYTICS`; example `PMDP_TEST_TRANSFORM_WH`. Config selects the actual warehouse assigned to the workload; roles need not imply three separately provisioned warehouses. Environment is encoded at database/warehouse level, not repeated in table names. dbt runs against Snowflake and owns analytical transformations; these names do not move lakehouse engineering into dbt.

## Configuration and environment variables

Select environment via required `PMDP_ENV=dev|test|prod`. Project-defined variables use uppercase snake_case `PMDP_<COMPONENT>_<SETTING>`; company-specific settings include RMRG/SCC. Canonical examples:

| Variable | Meaning / example |
| --- | --- |
| PMDP_ENV | Required runtime environment, e.g. `dev` |
| PMDP_AWS_REGION | Configured region, e.g. `ca-central-1` |
| PMDP_S3_LANDING_BUCKET, PMDP_S3_LAKEHOUSE_BUCKET | Resolved environment bucket names |
| PMDP_RMRG_POSTGRES_HOST, PMDP_RMRG_POSTGRES_DATABASE | Connection targets; schema remains rmrg |
| PMDP_SCC_MYSQL_HOST, PMDP_SCC_MYSQL_DATABASE | Connection targets; database remains scc |
| PMDP_RMRG_SOURCE_INSTANCE, PMDP_SCC_SOURCE_INSTANCE | Stable registered source instance names |
| PMDP_KAFKA_BOOTSTRAP_SERVERS, PMDP_KAFKA_RMRG_ORDERS_TOPIC | Resolved cluster endpoint and explicit topic name |
| PMDP_DATABRICKS_HOST, PMDP_DATABRICKS_CATALOG | Environment workspace/endpoint and catalog, e.g. pmdp_dev |
| PMDP_SNOWFLAKE_ACCOUNT, PMDP_SNOWFLAKE_DATABASE | Account and database, e.g. PMDP_DEV_ANALYTICS |
| PMDP_SNOWFLAKE_WAREHOUSE | Actual selected workload warehouse |

Project config keys use lowercase snake_case; documented environment-variable overrides take precedence over selected environment config, followed by shared nonsecret defaults. Never default environment/host/database/bucket/catalog/topic targets silently; verify all selected targets agree with PMDP_ENV. Secrets are injected separately, have no checked-in/default values and must not appear in logs. Standard provider/tool variables, e.g. AWS_REGION or AIRFLOW_CONN_* where required, retain their vendor names; document any mapping from project settings and do not let conflicting values choose a different environment silently.

Future checked-in nonsecret environment config belongs under `infrastructure/config/<env>.<format>` (one format chosen when implementation starts), with shared defaults documented there. No config files are created now. Developer `.env` files stay untracked; templates may contain placeholders only. Missing/malformed required targets fail validation rather than selecting production. Naming/config choices are reusable across Airflow, Databricks, Snowflake and dbt without hardcoding company credentials or changing the architecture.
