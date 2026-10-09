# Developer Guide: DAG Patterns & Idempotency

> Developer Guide for the `renewable_energy_ingestion` DAG. This document serves as the primary technical reference for understanding, maintaining, and extending the data ingestion architecture.

## 1. File Structure

```text
airflow/
└── dags/
    ├── renewable_energy_ingestion.py   # DAG definition (orchestration)
    └── utils/
        ├── config.py         # constants: cities, URLs, retry parameters
        ├── api_clients.py    # pure functions that call the external APIs
        └── gcs_utils.py      # GCS upload + structured logging
```

**Why split it this way?** Business logic (calling the API, building the blob name) lives in pure functions that can be tested with `pytest` without starting Airflow. The DAG (`renewable_energy_ingestion.py`) only orchestrates: it decides the order, the retries and what becomes an XCom.

## 2. Task Pattern (TaskFlow API)

I use `@dag` / `@task` (TaskFlow API) instead of the classic `PythonOperator`. It is the pattern currently recommended by Airflow, it reduces XCom boilerplate, and it lets type hints define each task's contract.

The original requirement describes the chain `fetch_weather_data → fetch_solar_data → upload_to_gcs_bronze`. In the implementation, this became **two parallel branches** that reuse the same upload task:

```text
fetch_weather_data (mapped per city) ─> upload_to_gcs_bronze (upload_weather_to_gcs_bronze)
fetch_solar_data   (mapped per city) ─> upload_to_gcs_bronze (upload_solar_to_gcs_bronze)
```

**Why not a single linear chain?** Weather and solar are independent sources - a PVGIS failure should not block the upload of weather data that was already fetched. Running both branches in parallel, each dynamically mapped (`.expand`) over the 3 cities, yields 12 task instances per run (2 sources ✕ 3 cities ✕ 2 tasks), all parallelizable and individually re-runnable. This is far more granular (and easier to debug) than a single monolithic task.

The same `upload_to_gcs_bronze` function is reused in both branches via `.override(task=id...)`, avoiding duplicated upload logic.

## 3. Idempotency Rule

Two guarantees, together, make the ingestion idempotent:

#### 1. Deterministic path
The blob name in GCS is always `f"{source}/{ds}/{city_id}.json"` (e.g. `open-meteo/2026-09-25/rotterdam.json`), built from the logical execution date (`{{ ds }}`) - never `datetime.now()`. Two runs for the same `ds` always resolve to the same blob.

#### 2. Native GCS overwrite
`blob.upload_from_filename()` overwrites the existing object by default. Since the Bronze bucket does not have Object Versioning enabled, versions do not accumulate - running the same date 5 times, or backfilling old dates, always ends with exactly the same final object.

Practical consequence: the DAG can run with `catchup=True` to populate history, or be re-run manually (`airflow tasks test` / "Clear") without worrying about duplicated or corrupted files.

## 4. XCom Rule

Never pass the raw API payload through XCom. It is stored in Airflow's metadata database (local Postgres), can easily exceed size limits, and clutters the UI. The fetch tasks:

1. Write the JSON to local disk
(`/tmp/renewable_energy_bronze_staging/<ds>/<source>/<city_id>.json`).
2. Return only metadata: `source`, `city_id`, `local_path`, `record_count`, `ds`.

The upload task reads the file from local disk, uploads it to GCS and then removes the local file (staging is ephemeral, per task instance).

## 5. Resilience

* `retries=3` with `retry_exponential_backoff=True` and `max_retry_delay=30min` in `default_args` — covers transient instability in the external APIs (Open-Meteo, PVGIS) without per-task configuration.

* The `google-cloud-storage` import happens inside the upload function (not at module level), so a DAG parsing environment without the library installed does not raise a `DAG import error` in the Scheduler.

## 6. Structured Logging

`utils.gcs_utils.log_event()` emits one JSON line per event (`fetch_weather_data.start`, `upload_to_gcs_bronze.success`, etc.), always including `city_id` and `ds`. This makes it easy to filter logs by city/date in Cloud Logging later without rewriting the tasks.

## 7. Known Limitations (documented on purpose)

* **Open-Meteo archive lag**: the `archive-api` endpoint takes a few days to consolidate quality data. Running the DAG for a very recent `ds` may return null hourly fields. This will be handled as validation (Pydantic, fail-fast).

* **PVGIS proxy year**: the PVGIS hourly series only covers 2005–2023. For a `ds` outside this range, we use the closest valid year as a meteorological proxy (same month/day), and flag `proxy_year_used=true` in the payload plus a `warning` log. This is a documented modeling choice, not a silent failure.

## 8. Troubleshooting and Issue Resolution (Local Development)

During the local development and testing of the `renewable_energy_ingestion` pipeline running on Docker, several infrastructure, compatibility, and configuration challenges were identified. Below is a log of the primary errors encountered and their respective structural solutions for future reference.

### 1. Web UI Blind to Logs (ConnectionPool socket_options)

* **Symptom:** Tasks remain indefinitely stuck in the Running state (light green). When forcing the task to fail in order to read the logs, the interface displays the error: 

```text
*** Could not read served logs: ConnectionPool.__init__() got an unexpected keyword argument 'socket_options'
```

* **Root Cause:** A version incompatibility within the Python ecosystem in the Docker image. The `requests` library conflicted with the `2.0.0` update of the `urllib3` library, breaking the Webserver's ability to fetch text log files from the Worker container.

* **Implemented Solution:**
1. Pinned the dependency in the project's `requirements.txt` file by adding the line `urllib3<2.0.0`.  

2. Rebuilt the Docker image without cache (`docker-compose build --no-cache`).  

3. Debugging workaround used: Read the worker logs directly via the Docker CLI (`docker logs renewable-airflow-worker`).

### 2. Authentication Failures with Workload Identity Federation (WIF)

* **Symptom**: The GCS upload task fails immediately with the error `IsADirectoryError: [Errno 21] Is a directory: '/airflow/gcp-key.json'` or, subsequently, with `Project was not passed and could not be determined from the environment.`

* **Root Cause**:
1. The `volumes` mount in `docker-compose.yml` attempted to map a local ADC (Application Default Credentials) file that did not exist yet. Docker's default behavior when a source file is missing is to create an empty directory at the destination path.

2. The ADC method impersonating a Service Account does not implicitly inject the `Project ID` into the environment variables, leaving the Python `google-cloud-storage` package without a destination reference.

* **Implemented Solution:**

1. The credential token was physically generated on the local machine, simulating the restricted Service Account created via Terraform:

```text
gcloud auth application-default login --impersonate-service-account=renewable-energy-sa@<PROJECT_ID>.iam.gserviceaccount.com
```

2. The resulting JSON file was moved to the project root as gcp-credentials.json and mapped directly into the Docker volumes.

3. The `GOOGLE_CLOUD_PROJECT` variable was explicitly declared under the `environment` section of the Airflow services in the `docker-compose.yml` file.

### 3. PVGIS API Rejection (HTTP 400 Bad Request)

* **Symptom:** The `fetch_solar_data` task fails with `requests.exceptions.HTTPError: 400 Client Error: BAD REQUEST.`

* **Root Cause:** The temporal limit of the European PVGIS API database (SARAH-2). The code attempted to make calls using `2023` as a proxy for the reference year, but the most recent consolidated data for the requested coordinates (Netherlands) is limited to the year 2020.

* **Implemented Solution:** The global temporal limit constant in the configuration layer (`utils/config.py`) was adjusted to accommodate the European database delay:

```text
PVGIS_MAX_YEAR = 2020
```

## 9. How to test locally

```bash
# Validate DAG syntax/imports without scheduling anything
docker compose exec airflow-scheduler airflow dags list-import-errors

# Run a single task for a specific date (does not affect the scheduler)
docker compose exec airflow-scheduler airflow tasks test renewable_energy_ingestion fetch_weather_data 2026-09-20 --map-index 0

# Test idempotency manually: run the same date twice and compare
# the object's hash in the Bronze bucket — it must be identical.
gsutil hash gs://<bucket>/open-meteo/2026-09-20/rotterdam.json

# Test a backfill over a date range
docker compose exec airflow-scheduler airflow dags backfill renewable_energy_ingestion -s 2026-09-15 -e 2026-09-18
```

---

**Built by:** @camillefk  
**Created:** October 2026  
**Last Updated:** October 08, 2026