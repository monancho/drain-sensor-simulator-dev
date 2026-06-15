import json

from sensor_model import attach_sensor_status
from sensor_payload import (
    SCHEMA_VERSION,
    build_mock_sensor_payload,
    build_mock_sensor_records,
    dumps_mock_sensor_payload,
    dumps_mock_sensor_records_jsonl,
)
from simulation import DRAIN_IDS, initialize_drain_states, run_step


def build_states():
    states = initialize_drain_states()
    configs = {
        "DRAIN_A": ("없음", 0.0),
        "DRAIN_B": ("상부", 0.75),
        "DRAIN_C": ("내부", 0.80),
    }
    for _ in range(4):
        states = run_step(
            states,
            rainfall=0.8,
            pipe_capacity=1.0,
            blockage_configs=configs,
            step_minutes=1,
        )
    return {
        drain_id: attach_sensor_status(state)
        for drain_id, state in states.items()
    }


def test_mock_sensor_payload_has_stable_schema():
    payload = build_mock_sensor_payload(
        build_states(),
        rainfall=0.8,
        pipe_capacity=1.0,
        time_step=4,
        elapsed_minutes=4,
        generated_at="2026-06-15T12:00:00",
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["source"] == "drain-sensor-simulator"
    assert payload["inputs"] == {"rainfall": 0.8, "pipe_capacity": 1.0}
    assert payload["network"]["nodes"] == [*DRAIN_IDS, "OUTFALL"]
    assert len(payload["readings"]) == 3

    first_reading = payload["readings"][0]
    assert first_reading["sensor_id"] == "SIM-DRAIN_A"
    assert first_reading["quality"] == "mock"
    assert set(first_reading["measurements"]) == {
        "surface_water_level",
        "inlet_flow",
        "pipe_water_level",
        "pipe_flow_speed",
        "pipe_flow_rate",
    }
    assert "stagnation_score" in first_reading["derived"]
    assert "surface_recession" in first_reading["derived"]


def test_mock_sensor_records_are_flat_and_serializable():
    payload = build_mock_sensor_payload(
        build_states(),
        rainfall=0.8,
        pipe_capacity=1.0,
        time_step=4,
        elapsed_minutes=4,
        generated_at="2026-06-15T12:00:00",
    )
    records = build_mock_sensor_records(payload)

    assert len(records) == 3
    assert records[1]["sensor_id"] == "SIM-DRAIN_B"
    assert records[1]["blockage_location"] == "상부"
    assert "pipe_flow_speed" in records[1]
    assert "remaining_pipe_capacity" in records[1]

    parsed_payload = json.loads(dumps_mock_sensor_payload(payload))
    parsed_records = [
        json.loads(line)
        for line in dumps_mock_sensor_records_jsonl(records).splitlines()
    ]

    assert parsed_payload["schema_version"] == SCHEMA_VERSION
    assert parsed_records[2]["sensor_id"] == "SIM-DRAIN_C"
