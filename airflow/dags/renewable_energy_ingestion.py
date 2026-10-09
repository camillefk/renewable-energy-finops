"""
DAG: renewable_energy_ingestion

Daily idempotent ingestion of weather data (Open-Meteo) and
irradiance/wind data (PVGIS) to the Bronze Layer (GCS),
in strategic cities in the Netherlands: The Hague, Rotterdam, and Groningen/Eemshaven.

Task pattern (see docs/DEVELOPER_GUIDE.md for the complete rationale):

    fetch_weather_data  ─┐
                          ├─> upload_to_gcs_bronze (mapped by city)
    fetch_solar_data    ─┘

Both sources follow the same fetch -> upload pattern, dynamically
mapped (`.expand`) over the 3 cities, and reuse the SAME
`upload_to_gcs_bronze` task (via `.override(task_id=...)`) to avoid
duplicating upload logic.

"""

from __future__ import annotations
import logging
import os
from datetime import date, timedelta
from typing import Any, Dict

import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable

from utils.api_clients import fetch_openmeteo_daily, fetch_pvgis_daily
from utils.config import (
    CITIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY,
    GCS_BUCKET_DEFAULT,
    GCS_BUCKET_VARIABLE,
    LOCAL_STAGING_DIR,
)
from utils.gcs_utils import (
    build_bronze_blob_name,
    log_event,
    upload_file_to_gcs,
    write_local_staging_file,
)

logger = logging.getLogger(__name__)

default_args = {
    "owner": "data-engineering",
    "retries": DEFAULT_RETRIES,
    "retry_delay": DEFAULT_RETRY_DELAY,
    "retry_exponential_backoff": True,
    "max_retry_delay": DEFAULT_MAX_RETRY_DELAY,
}


@dag(
    dag_id="renewable_energy_ingestion",
    description="Ingest weather and irradiance/wind data to GCS Bronze Layer",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="Europe/Amsterdam"),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["bronze", "ingestion", "renewable-energy-finops"],
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

    weather_metadata = fetch_weather_data.expand(city=CITIES)
    upload_to_gcs_bronze.override(task_id="upload_weather_to_gcs_bronze").expand(
        metadata=weather_metadata
    )

    solar_metadata = fetch_solar_data.expand(city=CITIES)
    upload_to_gcs_bronze.override(task_id="upload_solar_to_gcs_bronze").expand(
        metadata=solar_metadata
    )

renewable_energy_ingestion()
