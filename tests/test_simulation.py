from itertools import product
from statistics import mean

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
    "surface_spill_in",
    "surface_spill_out",
    "pipe_surcharge_to_surface",
    "upstream_pipe_flow",
    "downstream_backwater",
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


def run_history(
    configs,
    *,
    steps=36,
    pipe_capacity=1.0,
    rainfall_by_step=None,
):
    states = initialize_drain_states()
    history = []

    for step_index in range(steps):
        rainfall = (
            rainfall_by_step(step_index)
            if rainfall_by_step is not None
            else 1.0
        )
        states = run_step(
            states,
            rainfall=rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=configs,
            step_minutes=1,
        )
        history.append(states)

    return history


def storm_then_dry(step_index):
    return 1.0 if step_index < 24 else 0.0


def build_configs(locations, severities):
    return {
        drain_id: (location, 0.0 if location == "없음" else severity)
        for drain_id, location, severity in zip(
            DRAIN_IDS,
            locations,
            severities,
            strict=True,
        )
    }


def values(history, drain_id, field):
    return [float(step[drain_id][field]) for step in history]


def peak(history, drain_id, field):
    return max(values(history, drain_id, field))


def expected_blockages(location, severity):
    if location == "없음":
        return 0.0, 0.0
    if location == "상부":
        return severity, 0.0
    if location == "내부":
        return 0.0, severity
    return severity, severity


def effective_pipe_capacity(pipe_capacity, internal_blockage, downstream_backwater=0.0):
    local_capacity = pipe_capacity * ((1.0 - internal_blockage) ** 1.35)
    backwater_capacity = 1.0 - downstream_backwater * 0.72
    return max(0.0, min(1.0, local_capacity * backwater_capacity))


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


def test_normalized_pipe_flow_speed_does_not_clip_too_early():
    states = run_network(("없음", "없음", "없음"), severity=0.0, steps=12)

    assert states["DRAIN_A"]["pipe_flow_speed"] < states["DRAIN_B"]["pipe_flow_speed"]
    assert states["DRAIN_B"]["pipe_flow_speed"] < states["DRAIN_C"]["pipe_flow_speed"]
    assert states["DRAIN_C"]["pipe_flow_speed"] < 0.90
    assert states["DRAIN_C"]["pipe_flow_speed"] > 0.55


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


def test_downstream_internal_blockage_backs_up_upstream_pipe_levels():
    normal = run_network(("없음", "없음", "없음"), severity=0.0, steps=12)
    c_blocked = run_network(("없음", "없음", "내부"), severity=1.0, steps=12)

    assert c_blocked["DRAIN_A"]["downstream_backwater"] > 0.20
    assert c_blocked["DRAIN_B"]["downstream_backwater"] > 0.50
    assert c_blocked["DRAIN_A"]["pipe_water_level"] > normal["DRAIN_A"]["pipe_water_level"]
    assert c_blocked["DRAIN_B"]["pipe_water_level"] > normal["DRAIN_B"]["pipe_water_level"]
    assert c_blocked["DRAIN_A"]["surface_blockage"] == 0.0
    assert c_blocked["DRAIN_B"]["surface_blockage"] == 0.0


def test_middle_internal_blockage_raises_ab_levels_and_spills_to_c_inlet():
    normal = run_network(("없음", "없음", "없음"), severity=0.0, steps=30)
    b_blocked = run_network(("없음", "내부", "없음"), severity=1.0, steps=30)

    assert b_blocked["DRAIN_A"]["downstream_backwater"] > 0.50
    assert b_blocked["DRAIN_A"]["pipe_water_level"] > normal["DRAIN_A"]["pipe_water_level"]
    assert b_blocked["DRAIN_B"]["pipe_water_level"] > normal["DRAIN_B"]["pipe_water_level"]
    assert b_blocked["DRAIN_A"]["surface_water_level"] >= 0.70
    assert b_blocked["DRAIN_B"]["surface_water_level"] >= 0.70
    assert b_blocked["DRAIN_C"]["surface_blockage"] == 0.0
    assert b_blocked["DRAIN_C"]["internal_blockage"] == 0.0
    assert b_blocked["DRAIN_C"]["surface_spill_in"] > 0.0
    assert b_blocked["DRAIN_C"]["inlet_flow"] > normal["DRAIN_C"]["inlet_flow"]


def test_upstream_surface_blockage_does_not_block_downstream_pipe_network():
    normal = run_network(("없음", "없음", "없음"), severity=0.0, steps=12)
    a_surface_blocked = run_network(("상부", "없음", "없음"), severity=1.0, steps=12)

    assert a_surface_blocked["DRAIN_A"]["surface_water_level"] > normal["DRAIN_A"]["surface_water_level"]
    assert a_surface_blocked["DRAIN_A"]["inlet_flow"] < normal["DRAIN_A"]["inlet_flow"]
    assert a_surface_blocked["DRAIN_B"]["internal_blockage"] == 0.0
    assert a_surface_blocked["DRAIN_C"]["internal_blockage"] == 0.0
    assert a_surface_blocked["DRAIN_B"]["pipe_flow_speed"] > 0.05
    assert a_surface_blocked["DRAIN_C"]["pipe_flow_speed"] > 0.05


def test_all_internal_blockage_can_surcharge_to_surface_flooding():
    states = run_network(("내부", "내부", "내부"), severity=1.0, steps=30)

    assert states["DRAIN_A"]["surface_water_level"] >= 0.80
    assert states["DRAIN_B"]["surface_water_level"] >= 0.80
    assert states["DRAIN_C"]["surface_water_level"] >= 0.40
    assert states["DRAIN_A"]["pipe_surcharge_to_surface"] > 0.0
    assert states["DRAIN_B"]["pipe_surcharge_to_surface"] > 0.0
    assert states["DRAIN_C"]["pipe_surcharge_to_surface"] > 0.0


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


def test_temporal_matrix_keeps_sensor_graph_values_stable():
    violations = []

    for locations in product(LOCATIONS, repeat=3):
        for severities in product(SEVERITY_LEVELS, repeat=3):
            configs = build_configs(locations, severities)

            for pipe_capacity in PIPE_CAPACITY_LEVELS:
                history = run_history(
                    configs,
                    steps=36,
                    pipe_capacity=pipe_capacity,
                    rainfall_by_step=storm_then_dry,
                )

                for step_index, states in enumerate(history):
                    for drain_id in DRAIN_IDS:
                        state = states[drain_id]

                        for field in BOUNDED_FIELDS:
                            value = float(state[field])
                            if not 0.0 <= value <= 1.0:
                                violations.append(
                                    ("bounded", step_index, drain_id, field, value)
                                )

                        if float(state["pipe_flow_speed"]) >= 0.98:
                            violations.append(
                                (
                                    "pipe speed clipped",
                                    step_index,
                                    locations,
                                    severities,
                                    pipe_capacity,
                                    drain_id,
                                    state,
                                )
                            )

                for drain_id in DRAIN_IDS:
                    surface_values = values(history, drain_id, "surface_water_level")
                    dry_start = mean(surface_values[24:27])
                    dry_end = mean(surface_values[-3:])

                    if surface_values[-1] > max(surface_values) + 0.0001:
                        violations.append(("surface final above peak", drain_id))

                    if surface_values[-1] > surface_values[23] + 0.02:
                        violations.append(
                            (
                                "surface rose after rain stopped",
                                locations,
                                severities,
                                pipe_capacity,
                                drain_id,
                                surface_values[23],
                                surface_values[-1],
                            )
                        )

                    if dry_start > 0.03 and dry_end > dry_start + 0.01:
                        violations.append(
                            (
                                "dry period did not recede",
                                locations,
                                severities,
                                pipe_capacity,
                                drain_id,
                                dry_start,
                                dry_end,
                            )
                        )

    assert violations == []


def test_representative_temporal_sensor_graph_shapes():
    clear = {drain_id: ("없음", 0.0) for drain_id in DRAIN_IDS}
    b_surface_blocked = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 1.0),
        "DRAIN_C": ("없음", 0.0),
    }
    b_internal_blocked = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("내부", 1.0),
        "DRAIN_C": ("없음", 0.0),
    }
    c_internal_blocked = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("없음", 0.0),
        "DRAIN_C": ("내부", 1.0),
    }

    clear_history = run_history(clear, steps=36, rainfall_by_step=storm_then_dry)
    assert peak(clear_history, "DRAIN_A", "surface_water_level") < 0.05
    assert peak(clear_history, "DRAIN_B", "surface_water_level") < 0.05
    assert peak(clear_history, "DRAIN_C", "surface_water_level") < 0.05
    assert peak(clear_history, "DRAIN_A", "pipe_flow_speed") < peak(
        clear_history,
        "DRAIN_B",
        "pipe_flow_speed",
    )
    assert peak(clear_history, "DRAIN_B", "pipe_flow_speed") < peak(
        clear_history,
        "DRAIN_C",
        "pipe_flow_speed",
    )
    assert peak(clear_history, "DRAIN_C", "pipe_flow_speed") < 0.90

    b_surface_history = run_history(
        b_surface_blocked,
        steps=36,
        rainfall_by_step=storm_then_dry,
    )
    assert values(b_surface_history, "DRAIN_B", "surface_water_level")[23] > 0.75
    assert values(b_surface_history, "DRAIN_B", "surface_water_level")[-1] < 0.50
    assert peak(b_surface_history, "DRAIN_B", "inlet_flow") <= 0.001
    assert peak(b_surface_history, "DRAIN_B", "pipe_flow_speed") > 0.25
    assert peak(b_surface_history, "DRAIN_C", "surface_spill_in") > 0.03

    b_internal_history = run_history(
        b_internal_blocked,
        steps=36,
        rainfall_by_step=storm_then_dry,
    )
    assert values(b_internal_history, "DRAIN_A", "pipe_water_level")[23] > 0.90
    assert values(b_internal_history, "DRAIN_B", "pipe_water_level")[23] > 0.90
    assert peak(b_internal_history, "DRAIN_A", "pipe_surcharge_to_surface") > 0.08
    assert peak(b_internal_history, "DRAIN_A", "downstream_backwater") > 0.80
    assert peak(b_internal_history, "DRAIN_C", "surface_spill_in") > 0.03
    assert peak(b_internal_history, "DRAIN_B", "pipe_flow_speed") <= 0.001

    c_internal_history = run_history(
        c_internal_blocked,
        steps=36,
        rainfall_by_step=storm_then_dry,
    )
    assert peak(c_internal_history, "DRAIN_A", "downstream_backwater") > 0.60
    assert peak(c_internal_history, "DRAIN_B", "downstream_backwater") > 0.80
    assert values(c_internal_history, "DRAIN_B", "surface_water_level")[23] > 0.90
    assert values(c_internal_history, "DRAIN_C", "surface_water_level")[23] > 0.90
    assert peak(c_internal_history, "DRAIN_C", "pipe_flow_speed") <= 0.001


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
                        pipe_capacity,
                        internal_blockage,
                        values["downstream_backwater"],
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
