"""
HTTP clients for the project's external APIs.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Tuple

import requests

from utils.config import (
    OPENMETEO_ARCHIVE_URL,
    OPENMETEO_HOURLY_VARS,
    PVGIS_BASE_URL,
    PVGIS_MAX_YEAR,
    PVGIS_MIN_YEAR,
    REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

def fetch_openmeteo_daily(
        latitude: float,
        longitude: float,
        target_date: date,
        timezone: str = "Europe/Amsterdam",
) -> Tuple[Dict[str, Any], int]:
    """Fetches hourly weather/radiation data for a single day.
 
    Engineering note: The Open-Meteo archive-api endpoint has a
    data quality lag of a few days. For very recent `target_date`s,
    some hourly fields may return as `null` — this is expected and
    handled in the validation layer, not here.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "hourly": OPENMETEO_HOURLY_VARS,
        "timezone": timezone,
    }

    response = requests.get(
        OPENMETEO_ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    payload = response.json()

    record_count = len(payload.get("hourly", {}).get("time", []))
    return payload, record_count

def _resolve_pvgis_year(target_date: date) -> int:
    """Selects the year to query in the PVGIS time series.
 
    The PVGIS `seriescalc` series only covers PVGIS_MIN_YEAR–PVGIS_MAX_YEAR.
    For dates outside this range (e.g., runs on the current date, in the future
    relative to the dataset), we use the closest valid year as a meteorological
    proxy for the same month/day — a common practice when using historical
    irradiance databases to model expected solar generation.
    """
    if target_date.year > PVGIS_MAX_YEAR:
        return PVGIS_MAX_YEAR
    if target_date.year < PVGIS_MIN_YEAR:
        return PVGIS_MIN_YEAR
    return target_date.year

def fetch_pvgis_daily(
    latitude: float, longitude: float, target_date: date
) -> Tuple[Dict[str, Any], int]:
    """Fetches the hourly PVGIS irradiance/wind time series for a single day.
 
    Returns the payload filtered for the hours of the requested day, along
    with metadata indicating whether a proxy year was used (see
    `_resolve_pvgis_year`).
    """
    effective_year = _resolve_pvgis_year(target_date)
    is_proxy_year = effective_year != target_date.year
 
    params = {
        "lat": latitude,
        "lon": longitude,
        "startyear": effective_year,
        "endyear": effective_year,
        "components": 1,
        "outputformat": "json",
        "raddatabase": "PVGIS-ERA5"
    }
 
    response = requests.get(
        f"{PVGIS_BASE_URL}/seriescalc",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()
 
    target_prefix = f"{effective_year}{target_date.month:02d}{target_date.day:02d}"
    hourly = raw.get("outputs", {}).get("hourly", [])
    day_records = [r for r in hourly if r.get("time", "").startswith(target_prefix)]
 
    payload = {
        "inputs": raw.get("inputs", {}),
        "meta": raw.get("meta", {}),
        "outputs": {"hourly": day_records},
        "proxy_year_used": is_proxy_year,
        "effective_year": effective_year,
        "requested_date": target_date.isoformat(),
    }
    return payload, len(day_records)