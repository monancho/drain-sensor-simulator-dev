"""Time-based virtual sensor simulation for storm-drain MVP.

This module intentionally uses a lightweight, explainable model.
It is not SWMM, CFD, or a real hydraulic solver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DrainId = Literal["DRAIN_A", "DRAIN_B", "DRAIN_C"]
BlockageLocation = Literal["없음", "상부", "내부", "복합"]

DRAIN_IDS: tuple[DrainId, ...] = ("DRAIN_A", "DRAIN_B", "DRAIN_C")


@dataclass(frozen=True)
class SimulationConstants:
    """Tunable constants for the lightweight water-flow model."""

    runoff_factor: float = 0.085
    inlet_factor: float = 0.11
    outflow_factor: float = 0.22
    flow_speed_factor: float = 4.8
    surface_relief_factor: float = 0.006
    dry_surface_recession_factor: float = 0.045


DEFAULT_CONSTANTS = SimulationConstants()


def clamp01(value: float) -> float:
    """Clamp a numeric value into the 0.0~1.0 range."""

    return max(0.0, min(1.0, float(value)))


def resolve_blockage(
    blockage_location: BlockageLocation,
    blockage_severity: float,
) -> tuple[float, float]:
    """Convert blockage UI controls into surface/internal blockage values.

    상부 막힘: 배수구 위 그레이팅/도로면 쓰레기 때문에 물이 지하로 못 들어감.
    내부 막힘: 물은 들어가지만 관로 내부에서 빠지지 못함.
    복합 막힘: 두 문제가 동시에 존재.
    """

    severity = clamp01(blockage_severity)

    if blockage_location == "없음":
        return 0.0, 0.0

    if blockage_location == "상부":
        return severity, 0.0

    if blockage_location == "내부":
        return 0.0, severity

    if blockage_location == "복합":
        return severity, severity

    raise ValueError(f"Unknown blockage_location: {blockage_location}")


def initialize_drain_states() -> dict[str, dict[str, float | str]]:
    """Create initial state for each drain."""

    states: dict[str, dict[str, float | str]] = {}

    for drain_id in DRAIN_IDS:
        states[drain_id] = {
            "drain_id": drain_id,
            "blockage_location": "없음",
            "blockage_severity": 0.0,
            "surface_blockage": 0.0,
            "internal_blockage": 0.0,
            "inlet_capacity": 1.0,
            "pipe_capacity_effective": 1.0,
            "surface_water_level": 0.05,
            "inlet_flow": 0.0,
            "surface_recession": 0.0,
            "upstream_pipe_flow": 0.0,
            "pipe_segment_outflow": 0.0,
            "pipe_water_level": 0.15,
            "pipe_flow_speed": 0.0,
            "pipe_flow_rate": 0.0,
            "surface_water_delta": 0.0,
            "pipe_water_delta": 0.0,
            "pipe_flow_delta": 0.0,
            "level_flow_ratio": 0.0,
            "stagnation_score": 0.0,
            "remaining_surface_capacity": 0.95,
            "remaining_pipe_capacity": 0.85,
            "sensor_status": "정상 배수",
        }

    return states


def update_drain_state(
    current_state: dict[str, float | str],
    *,
    rainfall: float,
    blockage_location: BlockageLocation,
    blockage_severity: float,
    pipe_capacity: float,
    upstream_pipe_flow: float = 0.0,
    step_minutes: float = 1.0,
    constants: SimulationConstants = DEFAULT_CONSTANTS,
) -> dict[str, float | str]:
    """Advance one drain state by one simulation step.

    Model idea:
    - rainfall creates surface water on the road.
    - surface blockage reduces inlet flow into the drain.
    - upstream pipe flow can pass below a surface-blocked grate.
    - internal blockage reduces underground pipe through-flow/outflow.
    - surface/pipeline water levels are tracked separately.
    """

    drain_id = str(current_state["drain_id"])
    rainfall = clamp01(rainfall)
    pipe_capacity = max(0.0, float(pipe_capacity))
    upstream_pipe_flow = clamp01(upstream_pipe_flow)
    step_minutes = max(0.1, float(step_minutes))

    surface_blockage, internal_blockage = resolve_blockage(
        blockage_location,
        blockage_severity,
    )

    previous_surface_water = clamp01(float(current_state.get("surface_water_level", 0.05)))
    previous_pipe_water = clamp01(float(current_state.get("pipe_water_level", 0.15)))
    previous_pipe_flow = clamp01(float(current_state.get("pipe_flow_speed", 0.0)))

    rain_inflow = rainfall * constants.runoff_factor * step_minutes

    inlet_capacity = clamp01(1.0 - surface_blockage)
    max_inlet_flow = inlet_capacity * constants.inlet_factor * step_minutes
    available_surface_water = previous_surface_water + rain_inflow
    inlet_flow = min(available_surface_water, max_inlet_flow)
    surface_after_inlet = available_surface_water - inlet_flow
    surface_recession_factor = (
        constants.surface_relief_factor
        + (1.0 - rainfall) * constants.dry_surface_recession_factor
    )
    surface_recession = surface_after_inlet * surface_recession_factor * step_minutes
    surface_recession = max(0.0, min(surface_recession, surface_after_inlet))

    next_surface_water = clamp01(surface_after_inlet - surface_recession)

    pipe_capacity_effective = clamp01(pipe_capacity * (1.0 - internal_blockage))
    local_pipe_water = previous_pipe_water + inlet_flow
    local_outflow = local_pipe_water * pipe_capacity_effective * constants.outflow_factor * step_minutes
    local_outflow = max(0.0, min(local_outflow, local_pipe_water))

    # Surface blockage affects only the local inlet. Water already in the main
    # pipe keeps moving downstream unless the internal pipe is restricted.
    through_flow = upstream_pipe_flow * pipe_capacity_effective
    available_pipe_water = local_pipe_water + upstream_pipe_flow
    outflow = max(0.0, min(local_outflow + through_flow, available_pipe_water))

    next_pipe_water = clamp01(available_pipe_water - outflow)
    pipe_flow_speed = clamp01(outflow * constants.flow_speed_factor)
    pipe_flow_rate = clamp01(pipe_flow_speed * pipe_capacity_effective)

    surface_water_delta = next_surface_water - previous_surface_water
    pipe_water_delta = next_pipe_water - previous_pipe_water
    pipe_flow_delta = pipe_flow_speed - previous_pipe_flow

    level_flow_ratio = next_pipe_water / (pipe_flow_speed + 0.01)
    stagnation_score = (
        max(0.0, surface_water_delta) * 0.45
        + max(0.0, pipe_water_delta) * 0.75
        + max(0.0, -pipe_flow_delta) * 0.55
        + max(0.0, internal_blockage - pipe_flow_speed) * 0.20
    )

    return {
        "drain_id": drain_id,
        "blockage_location": blockage_location,
        "blockage_severity": clamp01(blockage_severity),
        "surface_blockage": round(surface_blockage, 4),
        "internal_blockage": round(internal_blockage, 4),
        "inlet_capacity": round(inlet_capacity, 4),
        "pipe_capacity_effective": round(pipe_capacity_effective, 4),
        "surface_water_level": round(next_surface_water, 4),
        "inlet_flow": round(inlet_flow, 4),
        "surface_recession": round(surface_recession, 4),
        "upstream_pipe_flow": round(upstream_pipe_flow, 4),
        "pipe_segment_outflow": round(outflow, 4),
        "pipe_water_level": round(next_pipe_water, 4),
        "pipe_flow_speed": round(pipe_flow_speed, 4),
        "pipe_flow_rate": round(pipe_flow_rate, 4),
        "surface_water_delta": round(surface_water_delta, 4),
        "pipe_water_delta": round(pipe_water_delta, 4),
        "pipe_flow_delta": round(pipe_flow_delta, 4),
        "level_flow_ratio": round(level_flow_ratio, 4),
        "stagnation_score": round(stagnation_score, 4),
        "remaining_surface_capacity": round(1.0 - next_surface_water, 4),
        "remaining_pipe_capacity": round(1.0 - next_pipe_water, 4),
        "sensor_status": str(current_state.get("sensor_status", "정상 배수")),
    }


def run_step(
    states: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    step_minutes: float = 1.0,
) -> dict[str, dict[str, float | str]]:
    """Update all drain states for one step."""

    next_states: dict[str, dict[str, float | str]] = {}
    upstream_pipe_flow = 0.0

    for drain_id in DRAIN_IDS:
        location, severity = blockage_configs[drain_id]
        next_states[drain_id] = update_drain_state(
            states[drain_id],
            rainfall=rainfall,
            blockage_location=location,
            blockage_severity=severity,
            pipe_capacity=pipe_capacity,
            upstream_pipe_flow=upstream_pipe_flow,
            step_minutes=step_minutes,
        )
        upstream_pipe_flow = float(next_states[drain_id]["pipe_segment_outflow"])

    return next_states
