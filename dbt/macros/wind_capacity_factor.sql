{#
  Capacity factor (0..1) of a generic wind turbine at a given hub-height wind speed (m/s).

    v <  cut_in          -> 0
    cut_in <= v < rated  -> cubic ramp: (v^3 - cut_in^3) / (rated^3 - cut_in^3)
    rated <= v <= cutout -> 1
    v >  cut_out         -> 0 (turbine shuts down for safety)

  Parameters come from dbt_project.yml vars so the curve can be tuned in one place.
#}
{% macro wind_capacity_factor(speed_ms) %}
    case
        when {{ speed_ms }} is null then null
        when {{ speed_ms }} < {{ var('wind_cut_in_ms') }} then 0.0
        when {{ speed_ms }} < {{ var('wind_rated_ms') }} then
            safe_divide(
                pow({{ speed_ms }}, 3) - pow({{ var('wind_cut_in_ms') }}, 3),
                pow({{ var('wind_rated_ms') }}, 3) - pow({{ var('wind_cut_in_ms') }}, 3)
            )
        when {{ speed_ms }} <= {{ var('wind_cut_out_ms') }} then 1.0
        else 0.0
    end
{% endmacro %}