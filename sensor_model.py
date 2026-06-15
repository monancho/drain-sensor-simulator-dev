"""Sensor-status interpretation rules.

This is not a risk classifier. It describes the observed sensor pattern.
"""

from __future__ import annotations


def interpret_sensor_status(state: dict[str, float | str]) -> str:
    """Interpret sensor readings into a human-readable status.

    The order matters. Complex blockage is checked before individual patterns.
    """

    surface_water_level = float(state.get("surface_water_level", 0.0))
    inlet_flow = float(state.get("inlet_flow", 0.0))
    pipe_water_level = float(state.get("pipe_water_level", 0.0))
    pipe_flow_speed = float(state.get("pipe_flow_speed", 0.0))
    surface_blockage = float(state.get("surface_blockage", 0.0))
    internal_blockage = float(state.get("internal_blockage", 0.0))
    downstream_backwater = float(state.get("downstream_backwater", 0.0))
    pipe_water_delta = float(state.get("pipe_water_delta", 0.0))
    surface_water_delta = float(state.get("surface_water_delta", 0.0))

    if (
        surface_water_level >= 0.60
        and pipe_water_level >= 0.60
        and pipe_flow_speed <= 0.30
    ) or (surface_blockage >= 0.70 and internal_blockage >= 0.70):
        return "복합 막힘 의심"

    if (surface_water_level >= 0.55 and inlet_flow <= 0.035) or (
        surface_blockage >= 0.75 and surface_water_delta > 0
    ):
        return "상부 유입 막힘 의심"

    if (pipe_water_level >= 0.70 and pipe_flow_speed <= 0.30) or (
        internal_blockage >= 0.75 and pipe_water_delta > 0
    ):
        return "내부 정체 의심"

    if downstream_backwater >= 0.45 and pipe_water_level >= 0.65 and pipe_flow_speed <= 0.55:
        return "하류 병목 영향"

    if pipe_water_level >= 0.70 and pipe_flow_speed >= 0.55:
        return "배수 진행 중"

    if surface_water_level >= 0.45:
        return "도로면 물고임"

    if pipe_flow_speed <= 0.20 and pipe_water_level >= 0.40:
        return "흐름 약함"

    return "정상 배수"


def attach_sensor_status(state: dict[str, float | str]) -> dict[str, float | str]:
    """Return a copy of a drain state with sensor_status populated."""

    next_state = dict(state)
    next_state["sensor_status"] = interpret_sensor_status(next_state)
    return next_state
