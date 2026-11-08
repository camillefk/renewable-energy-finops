{{ config(materialized='view') }}

with weather as (
    select * from {{ source('silver', 'silver_weather_hourly') }}
),

solar as (
    select * from {{ source('silver', 'silver_solar_hourly') }}
),

typed as (
    select
        
        cast(w.observed_at as timestamp)            as observation_at,
        cast(w.city_id as string)                   as station_id,
        cast(w.city_id as string)                   as city,
        
        cast(null as float64)                       as latitude,
        cast(null as float64)                       as longitude,
        
        cast(w.temperature_2m_c as float64)         as temperature_c,
        cast(w.cloud_cover_pct as float64)          as cloud_cover_pct,
        cast(w.wind_speed_100m_kmh as float64)      as wind_speed_100m_kmh,
        
        cast(coalesce(s.global_irradiance_wm2, w.shortwave_radiation_wm2) as float64) as solar_radiation_wm2,
        
        cast(null as float64)                       as pvgis_pv_power_w
        
    from weather w
    left join solar s
        on w.observed_at = s.observed_at
        and w.city_id = s.city_id
),

converted as (
    select
        observation_at,
        date(observation_at, '{{ var("timezone") }}')                                 as observation_date,
        extract(hour from datetime(observation_at, '{{ var("timezone") }}'))          as observation_hour_local,
        station_id,
        city,
        latitude,
        longitude,
        temperature_c,
        cloud_cover_pct,
        solar_radiation_wm2,
        safe_divide(wind_speed_100m_kmh, 3.6)                                         as wind_speed_100m_ms,
        safe_divide(pvgis_pv_power_w, 1000.0)                                         as pvgis_pv_power_kw
    from typed
)

select * from converted