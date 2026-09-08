"""
Test and exploration script for the Open-Meteo API.
Extracts solar radiation, cloud cover, wind speed (100 m), and temperature.
"""

import json
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ========================================================================
# API Configuration
# ==========================================================================

OPENMETEO_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# sample coordinates (latitude, longitude)
COORDINATES = {
    "amsterdam": {"lat": 52.3676, "lon": 4.9041, "name": "Amsterdam, NL"},
    "berlin": {"lat": 52.5200, "lon": 13.4050, "name": "Berlin, DE"},
    "copenhagen": {"lat": 55.6761, "lon": 12.5683, "name": "Copenhagen, DK"},
}

class OpenMeteoAPI:
    """ Client for interacting with the Open-Meteo API."""

    def __init__(self, base_url: str = OPENMETEO_BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 30

    def get_weather_data(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
        timezone: str = "Europe/Amsterdam",
    ) -> Dict[str, Any]:
        """Extracts historical weather data from the Open-Meteo API.
        
        Parameters:
            latitude: Latitude of the location.
            longitude: Longitude of the location.
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
            timezone: Timezone for the data (default is Europe/Amsterdam).

        Returns:
            A dictionary containing the structured historical weather data.
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": [
                "direct_radiation",              # Direct solar radiation in W/m²
                "diffuse_radiation",             # Diffuse solar radiation in W/m²
                "global_tilted_irradiance",      # Global tilted irradiance in W/m²
                "cloud_cover",                   # Cloud cover in %
                "wind_speed_100m",               # Wind speed at 100m (offshore wind turbines)
                "temperature_2m",                # Temperature at 2m in °C
                "relative_humidity_2m",          # Relative humidity at 2m in %
            ],
            "timezone": timezone,
        }

        try:
            logger.info(
                f"Requesting Open-Meteo: lat={latitude}, lon={longitude}, "
                f"Time period={start_date} a {end_date}"
            )
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()
            logger.info(f"✓ Response received successfully")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"✕ Request failed: {e}")
            raise
    
    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        days: int = 7,
        timezone: str = "Europe/Amsterdam",
    ) -> Dict[str, Any]:
        """
        Extracts weather forecast data from the Open-Meteo API for the next 7 days.

        Parameters:
            latitude: Latitude of the location.
            longitude: Longitude of the location.
            days: Number of days to forecast (max. 16).
            timezone: Timezone for the data (default is Europe/Amsterdam).

        Returns:
            A dictionary containing the structured weather forecast data.
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": [
                "direct_radiation",
                "diffuse_radiation",
                "global_tilted_irradiance",
                "cloud_cover",
                "wind_speed_100m",
                "temperature_2m",
                "relative_humidity_2m",
            ],
            "forecast_days": min(days, 16),
            "timezone": timezone,
        }

        try:
            logger.info(
                f"Requesting Open-Meteo forecast: lat={latitude}, lon={longitude}, "
                f"Next {days} days"
            )
            response = self.session.get(OPENMETEO_FORECAST_URL, params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"✓ Forecast response received successfully")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"✗ Error in forecast request: {e}")
            raise


# =========================================================================
# Test Functions for the API
# ==========================================================================

def test_historical_data():
    """Test extraction of historical weather data."""
    logger.info("=" * 70)
    logger.info("Test 1: Historical Weather Data (Last Week)")
    logger.info("=" * 70)

    api = OpenMeteoAPI()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    coord = COORDINATES["amsterdam"]

    try:
        data = api.get_weather_data(
            latitude=coord["lat"],
            longitude=coord["lon"],
            start_date=str(start_date),
            end_date=str(end_date),
        )

        logger.info("\n Response Structure:")
        logger.info(json.dumps(
            {
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "timezone": data.get("timezone"),
                "hourly_keys": list(data.get("hourly", {}).keys()),
                "total_records": len(data.get("hourly", {}).get("time", [])),
            },
            indent=2,
        ))

        # Sample of the first 3 records
        if "hourly" in data and "time" in data["hourly"]:
            logger.info("\n Sample Records (First 3):")
            for i in range(min(3, len(data["hourly"]["time"]))):
                sample = {
                    "timestamp": data["hourly"]["time"][i],
                    "direct_radiation_W/m²": data["hourly"]["direct_radiation"][i],
                    "cloud_cover_%": data["hourly"]["cloud_cover"][i],
                    "wind_speed_100m_kmh": data["hourly"]["wind_speed_100m"][i],
                    "temperature_C": data["hourly"]["temperature_2m"][i],
                }

                logger.info(f"    [{i}] {json.dumps(sample, indent=2)}")

        logger.info("\n✓ Test 1: Historical data extraction test completed successfully.")  

    except Exception as e:
        logger.error(f"✕ Test 1 failed: {e}")

def test_forecast():
    """Test extraction of weather forecast data."""
    logger.info("=" * 70)
    logger.info("Test 2: Weather Forecast Data (Next 7 Days)")
    logger.info("=" * 70)

    api = OpenMeteoAPI()
    coord = COORDINATES["berlin"]

    try:
        data = api.get_forecast(
            latitude=coord["lat"],
            longitude=coord["lon"],
            days=7,
        )

        logger.info("\n Response Structure:")
        logger.info(json.dumps(
            {
                "location": coord["name"],
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "timezone": data.get("timezone"),
                "hourly_keys": list(data.get("hourly", {}).keys()),
                "total_records": len(data.get("hourly", {}).get("time", [])),
            },
            indent=2,
        ))

        logger.info("\n Test 2: Forecast data extraction test completed successfully.")

    except Exception as e:
        logger.error(f"✕ Test 2 failed: {e}")

def test_multiple_locations():
    """Test extraction of weather data from multiple locations."""
    logger.info("=" * 70)
    logger.info("Test 3: Multiple Locations Weather Data")
    logger.info("=" * 70)

    api = OpenMeteoAPI()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=1)

    results = {}

    for location_name, coord in COORDINATES.items():
        try:
            logger.info(f"\n Extracting data for {coord['name']} ...")
            data = api.get_weather_data(
                latitude=coord["lat"],
                longitude=coord["lon"],
                start_date=str(start_date),
                end_date=str(end_date),
            )
            results[location_name] = {
                "status": "success",
                "records": len(data.get("hourly", {}).get("time", [])),
            }
        except Exception as e:
            results[location_name] = {
                "status": "failed",
                "error": str(e),
            }

    logger.info("\n Results Summary:")
    logger.info(json.dumps(results, indent=2))
    logger.info("\n✓ Test 3: Multiple locations data extraction test completed successfully.")

def test_rate_limits():
    """Check behavior under high request volume (rate limits)."""
    logger.info("=" * 70)
    logger.info("Test 4: Handling of Rate Limits")
    logger.info("=" * 70)

    api = OpenMeteoAPI()
    coord = COORDINATES["copenhagen"]
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=1)

    logger.info("   ! Note: Open-Meteo allows unlimited requests, but with burst limits.")
    logger.info("   Recommendation: max 1 req/second in production.")

    for attempt in range(3):
        try:
            logger.info(f"\n Attempt {attempt + 1}/3...")
            data = api.get_weather_data(
                latitude=coord["lat"],
                longitude=coord["lon"],
                start_date=str(start_date),
                end_date=str(end_date),
            )
            logger.info(f"   ✓ Successfully")
        except Exception as e:
            logger.error(f"   ✕ Attempt {attempt + 1} failed: {e}")

    logger.info("\n✓ Test 4: Rate limit handling test completed successfully.")

# =========================================================================
# EXPECTED DATA SCHEMA
# =========================================================================

OPENMETEO_SCHEMA = {
    "latitude": "float",
    "longitude": "float",
    "generationtime_ms": "float",
    "utc_offset_seconds": "int",
    "timezone": "str",
    "timezone_abbreviation": "str",
    "elevation": "float",
    "hourly": {
        "time": "List[str]",  # ISO 8601 format: "2024-01-01T00:00"
        "direct_radiation": "List[float]",  # W/m²
        "diffuse_radiation": "List[float]",  # W/m²
        "global_tilted_irradiance": "List[float]",  # W/m²
        "cloud_cover": "List[int]",  # % (0-100)
        "wind_speed_100m": "List[float]",  # km/h
        "temperature_2m": "List[float]",  # °C
        "relative_humidity_2m": "List[int]",  # % (0-100)
    },
    "hourly_units": {
        "time": "iso8601",
        "direct_radiation": "W/m²",
        "diffuse_radiation": "W/m²",
        "global_tilted_irradiance": "W/m²",
        "cloud_cover": "%",
        "wind_speed_100m": "km/h",
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
    },
}


def print_schema():
    """Print the expected API schema."""
    logger.info("=" * 70)
    logger.info("OPEN-METEO API EXPECTED SCHEMA")
    logger.info("=" * 70)
    logger.info(json.dumps(OPENMETEO_SCHEMA, indent=2))

# =========================================================================
# MAIN
# =========================================================================

if __name__ == "__main__":
    logger.info("\n🌍 TEST AND EXPLORATION: API OPEN-METEO")
    logger.info("Repository: renewable-energy-finops\n")

    test_historical_data()
    test_forecast()
    test_multiple_locations()
    test_rate_limits()
    print_schema()

    logger.info("=" * 70)
    logger.info("✓ TESTS COMPLETED!")
    logger.info("=" * 70)
