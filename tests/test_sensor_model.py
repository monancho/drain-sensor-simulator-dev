from sensor_model import interpret_sensor_status


def base_state(**kwargs):
    state = {
        "surface_water_level": 0.05,
        "inlet_flow": 0.07,
        "pipe_water_level": 0.20,
        "pipe_flow_speed": 0.40,
        "surface_blockage": 0.0,
        "internal_blockage": 0.0,
        "surface_water_delta": 0.0,
        "pipe_water_delta": 0.0,
    }
    state.update(kwargs)
    return state


def test_high_level_high_flow_is_drainage_in_progress():
    status = interpret_sensor_status(
        base_state(pipe_water_level=0.78, pipe_flow_speed=0.80)
    )
    assert status == "배수 진행 중"


def test_high_pipe_level_low_flow_is_internal_stagnation():
    status = interpret_sensor_status(
        base_state(pipe_water_level=0.80, pipe_flow_speed=0.10)
    )
    assert status == "내부 정체 의심"


def test_surface_pooling_low_inlet_is_surface_blockage():
    status = interpret_sensor_status(
        base_state(
            surface_water_level=0.75,
            inlet_flow=0.01,
            surface_blockage=0.85,
            surface_water_delta=0.10,
        )
    )
    assert status == "상부 유입 막힘 의심"


def test_complex_pattern_has_priority():
    status = interpret_sensor_status(
        base_state(
            surface_water_level=0.75,
            pipe_water_level=0.75,
            pipe_flow_speed=0.10,
            surface_blockage=0.9,
            internal_blockage=0.9,
        )
    )
    assert status == "복합 막힘 의심"
