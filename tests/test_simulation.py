from itertools import product

from sensor_model import attach_sensor_status
from simulation import DRAIN_IDS, initialize_drain_states, resolve_blockage, run_step

LOCATIONS = ("없음", "상부", "내부", "복합")
RAINFALL_LEVELS = (0.0, 0.5, 1.0)
PIPE_CAPACITY_LEVELS = (0.2, 0.85, 1.5)
SEVERITY_LEVELS = (0.0, 0.5, 1.0)
BOUNDED_FIELDS = (
    "surface_water_level",
    "inlet_flow",
    "surface_recession",
    "upstream_pipe_flow",
    "pipe_segment_outflow",
    "pipe_water_level",
    "pipe_flow_speed",
    "pipe_flow_rate",
    "pipe_capacity_effective",
    "stagnation_score",
    "surface_blockage",
    "internal_blockage",
)


def run_many(location, severity, steps=12):
    states = initialize_drain_states()
    configs = {
        "DRAIN_A": (location, severity),
        "DRAIN_B": ("없음", 0.0),
        "DRAIN_C": ("없음", 0.0),
    }

    for _ in range(steps):
        states = run_step(
            states,
            rainfall=0.8,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )

    return states["DRAIN_A"]


def run_network(locations, severity=0.9, steps=12):
    states = initialize_drain_states()
    configs = {
        drain_id: (location, 0.0 if location == "없음" else severity)
        for drain_id, location in zip(DRAIN_IDS, locations, strict=True)
    }

    for _ in range(steps):
        states = run_step(
            states,
            rainfall=1.0,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )

    return states


def expected_blockages(location, severity):
    if location == "없음":
        return 0.0, 0.0
    if location == "상부":
        return severity, 0.0
    if location == "내부":
        return 0.0, severity
    return severity, severity


def effective_pipe_capacity(pipe_capacity, internal_blockage):
    return max(0.0, min(1.0, pipe_capacity * (1.0 - internal_blockage)))


def test_resolve_blockage_mapping():
    assert resolve_blockage("없음", 0.9) == (0.0, 0.0)
    assert resolve_blockage("상부", 0.8)[0] == 0.8
    assert resolve_blockage("내부", 0.8)[1] == 0.8
    assert resolve_blockage("복합", 0.8) == (0.8, 0.8)


def test_surface_blockage_increases_surface_water_and_reduces_inlet():
    normal = run_many("없음", 0.0)
    surface_blocked = run_many("상부", 0.9)

    assert surface_blocked["surface_water_level"] > normal["surface_water_level"]
    assert surface_blocked["inlet_flow"] < normal["inlet_flow"]


def test_internal_blockage_increases_pipe_level_and_reduces_flow():
    normal = run_many("없음", 0.0)
    internal_blocked = run_many("내부", 0.9)

    assert internal_blocked["pipe_water_level"] > normal["pipe_water_level"]
    assert internal_blocked["pipe_flow_speed"] < normal["pipe_flow_speed"]


def test_complex_blockage_has_surface_and_pipe_effects():
    complex_blocked = run_many("복합", 0.9)

    assert complex_blocked["surface_water_level"] > 0.2
    assert complex_blocked["pipe_water_level"] > 0.15
    assert complex_blocked["pipe_flow_speed"] < 0.4


def test_surface_blocked_downstream_drains_still_pass_upstream_pipe_flow():
    states = initialize_drain_states()
    configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.95),
        "DRAIN_C": ("상부", 0.95),
    }

    for _ in range(8):
        states = run_step(
            states,
            rainfall=1.0,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )

    assert states["DRAIN_B"]["inlet_flow"] < states["DRAIN_A"]["inlet_flow"]
    assert states["DRAIN_C"]["inlet_flow"] < states["DRAIN_A"]["inlet_flow"]
    assert states["DRAIN_B"]["upstream_pipe_flow"] > 0.0
    assert states["DRAIN_C"]["upstream_pipe_flow"] > 0.0
    assert states["DRAIN_B"]["pipe_flow_speed"] > 0.05
    assert states["DRAIN_C"]["pipe_flow_speed"] > 0.05


def test_surface_water_recedes_after_rain_stops_even_when_surface_blocked():
    states = initialize_drain_states()
    configs = {
        "DRAIN_A": ("상부", 1.0),
        "DRAIN_B": ("없음", 0.0),
        "DRAIN_C": ("없음", 0.0),
    }

    for _ in range(12):
        states = run_step(
            states,
            rainfall=1.0,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )

    surface_after_rain = states["DRAIN_A"]["surface_water_level"]

    for _ in range(20):
        states = run_step(
            states,
            rainfall=0.0,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )

    assert surface_after_rain > 0.55
    assert states["DRAIN_A"]["surface_water_level"] < surface_after_rain
    assert states["DRAIN_A"]["surface_recession"] > 0.0


def test_all_drain_location_combinations_follow_expected_sensor_patterns():
    for locations in product(LOCATIONS, repeat=3):
        states = run_network(locations)

        for drain_id, location in zip(DRAIN_IDS, locations, strict=True):
            state = states[drain_id]

            for field in BOUNDED_FIELDS:
                assert 0.0 <= state[field] <= 1.0

            if location in ("상부", "복합"):
                assert state["surface_water_level"] >= 0.55
                assert state["inlet_flow"] <= 0.02

            if location in ("내부", "복합"):
                assert state["pipe_capacity_effective"] <= 0.11

            if location == "상부" and state["upstream_pipe_flow"] > 0.01:
                assert state["pipe_segment_outflow"] >= state["upstream_pipe_flow"] * 0.85
                assert state["pipe_flow_speed"] > 0.05


def test_slider_boundary_matrix_has_no_policy_violations():
    violations = []

    for locations in product(LOCATIONS, repeat=3):
        for severities in product(SEVERITY_LEVELS, repeat=3):
            for rainfall, pipe_capacity in product(RAINFALL_LEVELS, PIPE_CAPACITY_LEVELS):
                states = initialize_drain_states()
                configs = {
                    drain_id: (location, 0.0 if location == "없음" else severity)
                    for drain_id, location, severity in zip(
                        DRAIN_IDS, locations, severities, strict=True
                    )
                }

                for _ in range(12):
                    states = run_step(
                        states,
                        rainfall=rainfall,
                        pipe_capacity=pipe_capacity,
                        blockage_configs=configs,
                        step_minutes=1,
                    )

                states = {
                    drain_id: attach_sensor_status(state)
                    for drain_id, state in states.items()
                }

                for drain_id, location, severity in zip(
                    DRAIN_IDS, locations, severities, strict=True
                ):
                    state = states[drain_id]
                    values = {field: float(state[field]) for field in BOUNDED_FIELDS}
                    surface_blockage, internal_blockage = expected_blockages(
                        location, severity
                    )
                    expected_capacity = effective_pipe_capacity(
                        pipe_capacity, internal_blockage
                    )

                    for field, value in values.items():
                        if not 0.0 <= value <= 1.0:
                            violations.append((field, value, locations, severities))

                    if abs(values["surface_blockage"] - surface_blockage) > 0.0001:
                        violations.append(("surface mapping", drain_id, location, severity))

                    if abs(values["internal_blockage"] - internal_blockage) > 0.0001:
                        violations.append(("internal mapping", drain_id, location, severity))

                    if abs(values["pipe_capacity_effective"] - expected_capacity) > 0.0001:
                        violations.append(
                            ("capacity mapping", drain_id, pipe_capacity, internal_blockage)
                        )

                    if rainfall == 0.0 and values["surface_water_level"] > 0.05:
                        violations.append(("dry created surface water", drain_id, values))

                    if (
                        rainfall == 1.0
                        and location in ("상부", "복합")
                        and severity == 1.0
                        and (
                            values["surface_water_level"] < 0.55
                            or values["inlet_flow"] > 0.001
                        )
                    ):
                        violations.append(("full surface blockage pattern", drain_id, values))

                    if location == "상부" and values["upstream_pipe_flow"] > 0.01:
                        minimum_outflow = (
                            values["upstream_pipe_flow"]
                            * max(0.0, min(1.0, pipe_capacity))
                            * 0.85
                        )
                        if values["pipe_segment_outflow"] < minimum_outflow:
                            violations.append(("surface throughflow", drain_id, values))

                    if (
                        values["pipe_water_level"] >= 0.70
                        and values["pipe_flow_speed"] >= 0.55
                        and "정체" in str(state["sensor_status"])
                    ):
                        violations.append(("high level high flow misread", drain_id, state))

    assert violations == []
