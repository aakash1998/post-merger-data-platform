# Post-Merger Enterprise Data Platform Architecture

```mermaid
flowchart LR
    subgraph SRC["Source Systems"]
      RM["Rocky Mountain Retail Group<br/>Aiven PostgreSQL"]
      SC["Stampede City Commerce<br/>Aiven MySQL"]
      SIM["Python Source Simulator<br/>seed + live I/U/D"]
      FILES["Legacy CSV / JSON"]
      KAFKA["Aiven Kafka<br/>streaming events"]
    end

    subgraph CDC["Change Capture & Landing"]
      DMS["AWS DMS<br/>CDC"]
      S3["Amazon S3<br/>CDC + batch landing"]
    end

    subgraph DBX["Databricks Lakehouse"]
      BR["Bronze<br/>raw CDC / files / events"]
      SI["Silver<br/>clean + standardized + deduped<br/>CDC + SCD1/SCD2"]
      GO["Gold<br/>business-ready datasets"]
      DL["Delta Lake tables on S3"]
      BR --> SI --> GO
      DL --- BR
      DL --- SI
      DL --- GO
    end

    subgraph ANALYTICS["Analytics & Transformation"]
      SF["Snowflake<br/>analytics warehouse"]
      DBT["dbt<br/>staging -> intermediate -> marts"]
      BI["BI / Reporting / Executive Dashboards"]
      SF --> DBT --> BI
    end

    SIM --> RM
    SIM --> SC
    SIM --> KAFKA
    RM --> DMS
    SC --> DMS
    DMS --> S3
    FILES --> S3
    S3 --> BR
    KAFKA --> BR
    GO --> SF

    AIR["Apache Airflow / Astronomer<br/>orchestration, monitoring, retries, SLAs"]
    AIR -. trigger/monitor .-> SIM
    AIR -. monitor .-> DMS
    AIR -. run jobs .-> DBX
    AIR -. load .-> SF
    AIR -. run/test .-> DBT
```

## Core Engineering Patterns

- CDC
- SCD Type 1
- SCD Type 2
- schema evolution
- deduplication
- late-arriving data
- data-quality gates
- replay/backfill
- idempotency
- medallion architecture
