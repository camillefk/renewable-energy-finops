{{
    config(
        materialized='incremental',
        incremental_strategy='insert_overwrite',
        partition_by={'field': 'observation_date', 'data_type': 'date', 'granularity': 'day'},
        cluster_by=['station_id'],
        on_schema_change='append_new_columns'
    )
}}

{#
  Gold fact table, hourly grain: one row per (observation_at, station_id).

  Incremental strategy: insert_overwrite. Every run replaces whole date partitions of the last
  `incremental_lookback_days`, so re-running or back-filling a day never creates duplicates
  (same idempotency principle as the Airflow ingestion), and only the touched partitions are billed.

  Solar: PVGIS power when available, otherwise a modelled estimate from irradiance with
  a temperature derating. Wind: generic turbine power curve applied to wind speed at 100 m.
  Both are expressed per reference plant (see vars) and as capacity factors (0..1),
  which makes solar and wind directly comparable.
#}

with weather as (

    select * from {{ ref('stg_weather_solar') }}

    {% if is_incremental() %}
    where observation_date >= date_sub(
        (select max(observation_date) from {{ this }}),
        interval {{ var('incremental_lookback_days') }} day
    )
    {% endif %}

),

solar as (

    select
        *,
        temperature_c + {{ var('solar_cell_temp_rise_per_wm2') }} * solar_radiation_wm2 as cell_temperature_c
    from weather

),

solar_model as (

    select
        *,
        greatest(0.0, 1 + {{ var('solar_temp_coefficient') }} * (cell_temperature_c - 25))
            as temperature_derating_factor
    from solar

),

solar_output as (

    select
        *,
        -- 1-hour interval: kW == kWh for the hour. Values are per 1 kWp installed.
        solar_radiation_wm2 / 1000.0 * {{ var('solar_performance_ratio') }} * temperature_derating_factor
            as modelled_solar_kwh_per_kwp
    from solar_model

),

generation as (

    select
        *,
        coalesce(pvgis_pv_power_kw, modelled_solar_kwh_per_kwp)            as solar_kwh_per_kwp,
        if(pvgis_pv_power_kw is not null, 'pvgis', 'modelled')             as solar_data_source,
        {{ wind_capacity_factor('wind_speed_100m_ms') }}                   as wind_capacity_factor
    from solar_output

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['observation_at', 'station_id']) }} as energy_generation_key,
        observation_at,
        observation_date,
        observation_hour_local,
        station_id,
        city,
        latitude,
        longitude,

        -- weather drivers
        temperature_c,
        cloud_cover_pct,
        solar_radiation_wm2,
        wind_speed_100m_ms,
        temperature_derating_factor,

        -- normalised, comparable metrics (0..1)
        least(1.0, solar_kwh_per_kwp)                                       as solar_capacity_factor,
        wind_capacity_factor,

        -- generation for the reference plants (1 MWp solar, one 5 MW turbine by default)
        solar_kwh_per_kwp * {{ var('reference_solar_kwp') }}                as solar_generation_kwh,
        wind_capacity_factor * {{ var('reference_wind_kw') }}               as wind_generation_kwh,
        solar_kwh_per_kwp * {{ var('reference_solar_kwp') }}
            + wind_capacity_factor * {{ var('reference_wind_kw') }}         as total_renewable_kwh,

        solar_data_source,
        current_timestamp()                                                 as dbt_updated_at
    from generation

)

select * from final