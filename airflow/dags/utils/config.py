"""
DAG configuration
"""

from datetime import timedelta

# Bronze Layer (GCS)
GCS_BUCKET_VARIABLE = "bronze_raw_data_bucket"
GCS_BUCKET_DEFAULT = "bronze-raw-data-bucket-peppy-coda-483817-b1"

LOCAL_STAGING_DIR = "/tmp/renewable_energy_bronze_staging"

# Cities
CITIES = [
    {"id": "the_hague", "name": "The Hague", "lat": 52.0705, "lon": 4.3007},
    {"id": "rotterdam", "name": "Rotterdam", "lat": 51.9225, "lon": 4.47917},
    {"id": "groningen_eemshaven", "name": "Groningen/Eemshaven", "lat": 53.2194, "lon": 6.5667},
]

# External API
OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_HOURLY_VARS = [
    "direct_radiation",
    "diffuse_radiation",
    "global_tilted_irradiance",
    "cloud_cover",
    "wind_speed_100m",
    "temperature_2m",
    "relative_humidity_2m",
]

PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_2"

# PVGIS time series (seriescalc) only covers this year range.
# Outside of it, i use the closest valid year as a proxy (see api_clients.py).
PVGIS_MIN_YEAR = 2005
PVGIS_MAX_YEAR = 2020

# Resilience
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = timedelta(minutes=5)
DEFAULT_MAX_RETRY_DELAY = timedelta(minutes=30)
REQUEST_TIMEOUT_SECONDS = 30
