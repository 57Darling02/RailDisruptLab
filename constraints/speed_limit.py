from __future__ import annotations

import math

from core.builder import BuildContext


def apply_speed_limit_constraints(ctx: BuildContext) -> None:
    for speed_limit in ctx.config.scenarios.speed_limits:
        if speed_limit.limit_speed <= 0:
            continue

        section = (speed_limit.start_station, speed_limit.end_station)
        distance_km = abs(
            ctx.config.base_context.mileage_by_station[speed_limit.end_station]
            - ctx.config.base_context.mileage_by_station[speed_limit.start_station]
        )
        if distance_km <= 0:
            raise ValueError(
                f"Speed limit section distance must be positive: {speed_limit.start_station}->{speed_limit.end_station}"
            )

        for train_id, sections in ctx.translated.train_sections.items():
            if section not in sections:
                continue

            dep_key = (train_id, speed_limit.start_station, "dep")
            arr_key = (train_id, speed_limit.end_station, "arr")
            planned_dep = ctx.translated.event_time[dep_key]
            planned_arr = ctx.translated.event_time[arr_key]

            overlaps_window = planned_dep < speed_limit.end_time and planned_arr > speed_limit.start_time
            if not overlaps_window:
                continue

            base_runtime = ctx.translated.planned_section_runtime[
                (train_id, speed_limit.start_station, speed_limit.end_station)
            ]
            limited_runtime = int(math.ceil(distance_km * 3600.0 / speed_limit.limit_speed))
            runtime_rhs = max(float(base_runtime), float(limited_runtime))
            if runtime_rhs <= float(base_runtime):
                continue

            ctx.model.add_constraint(
                name=f"speed_limit_{ctx.event_id[arr_key]}",
                coefficients={ctx.time_var[arr_key]: 1.0, ctx.time_var[dep_key]: -1.0},
                sense=">=",
                rhs=runtime_rhs,
            )
