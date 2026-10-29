"""Pydantic data contracts for the Bronze layer payloads.

Two validation levels, both blocking:
1. Schema level (Pydantic): types, nulls, physical ranges, equal series lengths.
2. Business-rule level (`check_business_rules`): right date, expected number of hourly records, no duplicated timestamps, coordinates inside the Netherlands.

Any violation raises`DataQualityError` (see `validate_payload`). 
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Dict, List, Type

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from utils.errors import DataQualityError

EXPECTED_HOURLY_RECORDS = 24
NL_LAT_RANGE = (50.5, 53.7)
NL_LON_RANGE = (3.2, 7.3)
MAX_REPORTED_ERRORS = 20
PVGIS_MIN_YEAR = 2005

# --- Strictly typed, range-checked numeric building blocks -----------------------------------------#
def _require_number(value: Any) -> float:
    """Reject null, strings and booleans: only real JSON numbers are accepted."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number (null, string and bool are not allowed)")
    return float(value)

def _require_str(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be an ISO-8601 string")
    return value

def _bounded(low: float, high: float):
    return Annotated[
        float,
        BeforeValidator(_require_number),
        Field(ge=low, le=high, allow_inf_nan=False),
    ]
 
TemperatureC = _bounded(-50.0, 50.0)
RadiationWm2 = _bounded(0.0, 1400.0)
CloudCoverPct = _bounded(0.0, 100.0)
WindSpeedKmh = _bounded(0.0, 200.0)  # Open-Meteo default unit: km/h
WindSpeedMs = _bounded(0.0, 60.0)  # PVGIS unit: m/s
SunHeightDeg = _bounded(-90.0, 90.0)
Latitude = _bounded(-90.0, 90.0)
Longitude = _bounded(-180.0, 180.0)
IsoTimestamp = Annotated[datetime, BeforeValidator(_require_str)]

def _coordinate_issues(lat: float, lon: float) -> List[str]:
    issues: List[str] = []
    if not NL_LAT_RANGE[0] <= lat <= NL_LAT_RANGE[1]:
        issues.append(f"latitude {lat} outside the Netherlands bounding box {NL_LAT_RANGE}")
    if not NL_LON_RANGE[0] <= lon <= NL_LON_RANGE[1]:
        issues.append(f"longitude {lon} outside the Netherlands bounding box {NL_LON_RANGE}")
    return issues

# --- Open-Meteo ---------------------------------------------- #
class OpenMeteoHourly(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: List[IsoTimestamp] = Field(min_length=1)
    temperature_2m: List[TemperatureC]
    shortwave_radiation: List[RadiationWm2]
    cloud_cover: List[CloudCoverPct]
    wind_speed_100m: List[WindSpeedKmh]

    @model_validator(mode="after")
    def _series_have_equal_length(self) -> "OpenMeteoHourly":
        lengths = {
            name: len(getattr(self, name))
            for name in (
                "time",
                "temperature_2m",
                "shortwave_radiation",
                "cloud_cover",
                "wind_speed_100m",
            )
        }
        if len(set(lengths.values())) != 1:
            raise ValueError(f"hourly series have different lengths: {lengths}")
        return self

class OpenMeteoPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latitude: Latitude
    longitude: Longitude
    hourly: OpenMeteoHourly

    @property
    def record_count(self) -> int:
        return len(self.hourly.time)

    def check_business_rules(self, ds: str) -> List[str]:
        target = date.fromisoformat(ds)
        times = self.hourly.time
        issues: List[str] = []

        if len(times) != EXPECTED_HOURLY_RECORDS:
            issues.append(f"expected {EXPECTED_HOURLY_RECORDS} hourly records, got {len(times)}")
        off_date = sorted({t.date().isoformat() for t in times if t.date() != target})
        if off_date:
            issues.append(f"timestamps outside the target date {ds}: {off_date}")
        if len(set(times)) != len(times):
            issues.append("duplicated timestamps in hourly series")
        issues.extend(_coordinate_issues(self.latitude, self.longitude))
        return issues

# --- PVGIS ---------------------------------------------- #
class PvgisHourlyRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    time: datetime
    global_irradiance_wm2: RadiationWm2 = Field(alias="G(i)")
    sun_height_deg: SunHeightDeg = Field(alias="H_sun")
    temperature_2m_c: TemperatureC = Field(alias="T2m")
    wind_speed_10m_ms: WindSpeedMs = Field(alias="WS10m")

    @field_validator("time", mode="before")
    @classmethod
    def _parse_pvgis_time(cls, value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("must be a string like 'YYYYMMDD:HHMM'")
        return datetime.strptime(value, "%Y%m%d:%H%M")

class PvgisOutputs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hourly: List[PvgisHourlyRecord] = Field(min_length=1)

class PvgisPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proxy_year_used: bool
    effective_year: int
    outputs: PvgisOutputs

    @property
    def record_count(self) -> int:
        return len(self.outputs.hourly)

    def check_business_rules(self, ds: str) -> List[str]:
        target = date.fromisoformat(ds)
        records = self.outputs.hourly
        issues: List[str] = []
        current_year = datetime.now(timezone.utc).year

        if len(records) != EXPECTED_HOURLY_RECORDS:
            issues.append(f"expected {EXPECTED_HOURLY_RECORDS} hourly records, got {len(records)}")
        if not PVGIS_MIN_YEAR <= self.effective_year <= current_year:
            issues.append(f"effective_year {self.effective_year} outside [{PVGIS_MIN_YEAR}, {current_year}]")
        if not self.proxy_year_used and self.effective_year != target.year:
            issues.append("proxy_year_used is false but effective_year differs from the requested year")

        wrong_day = sorted(
            {r.time.strftime("%m-%d") for r in records if (r.time.month, r.time.day) != (target.month, target.day)}
        )
        if wrong_day:
            issues.append(f"records outside the requested month/day {target.strftime('%m-%d')}: {wrong_day}")
        wrong_year = sorted({r.time.year for r in records if r.time.year != self.effective_year})
        if wrong_year:
            issues.append(f"records whose year differs from effective_year {self.effective_year}: {wrong_year}")
        if len({r.time.hour for r in records}) != len(records):
            issues.append("duplicated hours in hourly series")
        return issues

# --- public entry point ------------------------------------------- #

SOURCE_MODELS: Dict[str, Type[BaseModel]] = {
    "open-meteo": OpenMeteoPayload,
    "pvgis": PvgisPayload,
} 

def _format_errors(exc: ValidationError) -> List[Dict[str, str]]:
    """Compact, log-friendly view of a Pydantic error (raw inputs are omitted)."""
    return [
        {"loc": ".".join(str(p) for p in err["loc"]), "msg": err["msg"], "type": err["type"]}
        for err in exc.errors()[:MAX_REPORTED_ERRORS]
    ]

def validate_payload(source: str, payload: Any, ds: str, city_id: str):
    """Validate one Bronze payload. Returns the typed model or raises DataQualityError."""
    model_cls = SOURCE_MODELS.get(source)
    if model_cls is None:
        raise DataQualityError(f"unknown source '{source}'", errors=[{"source": source}])

    try:
        model = model_cls.model_validate(payload)
    except ValidationError as exc:
        raise DataQualityError(
            f"[{source}/{city_id}] {exc.error_count()} schema violation(s)",
            errors=_format_errors(exc),
        ) from exc
 
    issues = model.check_business_rules(ds)
    if issues:
        raise DataQualityError(
            f"[{source}/{city_id}] {len(issues)} business rule violation(s)",
            errors=issues,
        )
    return model