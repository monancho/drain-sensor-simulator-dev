from app import (
    build_dynamic_blockage_configs,
    resolve_dynamic_inputs,
    smooth_cycle_value,
)


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


def test_dynamic_blockage_configs_keep_manual_values_when_disabled():
    base_configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.55),
        "DRAIN_C": ("복합", 0.85),
    }

    adjusted = build_dynamic_blockage_configs(
        base_configs,
        enabled=False,
        time_step=10,
        amplitude=0.1,
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
        enabled=True,
        time_step=24,
        amplitude=0.2,
        speed=2.0,
    )

    assert adjusted["DRAIN_A"] == ("없음", 0.8)
    assert all(0.0 <= severity <= 1.0 for _, severity in adjusted.values())
    assert adjusted["DRAIN_B"][0] == "상부"
    assert adjusted["DRAIN_C"][0] == "내부"


def test_resolve_dynamic_inputs_preserves_manual_values_when_options_are_off():
    base_configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.55),
        "DRAIN_C": ("복합", 0.85),
    }

    rainfall, configs = resolve_dynamic_inputs(
        base_rainfall=0.7,
        base_blockage_configs=base_configs,
        time_step=5,
        rainfall_auto=False,
        rainfall_min=0.1,
        rainfall_max=0.9,
        rainfall_speed=2.0,
        blockage_wobble=False,
        blockage_amplitude=0.1,
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
        base_blockage_configs=base_configs,
        time_step=8,
        rainfall_auto=True,
        rainfall_min=0.2,
        rainfall_max=0.6,
        rainfall_speed=1.0,
        blockage_wobble=True,
        blockage_amplitude=0.05,
        blockage_speed=1.0,
    )

    assert 0.2 <= rainfall <= 0.6
    assert configs["DRAIN_A"] == ("없음", 0.0)
    assert configs["DRAIN_B"][0] == "상부"
    assert configs["DRAIN_B"][1] != 0.55
    assert all(0.0 <= severity <= 1.0 for _, severity in configs.values())
