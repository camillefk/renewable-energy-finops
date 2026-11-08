{{ config(materialized='table', cluster_by=['city']) }}

{#
  Answers the architectural question:
  "When solar generation drops (winter / cloudy days), does wind compensate in the analysed cities?"

  Grain: one row per (city, day).
  Method (all in capacity factors, so 1 kW of solar and 1 kW of wind are comparable):
    1. baseline   = trailing average of the previous N days (current day excluded)
    2. low-solar  = solar CF below `low_solar_threshold` x its baseline
    3. shortfall  = how far solar is under its baseline
    4. surplus    = how far wind is over its baseline
    5. wind compensates when it is a low-solar day AND surplus >= shortfall
  Rows without enough history (< min_history_days) get NULL flags instead of misleading answers.
#}

with city_hour as (

    select
        city,
        observation_date,
        observation_at,
        avg(solar_capacity_factor)  as solar_cf,
        avg(wind_capacity_factor)   as wind_cf,
        avg(cloud_cover_pct)        as cloud_cover_pct,
        avg(temperature_c)          as temperature_c,
        sum(solar_generation_kwh)   as solar_generation_kwh,
        sum(wind_generation_kwh)    as wind_generation_kwh
    from {{ ref('fct_energy_generation') }}
    group by city, observation_date, observation_at

),

daily as (

    select
        city,
        observation_date,
        count(*)                    as hours_observed,
        avg(solar_cf)               as solar_cf,
        avg(wind_cf)                as wind_cf,
        avg(cloud_cover_pct)        as avg_cloud_cover_pct,
        avg(temperature_c)          as avg_temperature_c,
        sum(solar_generation_kwh)   as solar_generation_kwh,
        sum(wind_generation_kwh)    as wind_generation_kwh
    from city_hour
    group by city, observation_date
    having count(*) >= {{ var('min_hours_per_day') }}   -- complete days only

),

baselined as (

    select
        *,
        avg(solar_cf) over trailing  as baseline_solar_cf,
        avg(wind_cf)  over trailing  as baseline_wind_cf,
        count(*)      over trailing  as history_days
    from daily
    window trailing as (
        partition by city
        order by observation_date
        rows between {{ var('rolling_window_days') }} preceding and 1 preceding
    )

),

scored as (

    select
        *,
        history_days >= {{ var('min_history_days') }}                          as has_baseline,
        greatest(baseline_solar_cf - solar_cf, 0)                              as solar_shortfall_cf,
        greatest(wind_cf - baseline_wind_cf, 0)                                as wind_surplus_cf
    from baselined

)

select
    city,
    observation_date,
    hours_observed,
    avg_cloud_cover_pct,
    avg_temperature_c,
    solar_generation_kwh,
    wind_generation_kwh,
    solar_cf,
    wind_cf,
    baseline_solar_cf,
    baseline_wind_cf,
    has_baseline,
    if(has_baseline, solar_cf < baseline_solar_cf * {{ var('low_solar_threshold') }}, null)
        as is_low_solar_day,
    solar_shortfall_cf,
    wind_surplus_cf,
    if(
        has_baseline,
        solar_cf < baseline_solar_cf * {{ var('low_solar_threshold') }}
            and wind_surplus_cf >= solar_shortfall_cf,
        null
    ) as is_wind_compensating,
    safe_divide(wind_surplus_cf, solar_shortfall_cf)                           as compensation_ratio
from scored