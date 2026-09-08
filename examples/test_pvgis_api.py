"""
Test and exploration script for the PVGIS API (Photovoltaic Geographical Information System).
Extracts solar irradiance data and related weather data.

PVGIS is maintained by the European Commission (Joint Research Centre).
"""

import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================================================
# API Configuration
# ========================================================================

PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_2"

# sample coordinates: location with historical solar data
COORDINATES = {
    "netherlands_north": {"lat": 52.5, "lon": 5.5, "name": "Netherlands (North)"},
    "germany_south": {"lat": 48.0, "lon": 11.5, "name": "Germany (South)"},
    "spain_madrid": {"lat": 40.4, "lon": -3.7, "name": "Madrid, Spain"},
    "portugal_south": {"lat": 37.0, "lon": -7.9, "name": "Algarve, Portugal"},
}

class PVGISAPI:
    """ Client for interacting with the PVGIS API."""

    def __init__(self, base_url: str = PVGIS_BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 30

    def get_monthly_pvgis(
        self,
        latitude: float,
        longitude: float,
        horirrad: bool = True,
        optrad: bool = True,
        selectrad: bool = False,
        angle: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Extracts monthly solar irradiance data.

        MRcalc requires at least one output option to be selected
        (horirrad, optrad, or selectrad). Without one of these options,
        the API responds with 200 OK but returns the "monthly" table
        without any irradiance values.

        Parameters:
            latitude: Latitude of the location
            longitude: Longitude of the location
            horirrad: If True, includes H(h)_m (irradiance on the horizontal plane)
            optrad: If True, includes H(i_opt)_m (irradiance at the optimal tilt angle)
            selectrad: If True, includes H(i)_m for the tilt angle specified
                in `angle` (required in this case)
            angle: Tilt angle in degrees, used only if selectrad=True

        Returns:
        A dictionary containing monthly solar irradiance data
        """
        params = {
            "lat": latitude,
            "lon": longitude,
            "outputformat": "json",
            "horirrad": 1 if horirrad else 0,
            "optrad": 1 if optrad else 0,
        }
        if selectrad:
            params["selectrad"] = 1
            params["angle"] = angle

        try:

            url = f"{self.base_url}/MRcalc"
            logger.info(
                f"Requesting PVGIS (Monthly): lat={latitude}, lon={longitude}"
            )
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"✓ Response received successfully")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"✕ Request failed: {e}")
            raise

    def get_hourly_pvgis(
            self,
        latitude: float,
        longitude: float,
        year: int,
        month: int,
        day: int,
    ) -> Dict[str, Any]:
        """
        Extracts hourly solar irradiance data for a specific date.

        The seriescalc tool does not support a "single day" range: it always
        returns the entire hourly series between startyear and endyear. Therefore,
        we request only the desired year (startyear=endyear=year) and filter
        locally for the hours of the requested day.

        Parameters:
            latitude: Latitude of the location
            longitude: Longitude of the location
            year: (2007-2020 available)
            month: (1-12)
            day: (1-31)

        Returns:
        A dictionary with the hourly records (list) for the requested day
        """
        params = {
            "lat": latitude,
            "lon": longitude,
            "startyear": year,
            "endyear": year,
            "components": 1,
            "outputformat": "json",
        }

        try:

            url = f"{self.base_url}/seriescalc"
            logger.info(
                f"Requesting PVGIS (Hourly): lat={latitude}, lon={longitude}, "
                f"data={year}-{month:02d}-{day:02d}"
            )
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"✓ Response received successfully")

            # Filter only the hours of the requested day.
            # The "time" field is provided in the "YYYYMMDD:HHMM" format.
            target_prefix = f"{year}{month:02d}{day:02d}"
            hourly = data.get("outputs", {}).get("hourly", [])
            day_records = [
                record for record in hourly
                if record.get("time", "").startswith(target_prefix)
            ]

            return {
                "inputs": data.get("inputs", {}),
                "meta": data.get("meta", {}),
                "outputs": {"hourly": day_records},
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"✕ Request failed: {e}")
            raise

    def get_typical_meteorological_year(
        self,
        latitude: float,
        longitude: float,
        startyear: int = 2007,
        endyear: int = 2020,
    ) -> Dict[str, Any]:
        """
        Extracts typical meteorological year (TMY) data.

        Parameters:
            latitude: Latitude of the location
            longitude: Longitude of the location
            startyear: Start year for TMY data
            endyear: End year for TMY data

        Returns:
            A dictionary containing TMY data
        """
        params = {
            "lat": latitude,
            "lon": longitude,
            "startyear": startyear,
            "endyear": endyear,
            "outputformat": "json",
        }

        try:

            url = f"{self.base_url}/tmy"
            logger.info(
                f"Requesting PVGIS (TMY): lat={latitude}, lon={longitude}, "
                f"period={startyear}-{endyear}"
            )
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            logger.info(f"✓ Response received successfully")
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"✕ Request failed: {e}")
            raise


# ============================================================================
# Test Functions for the API
# ============================================================================

def test_monthly_data():
    """Test extraction of monthly solar irradiance data."""
    logger.info("=" * 70)
    logger.info("TEST 1: Monthly Solar Irradiance Data")
    logger.info("=" * 70)

    api = PVGISAPI()
    coord = COORDINATES["netherlands_north"]

    try:
        data = api.get_monthly_pvgis(
            latitude=coord["lat"],
            longitude=coord["lon"],
            horirrad=True,
            optrad=True,
        )

        logger.info("\n Response Structure:")
        logger.info(json.dumps(
            {
                "location": {
                    "latitude": data.get("inputs", {}).get("location", {}).get("latitude"),
                    "longitude": data.get("inputs", {}).get("location", {}).get("longitude"),
                    "elevation": data.get("inputs", {}).get("location", {}).get("elevation"),
                },
                "outputs_keys": list(data.get("outputs", {}).keys()) if "outputs" in data else [],
                "monthly_data_available": bool(data.get("outputs", {}).get("monthly")),
            },
            indent=2,
        ))

        # sample of monthly data
        monthly = data.get("outputs", {}).get("monthly", [])
        if monthly:
            logger.info("\n Sample of the First 3 Months:")
            for i in range(min(3, len(monthly))):
                sample = {
                    "year": monthly[i].get("year"),
                    "month": monthly[i].get("month"),
                    "H(h)_m_kWh_m2_mo": monthly[i].get("H(h)_m"),
                    "H(i_opt)_m_kWh_m2_mo": monthly[i].get("H(i_opt)_m"),
                }
                logger.info(f"  [Month {i+1}] {json.dumps(sample)}")

        logger.info("\n✓ Test 1 completed successfully.")

    except Exception as e:
        logger.error(f"✕ Error in Test 1: {e}")


def test_hourly_data():
    """Test extraction of hourly solar irradiance data."""
    logger.info("=" * 70)
    logger.info("TEST 2: Hourly Solar Irradiance Data")
    logger.info("=" * 70)

    api = PVGISAPI()
    coord = COORDINATES["germany_south"]

    # Use historical data within the available range (2007-2020)
    year, month, day = 2020, 6, 15  # European summer

    try:
        data = api.get_hourly_pvgis(
            latitude=coord["lat"],
            longitude=coord["lon"],
            year=year,
            month=month,
            day=day,
        )

        logger.info("\n Response Structure:")
        logger.info(json.dumps(
            {
                "location": {
                    "latitude": data.get("inputs", {}).get("location", {}).get("latitude"),
                    "longitude": data.get("inputs", {}).get("location", {}).get("longitude"),
                    "elevation": data.get("inputs", {}).get("location", {}).get("elevation"),
                },
                "query_date": f"{year}-{month:02d}-{day:02d}",
                "hourly_records_found": len(data.get("outputs", {}).get("hourly", [])),
            },
            indent=2,
        ))

        # Sample of hourly data (registros já filtrados para o dia pedido)
        hourly = data.get("outputs", {}).get("hourly", [])
        if hourly:
            logger.info("\n Sample of Hourly Records (every 3 hours):")
            for key in ["Gb(i)", "Gd(i)", "Gr(i)"]:  # Direct, Diffuse, Reflected
                values = [record.get(key) for record in hourly]
                logger.info(f"  {key}: {values[::3][:5]}")  # Every 3h, max 5 values

        logger.info("\n✓ Test 2 completed successfully!")

    except Exception as e:
        logger.error(f"✕ Error in Test 2: {e}")


def test_tmy_data():
    """Test extraction of Typical Meteorological Year data."""
    logger.info("=" * 70)
    logger.info("TEST 3: Typical Meteorological Year Data (TMY)")
    logger.info("=" * 70)

    api = PVGISAPI()
    coord = COORDINATES["spain_madrid"]

    try:
        data = api.get_typical_meteorological_year(
            latitude=coord["lat"],
            longitude=coord["lon"],
            startyear=2007,
            endyear=2020,
        )

        tmy_hourly = data.get("outputs", {}).get("tmy_hourly", [])

        logger.info("\n TMY Response Structure:")
        logger.info(json.dumps(
            {
                "location": coord["name"],
                "latitude": coord["lat"],
                "longitude": coord["lon"],
                "tmy_data_available": bool(tmy_hourly),
                "outputs_keys": list(data.get("outputs", {}).keys()) if "outputs" in data else [],
            },
            indent=2,
        ))

        # sample TMY data
        if tmy_hourly:

            logger.info("\n Sample of 5 Hourly TMY Records:")
            for i, record in enumerate(tmy_hourly[:5]):
                time_value = record.get("time", record.get("time(UTC)"))
                sample = {
                    "time": time_value,
                    "G(h)": record.get("G(h)"),
                    "T2m": record.get("T2m"),
                    "RH": record.get("RH"),
                }
                logger.info(f"  [{i}] {json.dumps(sample)}")

        logger.info("\n✓ Test 3 completed successfully!")

    except Exception as e:
        logger.error(f"✕ Error in Test 3: {e}")


def test_multiple_locations():
    """Test extraction of data from multiple locations."""
    logger.info("=" * 70)
    logger.info("TEST 4: Multiple Locations (Monthly Data)")
    logger.info("=" * 70)

    api = PVGISAPI()
    results = {}

    for location_name, coord in COORDINATES.items():
        try:
            logger.info(f"\n  Extracting data for {coord['name']}...")
            data = api.get_monthly_pvgis(
                latitude=coord["lat"],
                longitude=coord["lon"],
                horirrad=True,
            )

            # WARNING: Without startyear/endyear, MRcalc returns ALL available years
            # (e.g., 2005-2020 = 16 years), not just 12 months. Therefore,
            # simply summing H(h)_m is not enough — we need to divide by the number
            # of years to obtain the actual average annual irradiance.
            monthly = data.get("outputs", {}).get("monthly", [])
            years = sorted(set(record.get("year") for record in monthly))
            num_years = len(years) or 1

            total_irradiance = sum(record.get("H(h)_m", 0) for record in monthly)
            annual_irradiance = total_irradiance / num_years

            results[location_name] = {
                "status": "success",
                "location": coord["name"],
                "period": f"{years[0]}-{years[-1]}" if years else "n/a",
                "annual_irradiance_kWh_m2": round(annual_irradiance, 2),
            }
        except Exception as e:
            results[location_name] = {
                "status": "error",
                "error": str(e),
            }

    logger.info("\n Comparative Summary of Annual Irradiance:")
    logger.info(json.dumps(results, indent=2))
    logger.info("\n✓ Test 4 completed successfully!")


def test_rate_limits():
    """Test behavior under rate limits."""
    logger.info("=" * 70)
    logger.info("TEST 5: Rate Limit Behavior")
    logger.info("=" * 70)

    logger.info("PVGIS Rate Limits:")
    logger.info("  - Free for non-commercial use")
    logger.info("  - Documented limit: 30 requests/second per IP")
    logger.info("  - Above this limit: error 429 (too many requests)")
    logger.info("  - Overloaded server: error 529 (retry later)\n")

    api = PVGISAPI()
    coord = COORDINATES["portugal_south"]

    for attempt in range(3):
        try:
            logger.info(f"  Attempt {attempt + 1}/3...")
            data = api.get_monthly_pvgis(
                latitude=coord["lat"],
                longitude=coord["lon"],
                horirrad=True,
            )
            logger.info(f"  ✓ Success")
        except Exception as e:
            logger.error(f"  ✕ Error: {e}")

    logger.info("\n✓ Test 5 completed successfully!")


# ============================================================================
# EXPECTED DATA SCHEMA
# ============================================================================

# (https://joint-research-centre.ec.europa.eu/.../pvgis-tools/monthly-radiation_en).
PVGIS_MONTHLY_SCHEMA = {
    "inputs": {
        "location": {
            "latitude": "float",
            "longitude": "float",
            "elevation": "float",
        },
        "meteo_data": "dict",
        "plane": "dict",
    },
    "outputs": {
        "monthly": [
            {
                "year": "int",
                "month": "int",         # 1-12
                "H(h)_m": "float",      # Irradiance on the horizontal plane (kWh/m²/month) — requires horirrad=1
                "H(i_opt)_m": "float",  # Irradiance at the optimal tilt angle (kWh/m²/month) — requires optrad=1
                "H(i)_m": "float",      # Irradiance at the selected tilt angle (kWh/m²/month) — requires selectrad=1
                "Hb(n)_m": "float",     # Direct normal irradiance (kWh/m²/month) — requires mr_dni=1
                "Kd": "float",          # Diffuse-to-global ratio — requires d2g=1
                "T2m": "float",         # Average daily temperature (°C) — requires avtemp=1
            }
        ]
    },
    "meta": {
        "inputs": "dict",
        "outputs": "dict",
    }
}

# (https://joint-research-centre.ec.europa.eu/.../pvgis-tools/hourly-radiation_en).
PVGIS_HOURLY_SCHEMA = {
    "inputs": {
        "location": {
            "latitude": "float",
            "longitude": "float",
            "elevation": "float",
        },
        "meteo_data": "dict",   # radiation database used (e.g., PVGIS-SARAH2)
    },
    "outputs": {
        "hourly": [
            {
                "time": "str",     # format "YYYYMMDD:HHMM" (UTC)
                "P": "float",      # PV power in W (only if pvcalculation=1)
                "G(i)": "float",   # global irradiance on the plane (W/m²) — only if components != 1
                "Gb(i)": "float",  # direct irradiance on the plane (W/m²) — only if components=1
                "Gd(i)": "float",  # diffuse irradiance on the plane (W/m²) — only if components=1
                "Gr(i)": "float",  # reflected irradiance on the plane (W/m²) — only if components=1
                "H_sun": "float",  # solar height/elevation (degrees)
                "T2m": "float",    # air temperature at 2 m (°C)
                "WS10m": "float",  # wind speed at 10 m (m/s)
                "Int": "int",      # 1 if the value was reconstructed/interpolated, 0 otherwise
            }
        ]
    },
    "meta": {
        "inputs": "dict",
        "outputs": "dict",
    }
}

# TMY route schema, according to the official documentation
# (https://joint-research-centre.ec.europa.eu/.../pvgis-typical-meteorological-year-tmy-generator_en).
PVGIS_TMY_SCHEMA = {
    "inputs": {
        "location": {
            "latitude": "float",
            "longitude": "float",
            "elevation": "float",
        },
        "meteo_data": "dict",
    },
    "outputs": {
        "months_selected": [
            {"month": "int", "year": "int"}
        ],
        "tmy_hourly": [
            {
                "time": "str",     # format "YYYYMMDD:HHMM"
                "T2m": "float",    # air temperature at 2 m (°C)
                "RH": "float",     # relative humidity (%)
                "G(h)": "float",   # global horizontal irradiance (W/m²)
                "Gb(n)": "float",  # direct normal irradiance (W/m²)
                "Gd(h)": "float",  # diffuse horizontal irradiance (W/m²)
                "IR(h)": "float",  # downward infrared radiation (W/m²)
                "WS10m": "float",  # wind speed at 10 m (m/s)
                "WD10m": "float",  # wind direction at 10 m (degrees)
                "SP": "float",     # atmospheric pressure (Pa)
            }
        ]
    },
    "meta": {
        "inputs": "dict",
        "outputs": "dict",
    }
}


def print_schema():
    """Print the expected data schemas for the PVGIS API."""
    logger.info("=" * 70)
    logger.info("PVGIS API EXPECTED DATA SCHEMA")
    logger.info("=" * 70)
    logger.info("\n🔹 MONTHLY SCHEMA:")
    logger.info(json.dumps(PVGIS_MONTHLY_SCHEMA, indent=2))
    logger.info("\n🔹 HOURLY SCHEMA:")
    logger.info(json.dumps(PVGIS_HOURLY_SCHEMA, indent=2))
    logger.info("\n🔹 TMY SCHEMA:")
    logger.info(json.dumps(PVGIS_TMY_SCHEMA, indent=2))


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    logger.info("\n TEST AND EXPLORATION: API PVGIS (JRC)")
    logger.info("Repository: renewable-energy-finops\n")

    test_monthly_data()
    test_hourly_data()
    test_tmy_data()
    test_multiple_locations()
    test_rate_limits()
    print_schema()

    logger.info("=" * 70)
    logger.info("✓ ALL TESTS COMPLETED!")
    logger.info("=" * 70)