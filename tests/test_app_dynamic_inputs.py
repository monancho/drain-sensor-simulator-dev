from app import (
    PRESET_VERSION,
    apply_preset_to_session_state,
    build_current_preset,
    build_dynamic_blockage_configs,
    build_latest_endpoint_url,
    build_runtime_sensor_payload,
    rainfall_variation_bounds,
    resolve_dynamic_inputs,
    smooth_cycle_value,
    validate_preset,
)
from sensor_model import attach_sensor_status
from simulation import DRAIN_IDS, initialize_drain_states


def test_smooth_cycle_value_is_deterministic_and_bounded():
    first = smooth_cycle_value(
        minimum=0.2,
        maximum=0.8,
        time_step=12,
        speed=1.4,
    )
    second = smooth_cycle_value(
        minimum=0.2,
        maximum=0.8,
        time_step=12,
        speed=1.4,
    )

    assert first == second
    assert 0.2 <= first <= 0.8


def test_smooth_cycle_value_changes_with_time():
    values = [
        smooth_cycle_value(
            minimum=0.1,
            maximum=0.9,
            time_step=step,
            speed=1.2,
        )
        for step in range(20)
    ]

    assert len(set(values)) > 1
    assert all(0.1 <= value <= 0.9 for value in values)


def test_rainfall_variation_bounds_clamp_to_unit_range():
    assert rainfall_variation_bounds(0.7, 0.2) == (0.5, 0.9)
    assert rainfall_variation_bounds(0.9, 0.2) == (0.7, 1.0)
    assert rainfall_variation_bounds(0.1, 0.2) == (0.0, 0.3)


def test_dynamic_blockage_configs_keep_manual_values_when_amplitude_is_zero():
    base_configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.55),
        "DRAIN_C": ("복합", 0.85),
    }

    adjusted = build_dynamic_blockage_configs(
        base_configs,
        time_step=10,
        amplitude=0.0,
        speed=1.0,
    )

    assert adjusted == base_configs


def test_dynamic_blockage_configs_are_bounded_and_ignore_none_location():
    base_configs = {
        "DRAIN_A": ("없음", 0.8),
        "DRAIN_B": ("상부", 0.98),
        "DRAIN_C": ("내부", 0.02),
    }

    adjusted = build_dynamic_blockage_configs(
        base_configs,
        time_step=24,
        amplitude=0.2,
        speed=2.0,
    )

    assert adjusted["DRAIN_A"] == ("없음", 0.8)
    assert all(0.0 <= severity <= 1.0 for _, severity in adjusted.values())
    assert adjusted["DRAIN_B"][0] == "상부"
    assert adjusted["DRAIN_C"][0] == "내부"


def test_resolve_dynamic_inputs_preserves_manual_values_when_variations_are_zero():
    base_configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.55),
        "DRAIN_C": ("복합", 0.85),
    }

    rainfall, configs = resolve_dynamic_inputs(
        base_rainfall=0.7,
        rainfall_variation=0.0,
        base_blockage_configs=base_configs,
        time_step=5,
        rainfall_speed=2.0,
        blockage_amplitude=0.0,
        blockage_speed=1.5,
    )

    assert rainfall == 0.7
    assert configs == base_configs


def test_resolve_dynamic_inputs_applies_enabled_dynamic_options():
    base_configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.55),
        "DRAIN_C": ("복합", 0.85),
    }

    rainfall, configs = resolve_dynamic_inputs(
        base_rainfall=0.7,
        rainfall_variation=0.2,
        base_blockage_configs=base_configs,
        time_step=8,
        rainfall_speed=1.0,
        blockage_amplitude=0.05,
        blockage_speed=1.0,
    )

    assert 0.5 <= rainfall <= 0.9
    assert configs["DRAIN_A"] == ("없음", 0.0)
    assert configs["DRAIN_B"][0] == "상부"
    assert configs["DRAIN_B"][1] != 0.55
    assert all(0.0 <= severity <= 1.0 for _, severity in configs.values())


def test_build_latest_endpoint_url_for_runtime_live_and_snapshot():
    assert (
        build_latest_endpoint_url(
            base_url="http://127.0.0.1:8765/",
            drain_id="DRAIN_B",
        )
        == "http://127.0.0.1:8765/drains/b/latest"
    )
    assert (
        build_latest_endpoint_url(
            base_url="http://127.0.0.1:8765",
            drain_id="DRAIN_C",
            detail=True,
        )
        == "http://127.0.0.1:8765/drains/c/latest/detail"
    )


def test_build_runtime_sensor_payload_includes_records_and_runtime_metadata():
    states = {
        drain_id: attach_sensor_status(initialize_drain_states()[drain_id])
        for drain_id in DRAIN_IDS
    }

    payload = build_runtime_sensor_payload(
        states,
        rainfall=0.7,
        pipe_capacity=1.0,
        time_step=3,
        generated_at="2026-06-17T00:00:00",
    )

    assert payload["mode"] == "runtime_snapshot"
    assert payload["runtime"]["producer"] == "streamlit"
    assert payload["runtime"]["time_step"] == 3
    assert payload["rainfall"] == 0.7
    assert len(payload["records"]) == 3
    assert {record["drain_id"] for record in payload["records"]} == set(DRAIN_IDS)


def test_build_current_preset_contains_portable_sidebar_settings():
    preset = build_current_preset(
        base_rainfall=0.7,
        rainfall_variation=0.2,
        rainfall_speed=1.1,
        pipe_capacity=1.0,
        blockage_configs={
            "DRAIN_A": ("없음", 0.0),
            "DRAIN_B": ("상부", 0.55),
            "DRAIN_C": ("복합", 0.85),
        },
        blockage_amplitude=0.05,
        blockage_speed=0.8,
        auto_interval_ms=1500,
    )

    assert preset["preset_version"] == PRESET_VERSION
    assert preset["rainfall"] == {"base": 0.7, "variation": 0.2, "speed": 1.1}
    assert preset["pipe"] == {"capacity": 1.0}
    assert preset["blockages"]["DRAIN_B"] == {"location": "상부", "severity": 0.55}
    assert preset["simulation"] == {"auto_interval_ms": 1500}


def test_validate_preset_accepts_valid_sidebar_settings():
    preset = build_current_preset(
        base_rainfall=0.6,
        rainfall_variation=0.1,
        rainfall_speed=2.0,
        pipe_capacity=1.2,
        blockage_configs={
            "DRAIN_A": ("없음", 0.0),
            "DRAIN_B": ("내부", 0.4),
            "DRAIN_C": ("복합", 0.8),
        },
        blockage_amplitude=0.04,
        blockage_speed=1.5,
        auto_interval_ms=2000,
    )

    normalized = validate_preset(preset)

    assert normalized["rainfall"]["base"] == 0.6
    assert normalized["blockages"]["DRAIN_B"]["location"] == "내부"
    assert normalized["simulation"]["auto_interval_ms"] == 2000


def test_validate_preset_rejects_invalid_values_without_partial_apply():
    preset = build_current_preset(
        base_rainfall=0.6,
        rainfall_variation=0.1,
        rainfall_speed=2.0,
        pipe_capacity=1.2,
        blockage_configs={
            "DRAIN_A": ("없음", 0.0),
            "DRAIN_B": ("내부", 0.4),
            "DRAIN_C": ("복합", 0.8),
        },
        blockage_amplitude=0.04,
        blockage_speed=1.5,
        auto_interval_ms=2000,
    )
    preset["blockages"]["DRAIN_B"]["location"] = "하부"

    try:
        validate_preset(preset)
    except ValueError as exc:
        assert "DRAIN_B.location" in str(exc)
    else:
        raise AssertionError("invalid preset location should fail validation")


def test_apply_preset_to_session_state_sets_widget_keys():
    preset = build_current_preset(
        base_rainfall=0.5,
        rainfall_variation=0.0,
        rainfall_speed=1.0,
        pipe_capacity=0.9,
        blockage_configs={
            "DRAIN_A": ("상부", 0.3),
            "DRAIN_B": ("없음", 0.0),
            "DRAIN_C": ("내부", 0.7),
        },
        blockage_amplitude=0.0,
        blockage_speed=0.8,
        auto_interval_ms=1200,
    )
    session_state = {}

    apply_preset_to_session_state(preset, session_state)

    assert session_state["rainfall_base"] == 0.5
    assert session_state["rainfall_variation"] == 0.0
    assert session_state["pipe_capacity"] == 0.9
    assert session_state["DRAIN_A_location"] == "상부"
    assert session_state["DRAIN_C_severity"] == 0.7
    assert session_state["auto_interval_ms"] == 1200
