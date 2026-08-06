# Project Architecture: Renewable Energy FinOps

> This document describes the data architecture based on the **Medallion Architecture** pattern (Bronze, Silver, and Gold), designed to ensure scalability, data quality, and data governance.

## 1. Data Pipeline Overview

The pipeline ingests weather data and solar energy generation estimates, processing them until they are ready for consumption by Business Intelligence (BI) tools.

## 2. Medallion Architecture Layers

### Bronze Layer (Raw)

* **Storage:** Google Cloud Storage (GCS)
* **Purpose:** Store raw data retrieved from the Open-Meteo and PVGIS APIs in their native JSON format.
* **Partitioning:** Data is partitioned by extraction date and stored in the `gs://bronze-raw-data/` bucket.
* **Business Rule:** Data in this layer is immutable (append-only or overwrite by extraction date).

### Silver Layer (Trusted/Staging)

* **Storage:** Google BigQuery
* **Purpose:** Maintain the single source of truth. Data is cleaned, typed, deduplicated, and validated.
* **Primary Table:** `stg_weather_solar`
* **Business Rule:** Strict schema validation (using Pydantic) and idempotent data loading (MERGE/UPSERT) to prevent duplicate records.

### Gold Layer (Refined/Marts)

* **Storage:** Google BigQuery
* **Purpose:** Consolidate business metrics for reporting and Business Intelligence (BI).
* **Primary Table:** `fct_energy_generation` (business-oriented aggregated tables).
* **Business Rule:** Combine weather data with solar energy generation data to calculate efficiency metrics and assess operational impact.
