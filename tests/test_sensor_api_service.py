from sensor_api_service import (
    available_scenarios,
    fetch_external_sensor_payload,
    normalize_sensor_request,
    simulate_sensor_records,
    simulate_sensor_snapshot,
    simulate_sensor_timeseries,
    validate_sensor_payload,
    validate_sensor_timeseries_payload,
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


def records_for(payload, drain_id):
    return [record for record in payload["records"] if record["drain_id"] == drain_id]


def test_simulate_sensor_timeseries_has_reusable_contract():
    payload = simulate_sensor_timeseries(
        {"scenario": "surface_blockage", "steps": 8},
        generated_at="2026-06-15T12:00:00",
    )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["scenario"]["id"] == "surface_blockage"
    assert payload["scenario"]["steps"] == 8
    assert len(payload["snapshots"]) == 8
    assert len(payload["records"]) == 24
    assert validate_sensor_timeseries_payload(payload) == payload
    assert "surface_blockage" in {
        scenario["id"]
        for scenario in available_scenarios()
    }

    first_snapshot = payload["snapshots"][0]
    assert first_snapshot["simulation"]["scenario_id"] == "surface_blockage"
    assert first_snapshot["readings"][0]["measurements"]["surface_water_level"] >= 0.0
    assert "stagnation_score" in first_snapshot["readings"][0]["derived"]


def test_rain_stops_scenario_reduces_surface_water_after_peak():
    payload = simulate_sensor_timeseries(
        {"scenario": "rain_stops", "steps": 30},
        generated_at="2026-06-15T12:00:00",
    )
    drain_b_records = records_for(payload, "DRAIN_B")
    surface_levels = [
        float(record["surface_water_level"])
        for record in drain_b_records
    ]

    assert max(surface_levels) > 0.80
    assert surface_levels[-1] < max(surface_levels)
    assert float(drain_b_records[-1]["surface_recession"]) > 0.0


def test_timeseries_surface_and_internal_patterns_remain_distinct():
    surface_payload = simulate_sensor_timeseries(
        {"scenario": "surface_blockage", "steps": 24},
        generated_at="2026-06-15T12:00:00",
    )
    internal_payload = simulate_sensor_timeseries(
        {"scenario": "internal_stagnation", "steps": 24},
        generated_at="2026-06-15T12:00:00",
    )

    surface_last = records_for(surface_payload, "DRAIN_B")[-1]
    internal_last = records_for(internal_payload, "DRAIN_C")[-1]

    assert surface_last["blockage_location"] == "상부"
    assert float(surface_last["surface_water_level"]) > 0.50
    assert float(surface_last["inlet_flow"]) <= 0.01
    assert float(surface_last["internal_blockage"]) == 0.0

    assert internal_last["blockage_location"] == "내부"
    assert float(internal_last["pipe_water_level"]) >= 0.90
    assert float(internal_last["pipe_flow_speed"]) <= 0.05
    assert float(internal_last["surface_blockage"]) == 0.0
    assert "정체" in internal_last["status"]


def test_network_passthrough_keeps_upstream_pipe_flow_under_surface_blockage():
    payload = simulate_sensor_timeseries(
        {"scenario": "network_passthrough", "steps": 18},
        generated_at="2026-06-15T12:00:00",
    )
    drain_b_last = records_for(payload, "DRAIN_B")[-1]
    drain_c_last = records_for(payload, "DRAIN_C")[-1]

    assert drain_b_last["blockage_location"] == "상부"
    assert drain_c_last["blockage_location"] == "상부"
    assert float(drain_b_last["upstream_pipe_flow"]) > 0.05
    assert float(drain_c_last["upstream_pipe_flow"]) > 0.05
    assert float(drain_b_last["pipe_flow_speed"]) > 0.05
    assert float(drain_c_last["pipe_flow_speed"]) > 0.05


def test_default_realism_keeps_timeseries_deterministic_values():
    request = {"scenario": "surface_blockage", "steps": 6}
    clean = simulate_sensor_timeseries(
        request,
        generated_at="2026-06-15T12:00:00",
    )
    explicit_default = simulate_sensor_timeseries(
        {**request, "realism": {}},
        generated_at="2026-06-15T12:00:00",
    )

    assert "realism" not in clean
    assert clean["records"] == explicit_default["records"]
    assert clean["records"][0]["quality_flags"] == "mock"


def test_seeded_noise_timeseries_is_reproducible():
    request = {
        "scenario": "surface_blockage",
        "steps": 8,
        "realism": {
            "noise": True,
            "noise_scale": 0.05,
            "seed": 123,
        },
    }
    first = simulate_sensor_timeseries(request, generated_at="2026-06-15T12:00:00")
    second = simulate_sensor_timeseries(request, generated_at="2026-06-15T12:00:00")
    clean = simulate_sensor_timeseries(
        {"scenario": "surface_blockage", "steps": 8},
        generated_at="2026-06-15T12:00:00",
    )

    assert first["records"] == second["records"]
    assert first["records"] != clean["records"]
    assert first["realism"]["seed"] == 123
    assert any("noisy" in record["quality_flags"] for record in first["records"])


def test_snapshot_missing_realism_marks_null_measurements():
    payload = simulate_sensor_snapshot(
        {
            "rainfall": 0.8,
            "steps": 4,
            "realism": {
                "missing": True,
                "missing_rate": 1.0,
                "seed": 7,
            },
        },
        generated_at="2026-06-15T12:00:00",
    )

    assert validate_sensor_payload(payload) == payload
    assert payload["realism"]["missing"]["enabled"] is True
    for reading in payload["readings"]:
        assert all(value is None for value in reading["measurements"].values())
        assert "missing" in reading["quality_flags"]
        assert "missing" in reading["measurement_quality"]["surface_water_level"]


def test_realism_quality_metadata_includes_missing_stale_spike_stuck_and_delay():
    payload = simulate_sensor_timeseries(
        {
            "scenario": "surface_blockage",
            "steps": 4,
            "realism": {
                "missing": True,
                "missing_rate": 1.0,
                "stale": True,
                "stale_rate": 1.0,
                "spike": True,
                "spike_rate": 1.0,
                "spike_magnitude": 0.3,
                "stuck": True,
                "stuck_drain_id": "DRAIN_C",
                "stuck_field": "pipe_flow_speed",
                "delay": True,
                "delay_steps": 1,
                "seed": 11,
            },
        },
        generated_at="2026-06-15T12:00:00",
    )
    flags = set()
    for record in payload["records"]:
        flags.update(record["quality_flags"].split("+"))

    assert {"mock", "missing", "stale", "spike", "stuck", "delayed"} <= flags
    assert any(
        "stuck" in record["pipe_flow_speed_quality"]
        for record in records_for(payload, "DRAIN_C")
    )


def test_realism_does_not_break_surface_and_internal_policy_statuses():
    surface_payload = simulate_sensor_timeseries(
        {
            "scenario": "surface_blockage",
            "steps": 24,
            "realism": {
                "noise": True,
                "noise_scale": 0.01,
                "seed": 3,
            },
        },
        generated_at="2026-06-15T12:00:00",
    )
    internal_payload = simulate_sensor_timeseries(
        {
            "scenario": "internal_stagnation",
            "steps": 24,
            "realism": {
                "noise": True,
                "noise_scale": 0.01,
                "seed": 3,
            },
        },
        generated_at="2026-06-15T12:00:00",
    )

    surface_last = records_for(surface_payload, "DRAIN_B")[-1]
    internal_last = records_for(internal_payload, "DRAIN_C")[-1]

    assert surface_last["blockage_location"] == "상부"
    assert float(surface_last["internal_blockage"]) == 0.0
    assert surface_last["status"] == "상부 유입 막힘 의심"
    assert internal_last["blockage_location"] == "내부"
    assert float(internal_last["surface_blockage"]) == 0.0
    assert internal_last["status"] == "내부 정체 의심"
