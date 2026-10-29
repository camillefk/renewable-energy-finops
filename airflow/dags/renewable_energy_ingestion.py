"""
DAG: renewable_energy_ingestion

Idempotent daily ingestion of weather data (Open-Meteo) and solar irradiance/wind data (PVGIS) into the Bronze Layer (GCS) for the Netherlands' strategic cities: The Hague, Rotterdam and Groningen/Eemshaven. With a blocking data quality gate and the load into the Silver Layer (BigQuery).

Task pattern (see docs/DEVELOPER_GUIDE.md for the complete rationale):

    fetch (per city) -> upload_to_gcs_bronze (per city)
                     -> validate_data_quality (per city, Pydantic, fail-fast)
                     -> load_bronze_to_silver_bq (one MERGE per source)

Both sources follow the same pattern, dynamically mapped (`.expand`) over the 3 cities, and reuse the SAME `upload_to_gcs_bronze` and `validate_data_quality` tasks (via `override(task_id=...)`), so no logic is duplicated.

If ANY city fails validation, the load for that source is skipped (upstream_failed): nothing partial reaches BigQuery.
See docs/DATA_QUALITY_FRAMEWORK.md.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta, datetime
from typing import Any, Dict

import pendulum
from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.models import Variable

from utils.api_clients import fetch_openmeteo_daily, fetch_pvgis_daily
from utils.bigquery_utils import (
    ensure_silver_table,
    get_client,
    load_rows_to_staging,
    run_merge,
)
from utils.config import (
    CITIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY,
    GCS_BUCKET_DEFAULT,
    GCS_BUCKET_VARIABLE,
    LOCAL_STAGING_DIR,
)
from utils.errors import DataQualityError
from utils.gcs_utils import (
    build_bronze_blob_name,
    download_json_from_gcs,
    log_event,
    upload_file_to_gcs,
    write_local_staging_file,
)
from utils.schemas import validate_payload
from utils.silver import (
    SOURCE_TABLES,
    SILVER_SCHEMAS,
    assert_unique_keys,
    build_merge_sql,
    rows_time_window,
    staging_table_name,
    to_silver_rows,
)

logger = logging.getLogger(__name__)


def _fail_fast(event: str, exc: DataQualityError, **context: Any) -> None:
    """Log the quality failure as structured data, then fail the task WITHOUT retries.

    AirflowFailException skips `retries`: re-running cannot fix bad data.
    """
    log_event(
        logger, event, level="error", error=str(exc), errors=exc.errors, **context
    )
    raise AirflowFailException(f"{event}: {exc}") from exc


default_args = {
    "owner": "data-engineering",
    "retries": DEFAULT_RETRIES,
    "retry_delay": DEFAULT_RETRY_DELAY,
    "retry_exponential_backoff": True,
    "max_retry_delay": DEFAULT_MAX_RETRY_DELAY,
}


@dag(
    dag_id="renewable_energy_ingestion",
    description="Ingest weather and irradiance/wind data to GCS Bronze Layer, with a quality gate and a MERGE load into the Silver layer (Bigquery).",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="Europe/Amsterdam"),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["bronze", "silver", "ingestion", "renewable-energy-finops"],
)
def renewable_energy_ingestion():
    @task
    def fetch_weather_data(city: Dict[str, Any], ds: str = None) -> Dict[str, Any]:
        """Fetch weather/radiation data from Open-Meteo for a city and save it to local staging."""
        target_date = date.fromisoformat(ds)
        log_event(logger, "fetch_weather_data.start", city_id=city["id"], ds=ds)

        payload, record_count = fetch_openmeteo_daily(
            latitude=city["lat"], longitude=city["lon"], target_date=target_date
        )

        local_dir = os.path.join(LOCAL_STAGING_DIR, ds, "open-meteo")
        local_path = write_local_staging_file(local_dir, f"{city['id']}.json", payload)

        log_event(
            logger,
            "fetch_weather_data.success",
            city_id=city["id"],
            ds=ds,
            records=record_count,
        )
        return {
            "source": "open-meteo",
            "city_id": city["id"],
            "city_name": city["name"],
            "local_path": local_path,
            "record_count": record_count,
            "ds": ds,
        }

    @task
    def fetch_solar_data(city: Dict[str, Any], ds: str = None) -> Dict[str, Any]:
        """Fetch irradiance/wind data from PVGIS for a city and save it to local staging."""
        target_date = date.fromisoformat(ds)
        log_event(logger, "fetch_solar_data.start", city_id=city["id"], ds=ds)

        payload, record_count = fetch_pvgis_daily(
            latitude=city["lat"], longitude=city["lon"], target_date=target_date
        )
        if payload.get("proxy_year_used"):
            log_event(
                logger,
                "fetch_solar_data.proxy_year_used",
                level="warning",
                city_id=city["id"],
                requested_date=ds,
                effective_year=payload["effective_year"],
            )
        local_dir = os.path.join(LOCAL_STAGING_DIR, ds, "pvgis")
        local_path = write_local_staging_file(local_dir, f"{city['id']}.json", payload)

        log_event(
            logger,
            "fetch_solar_data.success",
            city_id=city["id"],
            ds=ds,
            records=record_count,
        )
        return {
            "source": "pvgis",
            "city_id": city["id"],
            "city_name": city["name"],
            "local_path": local_path,
            "record_count": record_count,
            "ds": ds,
        }

    @task
    def upload_to_gcs_bronze(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upload the JSON from local staging to GCS Bronze, with idempotent overwrite."""
        bucket_name = Variable.get(GCS_BUCKET_VARIABLE, default_var=GCS_BUCKET_DEFAULT)
        blob_name = build_bronze_blob_name(
            source=metadata["source"], ds=metadata["ds"], city_id=metadata["city_id"]
        )
        log_event(
            logger,
            "upload_to_gcs_bronze.start",
            bucket=bucket_name,
            blob_name=blob_name,
        )
        gcs_path = upload_file_to_gcs(
            bucket_name=bucket_name,
            blob_name=blob_name,
            local_path=metadata["local_path"],
        )

        os.remove(metadata["local_path"])  # clean up local staging file

        log_event(
            logger,
            "upload_to_gcs_bronze.success",
            gcs_path=gcs_path,
            record_count=metadata["record_count"],
        )

        return {
            "gcs_path": gcs_path,
            "record_count": metadata["record_count"],
            "source": metadata["source"],
            "city_id": metadata["city_id"],
        }

    @task
    def validate_data_quality(
        metadata: Dict[str, Any], ds: str = None
    ) -> Dict[str, Any]:
        """Quality gate: validate ONE Bronze file (schema, nulls, ranges, dates). Fail-fast."""
        gcs_path, source, city_id = (
            metadata["gcs_path"],
            metadata["source"],
            metadata["city_id"],
        )
        log_event(
            logger,
            "validate_data_quality.start",
            source=source,
            city_id=city_id,
            gcs_path=gcs_path,
        )

        payload = download_json_from_gcs(gcs_path)
        try:
            model = validate_payload(
                source=source, payload=payload, ds=ds, city_id=city_id
            )
        except DataQualityError as exc:
            _fail_fast(
                "validate_data_quality.failed",
                exc,
                source=source,
                city_id=city_id,
                ds=ds,
                gcs_path=gcs_path,
            )

        log_event(
            logger,
            "validate_data_quality.success",
            source=source,
            city_id=city_id,
            ds=ds,
            records=model.record_count,
        )
        return {
            "gcs_path": gcs_path,
            "source": source,
            "city_id": city_id,
            "record_count": model.record_count,
        }

    @task
    def load_bronze_to_silver_bq(
        validated: list, source: str, ds: str = None
    ) -> Dict[str, Any]:
        """Load all validated files of ONE source into Silver layer with a MERGE (UPSERT).

        Flow: read validated files -> flat typed rows -> staging table (batch load job, WRITE_TRUNCATE) -> MERGE on (observed_at, city_id). Reruns update, never duplicate.
        """
        validated = list(validated)  # mapped XCom arrives as a lazy sequence
        expected_cities = {city["id"] for city in CITIES}
        received_cities = {item["city_id"] for item in validated}
        if received_cities != expected_cities:
            raise AirflowFailException(
                f"load_bronze_to_silver_bq.incomplete_batch: expected {sorted(expected_cities)},"
                f"got {sorted(received_cities)}"
            )

        log_event(
            logger,
            "load_bronze_to_silver_bq.start",
            source=source,
            ds=ds,
            files=len(validated),
        )

        # 1) bronze (gcs)
        rows: list = []
        try:
            for item in validated:
                payload = download_json_from_gcs(item["gcs_path"])
                rows.extend(
                    to_silver_rows(
                        source=source,
                        payload=payload,
                        ds=ds,
                        city_id=item["city_id"],
                        gcs_path=item["gcs_path"],
                    )
                )
            assert_unique_keys(rows)
        except DataQualityError as exc:
            _fail_fast("load_bronze_to_silver_bq.failed", exc, source=source, ds=ds)

        # 2) rows -> self-expiring staging table (batch load job)
        dataset = "silver_trusted_dataset"
        schema_def = SILVER_SCHEMAS[source]

        client = get_client()
        target_fqn = ensure_silver_table(
            client, dataset, SOURCE_TABLES[source], schema_def
        )
        staging_fqn = load_rows_to_staging(
            client,
            dataset,
            staging_table_name(source, ds),
            rows,
            schema_def,
            ttl_days=1,
        )

        # 3) staging -> silver with MERGE (UPSERT) on (observed_at, city_id)
        sql = build_merge_sql(target_fqn, staging_fqn, source, rows_time_window(rows))
        affected = run_merge(client, sql)

        log_event(
            logger,
            "load_bronze_to_silver_bq.success",
            source=source,
            ds=ds,
            target=target_fqn,
            staging=staging_fqn,
            rows_in_batch=len(rows),
            rows_affected=affected,
        )
        return {
            "source": source,
            "target": target_fqn,
            "rows_in_batch": len(rows),
            "rows_affected": affected,
        }

    # --- OpenMeteo ------------------------------- #

    weather_metadata = fetch_weather_data.expand(city=CITIES)
    weather_bronze = upload_to_gcs_bronze.override(
        task_id="upload_weather_to_gcs_bronze"
    ).expand(metadata=weather_metadata)
    weather_validated = validate_data_quality.override(
        task_id="validate_weather_data_quality"
    ).expand(metadata=weather_bronze)
    load_bronze_to_silver_bq.override(task_id="load_weather_to_silver_bq")(
        validated=weather_validated, source="open-meteo"
    )

    # --- PVGIS ----------------------------------- #

    solar_metadata = fetch_solar_data.expand(city=CITIES)

    solar_bronze = upload_to_gcs_bronze.override(
        task_id="upload_solar_to_gcs_bronze"
    ).expand(metadata=solar_metadata)

    solar_validated = validate_data_quality.override(
        task_id="validate_solar_data_quality"
    ).expand(metadata=solar_bronze)

    load_bronze_to_silver_bq.override(task_id="load_solar_to_silver_bq")(
        validated=solar_validated, source="pvgis"
    )


renewable_energy_ingestion()
