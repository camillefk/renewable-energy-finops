"""Silver layer logic: schemas, Bronze -> typed rows, key checks and MERGE SQL.

Everything here is unit-testable.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.errors import DataQualityError
from utils.schemas import validate_payload

# Compositive primary key of every silver table
KEY_COLUMNS: Tuple[str, ...] = ("observed_at", "city_id")

# source -> silver table
SOURCE_TABLES: Dict[str, str] = {
    "open-meteo": "silver_weather_hourly",
    "pvgis": "silver_solar_hourly",
}

# source -> [(column, BigQuery type)]. All columns are REQUIRED (NOT NULL).
SILVER_SCHEMAS: Dict[str, List[Tuple[str, str]]] = {
    "open-meteo": [
        ("observed_at", "TIMESTAMP"),
        ("city_id", "STRING"),
        ("temperature_2m_c", "FLOAT64"),
        ("shortwave_radiation_wm2", "FLOAT64"),
        ("cloud_cover_pct", "FLOAT64"),
        ("wind_speed_100m_kmh", "FLOAT64"),
        ("source_file", "STRING"),
        ("ingested_at", "TIMESTAMP"),
    ],
    "pvgis": [
        ("observed_at", "TIMESTAMP"),
        ("city_id", "STRING"),
        ("global_irradiance_wm2", "FLOAT64"),
        ("sun_height_deg", "FLOAT64"),
        ("temperature_2m_c", "FLOAT64"),
        ("wind_speed_10m_ms", "FLOAT64"),
        ("source_year", "INT64"),
        ("is_proxy_year", "BOOL"),
        ("source_file", "STRING"),
        ("ingested_at", "TIMESTAMP"),
    ],
}
 
 
def _iso_utc(value: datetime) -> str:
    """Format as a BigQuery-friendly UTC timestamp. Naive datetimes are treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def staging_table_name(source: str, ds: str) -> str:
    """Deterministic staging table per (source, ds): reruns overwrite it (WRITE_TRUNCATE)."""
    return f"_stg_{SOURCE_TABLES[source]}_{ds.replace('-', '')}"

def to_silver_rows(
    source: str,
    payload: Dict[str, Any],
    ds: str,
    city_id: str,
    gcs_path: str,
    ingested_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Convert ONE Bronze payload into flat, typed Silver rows.
 
    The payload is validated again (cheap) so this function can never emit rows
    that violate the contract, even if called outside the quality gate.
    """
    model = validate_payload(source=source, payload=payload, ds=ds, city_id=city_id)
    ingested = _iso_utc(ingested_at or datetime.now(timezone.utc))
    target = date.fromisoformat(ds)
    rows: List[Dict[str, Any]] = []

    if source == "open-meteo":
        h = model.hourly
        for i, ts in enumerate(h.time):
            rows.append(
                {
                    "observed_at": _iso_utc(ts),
                    "city_id": city_id,
                    "temperature_2m_c": h.temperature_2m[i],
                    "shortwave_radiation_wm2": h.shortwave_radiation[i],
                    "cloud_cover_pct": h.cloud_cover[i],
                    "wind_speed_100m_kmh": h.wind_speed_100m[i],
                    "source_file": gcs_path,
                    "ingested_at": ingested,
                }
            )
    elif source == "pvgis":
        for rec in model.outputs.hourly:
            # PVGIS may serve a proxy year: observed_at is anchored on the REQUESTED
            # date so both sources share the same (observed_at, city_id) grain.
            observed_at = datetime.combine(target, time(hour=rec.time.hour))
            rows.append(
                {
                    "observed_at": _iso_utc(observed_at),
                    "city_id": city_id,
                    "global_irradiance_wm2": rec.global_irradiance_wm2,
                    "sun_height_deg": rec.sun_height_deg,
                    "temperature_2m_c": rec.temperature_2m_c,
                    "wind_speed_10m_ms": rec.wind_speed_10m_ms,
                    "source_year": model.effective_year,
                    "is_proxy_year": model.proxy_year_used,
                    "source_file": gcs_path,
                    "ingested_at": ingested,
                }
            )
    else:
        raise DataQualityError(f"unknown source '{source}'", errors=[{"source": source}])
    return rows

def assert_unique_keys(rows: List[Dict[str, Any]]) -> None:
    """MERGE fails if one target row matches several source rows: catch it earlier."""
    counts = Counter(tuple(row[k] for k in KEY_COLUMNS) for row in rows)
    duplicates = [{"key": list(k), "count": c} for k, c in counts.items() if c > 1]
    if duplicates:
        raise DataQualityError(
            f"{len(duplicates)} duplicated key(s) {KEY_COLUMNS} in the batch",
            errors=duplicates[:20],
        )

def rows_time_window(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(min, max) observed_at of the batch. Used to prune partitions in the MERGE."""
    values = [row["observed_at"] for row in rows]  # ISO strings sort chronologically
    return min(values), max(values)

def build_merge_sql(
    target_fqn: str,
    staging_fqn: str,
    source: str,
    window: Tuple[str, str],
) -> str:
    """MERGE (UPSERT) staging -> Silver on the composite key (observed_at, city_id).
 
    The BETWEEN predicate in the ON clause restricts the scan of the target table
    to the partitions touched by the batch (FinOps: bytes read stay constant as the
    table grows).
    """
    columns = [name for name, _ in SILVER_SCHEMAS[source]]
    non_key = [c for c in columns if c not in KEY_COLUMNS]
 
    on_clause = " AND ".join(f"T.{k} = S.{k}" for k in KEY_COLUMNS)
    update_set = ",\n    ".join(f"{c} = S.{c}" for c in non_key)
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join(f"S.{c}" for c in columns)
    low, high = window
 
    return f"""
MERGE `{target_fqn}` AS T
USING `{staging_fqn}` AS S
ON {on_clause}
   AND T.observed_at BETWEEN TIMESTAMP('{low}') AND TIMESTAMP('{high}')
WHEN MATCHED THEN
  UPDATE SET
    {update_set}
WHEN NOT MATCHED THEN
  INSERT ({insert_cols})
  VALUES ({insert_vals})
""".strip()
