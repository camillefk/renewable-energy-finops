# Data Quality Framework

> Guarantee that **only valid data reaches the Silver Layer** (`silver_trusted_dataset`) and that reruns/backfills **never create duplicates**. Quality is enforced by a *blocking* gate between Bronze (GCS) and Silver (BigQuery).

## 1. Where the gate sits
```text
fetch (x3 cities) -> upload_to_gcs_bronze (x3) -> validate_data_quality (x3) -> load_bronze_to_silver_bq (x1)
                                                        |                              |
                                          any city fails -> AirflowFailException       upstream_failed -> SKIPPED
```

Both sources (Open-Meteo, PVGIS) run the same pattern with the same tasks (`override(task_id=...)`).

| Source | Validation task | Load task | Silver table |
| ----- | ----- | ----- | ----- |
| Open-Meteo | `validate_weather_data_quality` | `load_weather_to_silver_bq` | `silver_weather_hourly` |
| PVGIS | `validate_solar_data_quality` | `load_solar_to_silver_bq` | `silver_solar_hourly` |

**All-or-nothing per source**: the load task has the default `all_success` trigger rule. If one of the 3 mapped validations fails, the load is skipped and *nothing partial* reaches BigQuery. Bronze keeps the raw file for investigation (Bronze is immutable evidence, never "fixed").

## 2. Validation Contract (`utils/schemas.py`)
Implemented with **Pydantic v2**, in two level.

### 2.1 Schema Level

| Check | Rule |
| ----- | ---------- |
| Types | Only JSON numbers accepted: `null`, strings and booleans are rejected | 
| Nulls in critical fields | Every metric is mandatory and non-null (a single `null` fails the file) |
| NaN / Infinity | Rejected |
| Equal series lengths | All Open-Meteo hourly arrays must have the same length |
| Timestamps | Must parse (`ISO-8601` for Open-Meteo, `YYYYMMDD:HHMM` for PVGIS) |

Physical ranges:
| Field | Range | Unit |
| -------- | --- | --- |
| `temperature_2m` / `T2m` | -5m ... 50 | °C |
| `shortwave_radiation` / `G(i)` | 0 ... 1400 | W/m² |
| `cloud_cover` | 0 ... 100 | % |
| `wind_speed_100m` (Open-Meteo) | 0 ... 200 | km/h |
| `WS10m` (PVGIS) | 0 ... 60 | m/s |
| `H_sun` (PVGIS) | 0 ... 90 |	° |

### 2.2 Business-rule Level (`check_business_rules`)

| Check |	Open-Meteo |	PVGIS |
| -------- | --- | --- |
| Exactly 24 hourly records |	✅ |	✅ |
| No duplicated timestamps/hours |	✅ |	✅ |
| All records belong to the requested date (`ds`) |	✅ (date) |	✅ (month/day) |
| Coordinates inside the Netherlands bounding box |	✅ |	– |
| `effective_year` plausible and consistent with `proxy_year_used` |	– |	✅ |

> **Proxy year (PVGIS):** PVGIS has no data for future/recent dates, so the client falls back to a historical year. The contract accepts it (flagged with `proxy_year_used`), and Silver stores `source_year` and `is_proxy_year` so downstream consumers can tell. `observed_at` is anchored on the **requested** date so both sources share the same grain.

## 3. Failure Policy (fail-fast)

1. `validate_payload` raises `DataQualityError` carrying a compact list os violations.
2. The task logs a structured `validate_data_quality.failed` event (`source`, `city_id`, `ds`, `gcs_path`, `error`, `errors[]`; max 20 violations, raw values omitted).
3. `AirflowFailException` is raised, which **skips retries:** re-running cannot fix bad data. (Transient problems such as network errors keep the normal retry with exponential backoff.)
4. Downstream load is `upstream_failed`.

## 4. Silver Layer Design

| Property | Value |
| --- | -------- |
| Primary key |	`(observed_at, city_id)` (composite, enforced by MERGE + pre-check) |
| Partitioning |	`DAY` on `observed_at` |
| Clustering |	`city_id` |
| Columns |	All `REQUIRED` (NOT NULL) + lineage: `source_file` (GCS path), `ingested_at` |
| Staging tables |	`_stg_<table>_<YYYYMMDD>`, auto-expire after `STAGING_TABLE_TTL_DAYS` (7) |

### 4.1 Load Flow (`load_bronze_to_silver_bq`)

1. Completeness check: all configured cities present, otherwise fail.
2. Read each validated Bronze file, re-validate and convert into flat typed rows (`to_silver_rows`).
3. `assert_unique_keys`: a duplicated key in the batch fails the task (BigQuery would reject the MERGE anyway).
4. Batch **load job** into the staging table with `WRITE_TRUNCATE` (free, unlike streaming inserts).
5. **MERGE** staging → Silver:
* `WHEN MATCHED` → `UPDATE` every non-key column;
* `WHEN NOT MATCHED` → `INSERT`.
The `ON` clause contains `T.observed_at BETWEEN <batch min> AND <batch max>`, so BigQuery only scans the partitions touched by the batch (partition pruning = lower cost).

### 4.2 Idempotency

| Scenario | Result |
| --- | --- |
| Same `ds` run 5 times |	Same row count; rows updated in place (only `ingested_at` changes) |
| Backfill of historical dates |	Each date touches only its own partition |
| Retry after a partial failure |	Staging is truncated and rebuilt; MERGE is re-applied safely |

## 5. How to verify

```sql
-- 1) No duplicates (must return 0 rows)
SELECT observed_at, city_id, COUNT(*) AS n
FROM `<project>.silver_trusted_dataset.silver_weather_hourly`
GROUP BY observed_at, city_id
HAVING n > 1;

-- 2) Expected volume: 3 cities x 24 hours per day
SELECT DATE(observed_at) AS day, COUNT(*) AS n
FROM `<project>.silver_trusted_dataset.silver_weather_hourly`
WHERE DATE(observed_at) >= DATE '2026-10-01'
GROUP BY day ORDER BY day;
```
Then trigger the same date twice (`airflow dags backfill` or *Clear* the run): the counts must not change.  

**Simulate a failure:** edit a Bronze JSON in GCS (e.g. set one `cloud_cover` to `null` or `150`) and re-run `validate_*`. Expected: task `failed` with no retries, `load_*` shown as `upstream_failed`, and a `validate_data_quality.failed` log entry listing the offending field.

## 6. Log Events (structured)

`validate_data_quality.start|success|failed` · `load_bronze_to_silver_bq.start|success|failed|incomplete_batch` (`success` includes `rows_in_batch` and `rows_affected`).

---

**Built by:** @camillefk  
**Created:** October 2026  
**Last Updated:** October 29, 2026