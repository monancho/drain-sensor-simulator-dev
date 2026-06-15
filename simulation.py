"""Time-based virtual sensor simulation for storm-drain MVP.

This module intentionally uses a lightweight, explainable model.
It is not SWMM, CFD, or a real hydraulic solver.
"""

from __future__ import annotations

import math
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
    flow_speed_factor: float = 3.2
    surface_relief_factor: float = 0.006
    dry_surface_recession_factor: float = 0.045
    internal_blockage_capacity_exponent: float = 1.35
    downstream_backwater_factor: float = 0.72
    backwater_storage_factor: float = 0.045
    pipe_surcharge_threshold: float = 0.84
    pipe_surcharge_factor: float = 0.20
    surface_spill_threshold: float = 0.74
    surface_spill_factor: float = 0.10
    surface_spill_capture_factor: float = 0.82


DEFAULT_CONSTANTS = SimulationConstants()


def clamp01(value: float) -> float:
    """Clamp a numeric value into the 0.0~1.0 range."""

    return max(0.0, min(1.0, float(value)))


def normalize_pipe_flow_speed(
    pipe_segment_outflow: float,
    constants: SimulationConstants = DEFAULT_CONSTANTS,
) -> float:
    """Map edge outflow to a normalized sensor speed without early clipping."""

    return clamp01(math.tanh(max(0.0, float(pipe_segment_outflow)) * constants.flow_speed_factor))


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
            "surface_spill_in": 0.0,
            "surface_spill_out": 0.0,
            "pipe_surcharge_to_surface": 0.0,
            "upstream_pipe_flow": 0.0,
            "downstream_backwater": 0.0,
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
    downstream_backwater: float = 0.0,
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
    downstream_backwater = clamp01(downstream_backwater)
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

    backwater_capacity_loss = downstream_backwater * constants.downstream_backwater_factor
    local_pipe_capacity = (1.0 - internal_blockage) ** constants.internal_blockage_capacity_exponent
    pipe_capacity_effective = clamp01(
        pipe_capacity * local_pipe_capacity * (1.0 - backwater_capacity_loss)
    )
    local_pipe_water = previous_pipe_water + inlet_flow
    local_outflow = local_pipe_water * pipe_capacity_effective * constants.outflow_factor * step_minutes
    local_outflow = max(0.0, min(local_outflow, local_pipe_water))

    # Surface blockage affects only the local inlet. Water already in the main
    # pipe keeps moving downstream unless the internal pipe is restricted.
    through_flow = upstream_pipe_flow * pipe_capacity_effective
    available_pipe_water = local_pipe_water + upstream_pipe_flow
    outflow = max(0.0, min(local_outflow + through_flow, available_pipe_water))

    next_pipe_water = clamp01(
        available_pipe_water
        - outflow
        + downstream_backwater * constants.backwater_storage_factor * step_minutes
    )
    surcharge_threshold = constants.pipe_surcharge_threshold - downstream_backwater * 0.18
    pipe_surcharge_to_surface = max(0.0, next_pipe_water - surcharge_threshold)
    pipe_surcharge_to_surface *= (
        constants.pipe_surcharge_factor
        + downstream_backwater * 0.20
        + internal_blockage * 0.08
    )
    pipe_surcharge_to_surface *= rainfall
    pipe_surcharge_to_surface = min(pipe_surcharge_to_surface, max(0.0, next_pipe_water - 0.50))
    next_surface_water = clamp01(next_surface_water + pipe_surcharge_to_surface)
    next_pipe_water = clamp01(next_pipe_water - pipe_surcharge_to_surface * 0.20)
    pipe_flow_speed = normalize_pipe_flow_speed(outflow, constants)
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
        "surface_spill_in": 0.0,
        "surface_spill_out": 0.0,
        "pipe_surcharge_to_surface": round(pipe_surcharge_to_surface, 4),
        "upstream_pipe_flow": round(upstream_pipe_flow, 4),
        "downstream_backwater": round(downstream_backwater, 4),
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


def calculate_downstream_backwater(
    states: dict[str, dict[str, float | str]],
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
) -> dict[str, float]:
    """Estimate downstream congestion that can back up pipe water upstream."""

    local_congestion: dict[str, float] = {}
    for drain_id in DRAIN_IDS:
        location, severity = blockage_configs[drain_id]
        _, internal_blockage = resolve_blockage(location, severity)
        previous_pipe_water = clamp01(float(states[drain_id].get("pipe_water_level", 0.15)))
        internal_congestion = internal_blockage * (0.68 + previous_pipe_water * 0.32)
        stored_water_congestion = max(0.0, previous_pipe_water - 0.66) * 0.45
        local_congestion[drain_id] = clamp01(internal_congestion + stored_water_congestion)

    downstream_backwater: dict[str, float] = {}
    carried_congestion = 0.0
    for drain_id in reversed(DRAIN_IDS):
        downstream_backwater[drain_id] = round(carried_congestion, 4)
        carried_congestion = clamp01(local_congestion[drain_id] + carried_congestion * 0.62)

    return downstream_backwater


def resolve_blockage_configs(
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
) -> dict[str, dict[str, float | str]]:
    """Resolve blockage controls for every drain into surface/internal factors."""

    resolved = {}
    for drain_id in DRAIN_IDS:
        location, severity = blockage_configs[drain_id]
        surface_blockage, internal_blockage = resolve_blockage(location, severity)
        resolved[drain_id] = {
            "location": location,
            "severity": clamp01(severity),
            "surface_blockage": surface_blockage,
            "internal_blockage": internal_blockage,
        }
    return resolved


def calculate_initial_surface_and_inlet(
    states: dict[str, dict[str, float | str]],
    resolved_blockages: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    step_minutes: float,
    constants: SimulationConstants,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Add rainfall to road storage and move available water through each inlet."""

    surface_storage: dict[str, float] = {}
    inlet_flow: dict[str, float] = {}
    inlet_capacity: dict[str, float] = {}

    for drain_id in DRAIN_IDS:
        previous_surface = clamp01(float(states[drain_id].get("surface_water_level", 0.05)))
        surface_blockage = float(resolved_blockages[drain_id]["surface_blockage"])
        rain_inflow = rainfall * constants.runoff_factor * step_minutes
        available_surface = previous_surface + rain_inflow
        inlet_capacity[drain_id] = clamp01(1.0 - surface_blockage)
        max_inlet_flow = inlet_capacity[drain_id] * constants.inlet_factor * step_minutes
        inlet_flow[drain_id] = min(available_surface, max_inlet_flow)
        surface_storage[drain_id] = available_surface - inlet_flow[drain_id]

    return surface_storage, inlet_flow, inlet_capacity


def calculate_pipe_edge_flows(
    states: dict[str, dict[str, float | str]],
    resolved_blockages: dict[str, dict[str, float | str]],
    inlet_flow: dict[str, float],
    downstream_backwater: dict[str, float],
    *,
    rainfall: float,
    pipe_capacity: float,
    step_minutes: float,
    constants: SimulationConstants,
) -> dict[str, dict[str, float]]:
    """Move pipe storage through A->B->C->outfall edges."""

    pipe_storage = {
        drain_id: clamp01(float(states[drain_id].get("pipe_water_level", 0.15)))
        + inlet_flow[drain_id]
        for drain_id in DRAIN_IDS
    }
    upstream_pipe_flow = {drain_id: 0.0 for drain_id in DRAIN_IDS}
    pipe_segment_outflow: dict[str, float] = {}
    pipe_capacity_effective: dict[str, float] = {}
    pipe_flow_speed: dict[str, float] = {}
    pipe_flow_rate: dict[str, float] = {}
    pipe_surcharge_to_surface: dict[str, float] = {}

    for index, drain_id in enumerate(DRAIN_IDS):
        internal_blockage = float(resolved_blockages[drain_id]["internal_blockage"])
        backwater = downstream_backwater[drain_id]
        backwater_capacity_loss = backwater * constants.downstream_backwater_factor
        local_pipe_capacity = (
            (1.0 - internal_blockage) ** constants.internal_blockage_capacity_exponent
        )
        pipe_capacity_effective[drain_id] = clamp01(
            pipe_capacity * local_pipe_capacity * (1.0 - backwater_capacity_loss)
        )

        available_pipe = pipe_storage[drain_id]
        pressure = 0.35 + available_pipe * 1.15
        edge_capacity = (
            pipe_capacity_effective[drain_id]
            * constants.outflow_factor
            * pressure
            * step_minutes
        )
        outflow = max(0.0, min(available_pipe, edge_capacity))
        pipe_storage[drain_id] = max(0.0, available_pipe - outflow)
        pipe_segment_outflow[drain_id] = outflow

        if index < len(DRAIN_IDS) - 1:
            downstream_id = DRAIN_IDS[index + 1]
            upstream_pipe_flow[downstream_id] += outflow
            pipe_storage[downstream_id] += outflow

    for drain_id in DRAIN_IDS:
        backwater = downstream_backwater[drain_id]
        internal_blockage = float(resolved_blockages[drain_id]["internal_blockage"])
        pipe_storage[drain_id] = clamp01(
            pipe_storage[drain_id]
            + backwater * constants.backwater_storage_factor * step_minutes
        )
        surcharge_threshold = constants.pipe_surcharge_threshold - backwater * 0.18
        surcharge = max(0.0, pipe_storage[drain_id] - surcharge_threshold)
        surcharge *= (
            constants.pipe_surcharge_factor
            + backwater * 0.20
            + internal_blockage * 0.08
        )
        surcharge *= rainfall
        surcharge = min(surcharge, max(0.0, pipe_storage[drain_id] - 0.50))
        pipe_surcharge_to_surface[drain_id] = surcharge
        pipe_storage[drain_id] = clamp01(pipe_storage[drain_id] - surcharge * 0.20)
        pipe_flow_speed[drain_id] = normalize_pipe_flow_speed(
            pipe_segment_outflow[drain_id],
            constants,
        )
        pipe_flow_rate[drain_id] = clamp01(
            pipe_flow_speed[drain_id] * pipe_capacity_effective[drain_id]
        )

    return {
        "pipe_storage": pipe_storage,
        "upstream_pipe_flow": upstream_pipe_flow,
        "pipe_segment_outflow": pipe_segment_outflow,
        "pipe_capacity_effective": pipe_capacity_effective,
        "pipe_flow_speed": pipe_flow_speed,
        "pipe_flow_rate": pipe_flow_rate,
        "pipe_surcharge_to_surface": pipe_surcharge_to_surface,
    }


def calculate_surface_spill(
    surface_storage: dict[str, float],
    *,
    step_minutes: float,
    constants: SimulationConstants,
) -> tuple[dict[str, float], dict[str, float]]:
    """Move excess road water to the next downstream surface node."""

    surface_spill_in = {drain_id: 0.0 for drain_id in DRAIN_IDS}
    surface_spill_out = {drain_id: 0.0 for drain_id in DRAIN_IDS}

    for index, drain_id in enumerate(DRAIN_IDS[:-1]):
        downstream_id = DRAIN_IDS[index + 1]
        surplus = max(0.0, surface_storage[drain_id] - constants.surface_spill_threshold)
        spill_capacity = constants.surface_spill_factor * step_minutes * (0.55 + surplus)
        spill = min(surplus, spill_capacity)
        surface_storage[drain_id] -= spill
        received = spill * constants.surface_spill_capture_factor
        surface_storage[downstream_id] += received
        surface_spill_out[drain_id] = spill
        surface_spill_in[downstream_id] = received

    return surface_spill_in, surface_spill_out


def run_step(
    states: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    step_minutes: float = 1.0,
) -> dict[str, dict[str, float | str]]:
    """Update all drain states for one edge-based network step."""

    next_states: dict[str, dict[str, float | str]] = {}
    rainfall = clamp01(rainfall)
    pipe_capacity = max(0.0, float(pipe_capacity))
    step_minutes = max(0.1, float(step_minutes))
    constants = DEFAULT_CONSTANTS
    resolved_blockages = resolve_blockage_configs(blockage_configs)
    downstream_backwater = calculate_downstream_backwater(states, blockage_configs)
    surface_storage, inlet_flow, inlet_capacity = calculate_initial_surface_and_inlet(
        states,
        resolved_blockages,
        rainfall=rainfall,
        step_minutes=step_minutes,
        constants=constants,
    )
    pipe_results = calculate_pipe_edge_flows(
        states,
        resolved_blockages,
        inlet_flow,
        downstream_backwater,
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        step_minutes=step_minutes,
        constants=constants,
    )

    for drain_id in DRAIN_IDS:
        surface_storage[drain_id] += pipe_results["pipe_surcharge_to_surface"][drain_id]

    surface_spill_in, surface_spill_out = calculate_surface_spill(
        surface_storage,
        step_minutes=step_minutes,
        constants=constants,
    )

    surface_recession_by_drain: dict[str, float] = {}
    for drain_id in DRAIN_IDS:
        surface_recession_factor = (
            constants.surface_relief_factor
            + (1.0 - rainfall) * constants.dry_surface_recession_factor
        )
        surface_recession = (
            surface_storage[drain_id] * surface_recession_factor * step_minutes
        )
        surface_recession = max(0.0, min(surface_recession, surface_storage[drain_id]))
        surface_storage[drain_id] = clamp01(surface_storage[drain_id] - surface_recession)
        surface_recession_by_drain[drain_id] = surface_recession

    for drain_id in DRAIN_IDS:
        current_state = states[drain_id]
        blockage = resolved_blockages[drain_id]
        previous_surface_water = clamp01(
            float(current_state.get("surface_water_level", 0.05))
        )
        previous_pipe_water = clamp01(float(current_state.get("pipe_water_level", 0.15)))
        previous_pipe_flow = clamp01(float(current_state.get("pipe_flow_speed", 0.0)))
        next_surface_water = clamp01(surface_storage[drain_id])
        next_pipe_water = clamp01(pipe_results["pipe_storage"][drain_id])
        pipe_flow_speed = clamp01(pipe_results["pipe_flow_speed"][drain_id])
        surface_water_delta = next_surface_water - previous_surface_water
        pipe_water_delta = next_pipe_water - previous_pipe_water
        pipe_flow_delta = pipe_flow_speed - previous_pipe_flow
        internal_blockage = float(blockage["internal_blockage"])
        level_flow_ratio = next_pipe_water / (pipe_flow_speed + 0.01)
        stagnation_score = (
            max(0.0, surface_water_delta) * 0.45
            + max(0.0, pipe_water_delta) * 0.75
            + max(0.0, -pipe_flow_delta) * 0.55
            + max(0.0, internal_blockage - pipe_flow_speed) * 0.20
        )

        next_states[drain_id] = {
            "drain_id": drain_id,
            "blockage_location": str(blockage["location"]),
            "blockage_severity": round(float(blockage["severity"]), 4),
            "surface_blockage": round(float(blockage["surface_blockage"]), 4),
            "internal_blockage": round(internal_blockage, 4),
            "inlet_capacity": round(inlet_capacity[drain_id], 4),
            "pipe_capacity_effective": round(
                pipe_results["pipe_capacity_effective"][drain_id],
                4,
            ),
            "surface_water_level": round(next_surface_water, 4),
            "inlet_flow": round(inlet_flow[drain_id], 4),
            "surface_recession": round(surface_recession_by_drain[drain_id], 4),
            "surface_spill_in": round(surface_spill_in[drain_id], 4),
            "surface_spill_out": round(surface_spill_out[drain_id], 4),
            "pipe_surcharge_to_surface": round(
                pipe_results["pipe_surcharge_to_surface"][drain_id],
                4,
            ),
            "upstream_pipe_flow": round(pipe_results["upstream_pipe_flow"][drain_id], 4),
            "downstream_backwater": round(downstream_backwater[drain_id], 4),
            "pipe_segment_outflow": round(
                pipe_results["pipe_segment_outflow"][drain_id],
                4,
            ),
            "pipe_water_level": round(next_pipe_water, 4),
            "pipe_flow_speed": round(pipe_flow_speed, 4),
            "pipe_flow_rate": round(pipe_results["pipe_flow_rate"][drain_id], 4),
            "surface_water_delta": round(surface_water_delta, 4),
            "pipe_water_delta": round(pipe_water_delta, 4),
            "pipe_flow_delta": round(pipe_flow_delta, 4),
            "level_flow_ratio": round(level_flow_ratio, 4),
            "stagnation_score": round(stagnation_score, 4),
            "remaining_surface_capacity": round(1.0 - next_surface_water, 4),
            "remaining_pipe_capacity": round(1.0 - next_pipe_water, 4),
            "sensor_status": str(current_state.get("sensor_status", "정상 배수")),
        }

    return next_states
