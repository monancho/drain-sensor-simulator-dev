from sensor_api_service import (
    fetch_external_sensor_payload,
    normalize_sensor_request,
    simulate_sensor_records,
    simulate_sensor_snapshot,
    validate_sensor_payload,
)
from sensor_payload import SCHEMA_VERSION


def test_normalize_sensor_request_accepts_api_aliases():
    request = normalize_sensor_request(
        {
            "rainfall": 1.5,
            "pipe_capacity": 2.0,
            "steps": 2,
            "drains": {
                "DRAIN_A": {"location": "none", "severity": 1.0},
                "DRAIN_B": {"location": "surface", "severity": 0.8},
                "DRAIN_C": {"location": "internal", "severity": 0.6},
            },
        }
    )

    assert request["rainfall"] == 1.0
    assert request["pipe_capacity"] == 1.5
    assert request["drain_configs"]["DRAIN_A"] == ("없음", 0.0)
    assert request["drain_configs"]["DRAIN_B"] == ("상부", 0.8)
    assert request["drain_configs"]["DRAIN_C"] == ("내부", 0.6)


def test_simulate_sensor_snapshot_matches_api_contract():
    payload = simulate_sensor_snapshot(
        {
            "rainfall": 0.8,
            "pipe_capacity": 1.0,
            "steps": 4,
            "drains": {
                "DRAIN_A": {"location": "none", "severity": 0.0},
                "DRAIN_B": {"location": "surface", "severity": 0.9},
                "DRAIN_C": {"location": "internal", "severity": 0.9},
            },
        },
        generated_at="2026-06-15T12:00:00",
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["simulation"] == {"steps": 4, "step_minutes": 1.0}
    assert len(payload["readings"]) == 3
    assert validate_sensor_payload(payload) == payload

    records = simulate_sensor_records(
        {"rainfall": 0.8, "pipe_capacity": 1.0, "steps": 4},
        generated_at="2026-06-15T12:00:00",
    )
    assert len(records) == 3
    assert "surface_water_level" in records[0]


def test_validate_sensor_payload_rejects_wrong_schema():
    try:
        validate_sensor_payload({"schema_version": "wrong", "readings": []})
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_fetch_external_sensor_payload_uses_same_validator(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def read(self):
            return (
                b'{"schema_version":"virtual-drain-sensor.v1",'
                b'"readings":[{"sensor_id":"SIM-DRAIN_A","drain_id":"DRAIN_A",'
                b'"observed_at":"2026-06-15T12:00:00",'
                b'"measurements":{"surface_water_level":0,"inlet_flow":0,'
                b'"pipe_water_level":0,"pipe_flow_speed":0,"pipe_flow_rate":0}}]}'
            )

    def fake_urlopen(request, timeout):
        assert timeout == 5.0
        assert request.headers["Accept"] == "application/json"
        return FakeResponse()

    monkeypatch.setattr("sensor_api_service.urlopen", fake_urlopen)

    payload = fetch_external_sensor_payload("http://example.test/sensors")
    assert payload["schema_version"] == SCHEMA_VERSION
