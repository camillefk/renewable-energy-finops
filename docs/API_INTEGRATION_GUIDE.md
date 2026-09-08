# API Integration Guide

> This guide documents the two external APIs used in this project — **PVGIS** (solar irradiance) and **Open-Meteo** (weather data) — including expected JSON response schemas, rate limits, and known quirks discovered during integration testing.

Reference implementations: [`test_pvgis_api.py`](../examples/test_pvgis_api.py) and [`test_openmeteo_api.py`](../examples/test_openmeteo_api.py).

---

## 1. PVGIS API

**Provider:** European Commission, Joint Research Centre (JRC)
**Base URL:** `https://re.jrc.ec.europa.eu/api/v5_2`
**Client class:** `PVGISAPI` (`examples/test_pvgis_api.py`)
**Auth:** none required (free, non-commercial use)

*⚠️ The API base URL **must** include the version segment (`v5_2` or `v5_3`). The unversioned entry point (`https://re.jrc.ec.europa.eu/api`) is no longer available and returns `404` on every request.*

### 1.1 Endpoints used

| Tool | Endpoint | Client method | Purpose |
|---|---|---|---|
| Monthly radiation | `/MRcalc` | `get_monthly_pvgis(latitude, longitude, horirrad=True, optrad=True, selectrad=False, angle=30.0)` | Monthly solar irradiance, one or more years |
| Hourly radiation | `/seriescalc` | `get_hourly_pvgis(latitude, longitude, year, month, day)` | Hourly irradiance time series (filtered client-side to a single day) |
| Typical Meteorological Year | `/tmy` | `get_typical_meteorological_year(latitude, longitude, startyear=2007, endyear=2020)` | TMY hourly dataset |

### 1.2 Required parameters — `MRcalc`

`MRcalc` returns `HTTP 200` even when no radiation value is actually computed. At least one output flag must be set to `1`:

| Parameter | Effect |
|---|---|
| `horirrad=1` | Adds `H(h)_m` (horizontal irradiation) to each monthly record |
| `optrad=1` | Adds `H(i_opt)_m` (irradiation at optimal angle) |
| `selectrad=1` (+ `angle`) | Adds `H(i)_m` (irradiation at the given fixed angle) |

Without `startyear`/`endyear`, `MRcalc` returns **one record per year in the full available period** (2005–2020, i.e. ~16 years), not 12 months. Aggregating annual totals requires grouping by `year` first — see [Known Quirks](#4-known-quirks--gotchas).

### 1.3 JSON schema — Monthly (`MRcalc`)

```json
{
  "inputs": {
    "location": {
      "latitude": "float",
      "longitude": "float",
      "elevation": "float"
    },
    "meteo_data": "dict",
    "plane": "dict"
  },
  "outputs": {
    "monthly": [
      {
        "year": "int",
        "month": "int",
        "H(h)_m": "float",       // requires horirrad=1
        "H(i_opt)_m": "float",   // requires optrad=1
        "H(i)_m": "float",       // requires selectrad=1
        "Hb(n)_m": "float",      // requires mr_dni=1
        "Kd": "float",           // requires d2g=1
        "T2m": "float"           // requires avtemp=1
      }
    ]
  },
  "meta": {
    "inputs": "dict",
    "outputs": "dict"
  }
}
```

### 1.4 JSON schema — Hourly (`seriescalc`)

```json
{
  "inputs": {
    "location": {
      "latitude": "float",
      "longitude": "float",
      "elevation": "float"
    },
    "meteo_data": "dict"
  },
  "outputs": {
    "hourly": [
      {
        "time": "str",       // format "YYYYMMDD:HHMM" (UTC)
        "P": "float",        // PV power output in W, only if pvcalculation=1
        "G(i)": "float",     // global irradiance on plane (W/m²), only if components != 1
        "Gb(i)": "float",    // direct (beam) irradiance on plane (W/m²), only if components=1
        "Gd(i)": "float",    // diffuse irradiance on plane (W/m²), only if components=1
        "Gr(i)": "float",    // reflected irradiance on plane (W/m²), only if components=1
        "H_sun": "float",    // solar elevation angle (degrees)
        "T2m": "float",      // air temperature at 2m (°C)
        "WS10m": "float",    // wind speed at 10m (m/s)
        "Int": "int"         // 1 if the value was reconstructed/interpolated, else 0
      }
    ]
  },
  "meta": {
    "inputs": "dict",
    "outputs": "dict"
  }
}
```

Note: `seriescalc` has no single-day filter — it always returns the full hourly series between `startyear` and `endyear`. The client filters the target day locally by matching the `YYYYMMDD` prefix of `time`.

### 1.5 JSON schema — TMY (`tmy`)

```json
{
  "inputs": {
    "location": {
      "latitude": "float",
      "longitude": "float",
      "elevation": "float"
    },
    "meteo_data": "dict"
  },
  "outputs": {
    "months_selected": [
      { "month": "int", "year": "int" }
    ],
    "tmy_hourly": [
      {
        "time(UTC)": "str",  // format "YYYYMMDD:HHMM" — NOTE: not "time", see quirks below
        "T2m": "float",      // air temperature at 2m (°C)
        "RH": "float",       // relative humidity (%)
        "G(h)": "float",     // global horizontal irradiance (W/m²)
        "Gb(n)": "float",    // direct normal irradiance (W/m²)
        "Gd(h)": "float",    // diffuse horizontal irradiance (W/m²)
        "IR(h)": "float",    // downward infrared radiation (W/m²)
        "WS10m": "float",    // wind speed at 10m (m/s)
        "WD10m": "float",    // wind direction at 10m (degrees)
        "SP": "float"        // atmospheric pressure (Pa)
      }
    ]
  },
  "meta": {
    "inputs": "dict",
    "outputs": "dict"
  }
}
```

### 1.6 Rate limits

| Limit | Value |
|---|---|
| Requests per second | 30 per IP (documented) |
| Over limit | `HTTP 429` (too many requests) |
| Server overloaded | `HTTP 529` — retry later |
| Commercial use | Free for non-commercial use |

---

## 2. Open-Meteo API

**Provider:** Open-Meteo
**Base URLs:**
- Historical: `https://archive-api.open-meteo.com/v1/archive`
- Forecast: `https://api.open-meteo.com/v1/forecast`

**Client class:** `OpenMeteoAPI` (`examples/test_openmeteo_api.py`)
**Auth:** none required for the free tier

### 2.1 Methods

| Method | Endpoint | Purpose |
|---|---|---|
| `get_weather_data(latitude, longitude, start_date, end_date, timezone="Europe/Amsterdam")` | `/v1/archive` | Historical hourly weather data for a date range |
| `get_forecast(latitude, longitude, days=7, timezone="Europe/Amsterdam")` | `/v1/forecast` | Forecast hourly weather data, up to 16 days |

Both request the same `hourly` variable set:
`direct_radiation`, `diffuse_radiation`, `global_tilted_irradiance`, `cloud_cover`, `wind_speed_100m`, `temperature_2m`, `relative_humidity_2m`.

### 2.2 JSON schema

```json
{
  "latitude": "float",
  "longitude": "float",
  "generationtime_ms": "float",
  "utc_offset_seconds": "int",
  "timezone": "str",
  "timezone_abbreviation": "str",
  "elevation": "float",
  "hourly": {
    "time": "List[str]",                      // ISO 8601, e.g. "2024-01-01T00:00"
    "direct_radiation": "List[float]",        // W/m²
    "diffuse_radiation": "List[float]",       // W/m²
    "global_tilted_irradiance": "List[float]",// W/m²
    "cloud_cover": "List[int]",               // % (0-100)
    "wind_speed_100m": "List[float]",         // km/h
    "temperature_2m": "List[float]",          // °C
    "relative_humidity_2m": "List[int]"       // % (0-100)
  },
  "hourly_units": {
    "time": "iso8601",
    "direct_radiation": "W/m²",
    "diffuse_radiation": "W/m²",
    "global_tilted_irradiance": "W/m²",
    "cloud_cover": "%",
    "wind_speed_100m": "km/h",
    "temperature_2m": "°C",
    "relative_humidity_2m": "%"
  }
}
```

### 2.3 Rate limits

| Limit | Value |
|---|---|
| Hard rate limit | None documented for the free tier |
| Recommended pace | Max ~1 request/second in production |
| Behavior under burst | Burst limits apply; back off and retry on errors |
| Commercial use | Free tier for non-commercial use; commercial plans available |

---

## 3. Comparison at a glance

| | PVGIS | Open-Meteo |
|---|---|---|
| Data type | Solar irradiance, PV modeling | General weather + radiation |
| Coverage | Historical only (2005–2020 typical) | Historical + forecast (up to 16 days) |
| Geographic coordinates | Returns exact elevation for requested point | Snaps to nearest grid point (returned lat/lon may differ slightly from request) |
| Response time (observed) | ~1.5–5.5s per request | <1–2s per request |
| Auth | None | None (free tier) |

---

## 4. Known Quirks & Gotchas

These were discovered during integration testing and are **not** documented clearly (or at all) in the official PVGIS docs:

1. **`MRcalc` needs an explicit output flag.** A request with no `horirrad`/`optrad`/`selectrad` returns `HTTP 200` with an empty `monthly` table — no error is raised, so this fails silently.
2. **`MRcalc` returns multi-year data by default.** Without `startyear`/`endyear`, the response includes one record per year for the entire available period (~16 years), not a single 12-month year. Summing `H(h)_m` directly overstates "annual" totals by the number of years included — group by `year` and average instead.
3. **`tmy` hourly timestamp key is `"time(UTC)"`, not `"time"`.** The public documentation examples show `"time"`, but the live `v5_2` API returns the timestamp under `"time(UTC)"`. Code should read `record.get("time(UTC)")` (with a fallback to `"time"` for safety).
4. **`seriescalc` has no single-day filter.** It always returns the full hourly series for the requested year range; filtering to one day must be done client-side after the request.
5. **Open-Meteo snaps to its internal grid.** The `latitude`/`longitude` in the response can differ slightly (a few km) from the requested coordinates — this is expected behavior, not a bug.

---

**Built by:** @camillefk  
**Created:** August 2026  
**Last Updated:** September 08, 2026