import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api import SensorAPIHandler
from runtime_state import write_runtime_snapshot
from sensor_payload import SCHEMA_VERSION

LIVE_PROFILES = (
    "normal_drain",
    "storm_pulse",
    "surface_debris_live",
    "internal_stagnation_live",
    "mixed_unstable",
)
LIVE_BOUNDED_FIELDS = (
    "surface_water_level",
    "inlet_flow",
    "pipe_water_level",
    "pipe_flow_speed",
    "pipe_flow_rate",
)


def runtime_payload():
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "drain-sensor-simulator",
        "mode": "runtime_snapshot",
        "generated_at": "2026-06-17T00:00:00",
        "rainfall": 0.72,
        "pipe_capacity": 1.0,
        "time_step": 12,
        "elapsed_minutes": 12,
        "runtime": {
            "producer": "streamlit",
            "generated_at": "2026-06-17T00:00:00",
            "time_step": 12,
            "elapsed_minutes": 12,
        },
        "records": [
            {"drain_id": "DRAIN_A", "surface_water_level": 0.1, "status": "정상 배수"},
            {"drain_id": "DRAIN_B", "surface_water_level": 0.6, "status": "상부 유입 막힘 의심"},
            {"drain_id": "DRAIN_C", "surface_water_level": 0.2, "status": "정상 배수"},
        ],
    }


def run_test_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SensorAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def get_json(url):
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_sensor_api_health_and_snapshot_endpoints():
    server, base_url = run_test_server()
    try:
        health = get_json(f"{base_url}/health")
        snapshot = get_json(
            f"{base_url}/api/v1/sensors/snapshot"
            "?rainfall=1&steps=3&drain_b_location=surface&drain_b_severity=1"
        )

        assert health == {"status": "ok", "schema_version": SCHEMA_VERSION}
        assert snapshot["schema_version"] == SCHEMA_VERSION
        assert snapshot["simulation"]["steps"] == 3
        assert len(snapshot["readings"]) == 3
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_records_and_post_simulate_endpoints():
    server, base_url = run_test_server()
    try:
        records = get_json(f"{base_url}/api/v1/sensors/records?steps=2")
        simulated = post_json(
            f"{base_url}/api/v1/sensors/simulate",
            {
                "rainfall": 0.8,
                "pipe_capacity": 1.0,
                "steps": 4,
                "drains": {
                    "DRAIN_A": {"location": "none", "severity": 0.0},
                    "DRAIN_B": {"location": "surface", "severity": 1.0},
                    "DRAIN_C": {"location": "internal", "severity": 1.0},
                },
            },
        )

        assert records["schema_version"] == SCHEMA_VERSION
        assert len(records["records"]) == 3
        assert simulated["simulation"]["steps"] == 4
        assert simulated["readings"][1]["blockage"]["location"] == "상부"
        assert simulated["readings"][2]["blockage"]["location"] == "내부"
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_timeseries_and_post_scenario_endpoints():
    server, base_url = run_test_server()
    try:
        timeseries = get_json(
            f"{base_url}/api/v1/sensors/timeseries"
            "?scenario=network_passthrough&steps=5"
        )
        scenario = post_json(
            f"{base_url}/api/v1/sensors/scenario",
            {
                "scenario": "rain_stops",
                "steps": 6,
            },
        )

        assert timeseries["schema_version"] == SCHEMA_VERSION
        assert timeseries["scenario"]["id"] == "network_passthrough"
        assert len(timeseries["snapshots"]) == 5
        assert len(timeseries["records"]) == 15
        assert scenario["scenario"]["id"] == "rain_stops"
        assert len(scenario["snapshots"]) == 6
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_latest_sensor_endpoint():
    server, base_url = run_test_server()
    try:
        latest_b = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?rainfall=0.8&steps=8&drain_b_location=surface&drain_b_severity=0.9"
        )
        latest_c = get_json(
            f"{base_url}/api/v1/sensors/c/latest"
            "?rainfall=0.8&steps=8&drain_c_location=internal&drain_c_severity=0.9"
        )
        latest_drain_b = get_json(
            f"{base_url}/api/v1/sensors/drain_b"
            "?rainfall=0.8&steps=8&drain_b_location=internal&drain_b_severity=0.9"
        )

        assert latest_b["schema_version"] == SCHEMA_VERSION
        assert latest_b["mode"] == "snapshot_latest"
        assert latest_b["drain_id"] == "DRAIN_B"
        assert latest_b["latest"]["drain_id"] == "DRAIN_B"
        assert latest_b["latest"]["blockage_location"] == "상부"
        assert latest_b["latest"]["surface_water_level"] > 0.0
        assert latest_c["mode"] == "snapshot_latest"
        assert latest_c["latest"]["drain_id"] == "DRAIN_C"
        assert latest_c["latest"]["blockage_location"] == "내부"
        assert latest_drain_b["latest"]["blockage_location"] == "내부"
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_runtime_latest_and_snapshot_source(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAIN_SIM_RUNTIME_DIR", str(tmp_path))
    write_runtime_snapshot(runtime_payload())
    server, base_url = run_test_server()
    try:
        latest = get_json(f"{base_url}/api/v1/sensors/b/latest?source=runtime")
        snapshot = get_json(f"{base_url}/api/v1/sensors/snapshot?source=runtime")

        assert latest["schema_version"] == SCHEMA_VERSION
        assert latest["mode"] == "runtime_latest"
        assert latest["drain_id"] == "DRAIN_B"
        assert latest["runtime"]["producer"] == "streamlit"
        assert latest["runtime"]["time_step"] == 12
        assert latest["latest"]["drain_id"] == "DRAIN_B"
        assert latest["latest"]["surface_water_level"] == 0.6
        assert snapshot["mode"] == "runtime_snapshot"
        assert snapshot["records"][1]["drain_id"] == "DRAIN_B"
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_runtime_source_missing_snapshot_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAIN_SIM_RUNTIME_DIR", str(tmp_path))
    server, base_url = run_test_server()
    try:
        try:
            get_json(f"{base_url}/api/v1/sensors/b/latest?source=runtime")
        except HTTPError as exc:
            assert exc.code == 404
            error = json.loads(exc.read().decode("utf-8"))
            assert error["error"] == "runtime_snapshot_not_found"
        else:
            raise AssertionError("runtime source should return 404 before Streamlit writes")
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_latest_rejects_scenario_query():
    server, base_url = run_test_server()
    try:
        try:
            get_json(
                f"{base_url}/api/v1/sensors/c/latest"
                "?scenario=internal_stagnation&steps=8"
            )
        except HTTPError as exc:
            assert exc.code == 400
            error = json.loads(exc.read().decode("utf-8"))
            assert "scenario is for timeseries endpoints" in error["detail"]
        else:
            raise AssertionError("latest endpoint should reject scenario queries")
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_live_latest_response_contract_and_reproducibility():
    server, base_url = run_test_server()
    try:
        first = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=storm_pulse&tick=10&seed=demo"
        )
        second = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=storm_pulse&tick=10&seed=demo"
        )
        next_tick = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=storm_pulse&tick=11&seed=demo"
        )

        assert first == second
        assert first["schema_version"] == SCHEMA_VERSION
        assert first["mode"] == "live_latest"
        assert first["drain_id"] == "DRAIN_B"
        assert first["live"]["profile"] == "storm_pulse"
        assert first["live"]["tick"] == 10
        assert first["live"]["interval_sec"] == 2.0
        assert first["live"]["next_poll_after_ms"] == 2000
        assert first["latest"]["drain_id"] == "DRAIN_B"

        changed_fields = [
            field
            for field in LIVE_BOUNDED_FIELDS
            if first["latest"][field] != next_tick["latest"][field]
        ]
        assert changed_fields
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_live_profiles_keep_values_bounded():
    server, base_url = run_test_server()
    try:
        for profile in LIVE_PROFILES:
            for tick in (0, 3, 10, 21):
                payload = get_json(
                    f"{base_url}/api/v1/sensors/c/latest"
                    f"?mode=live&profile={profile}&tick={tick}&seed=bounded"
                )
                latest = payload["latest"]

                assert payload["mode"] == "live_latest"
                assert payload["live"]["profile"] == profile
                for field in LIVE_BOUNDED_FIELDS:
                    assert 0.0 <= float(latest[field]) <= 1.0
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_live_surface_and_internal_profiles_keep_expected_patterns():
    server, base_url = run_test_server()
    try:
        surface = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=surface_debris_live&tick=10&seed=pattern"
        )["latest"]
        internal = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=internal_stagnation_live&tick=10&seed=pattern"
        )["latest"]
        storm = get_json(
            f"{base_url}/api/v1/sensors/b/latest"
            "?mode=live&profile=storm_pulse&tick=10&seed=pattern"
        )["latest"]

        assert surface["blockage_location"] == "상부"
        assert float(surface["surface_water_level"]) >= 0.45
        assert float(surface["inlet_flow"]) < float(storm["inlet_flow"])
        assert "상부" in surface["status"] or "물고임" in surface["status"]

        assert internal["blockage_location"] == "내부"
        assert float(internal["pipe_water_level"]) >= 0.70
        assert float(internal["pipe_flow_speed"]) < float(storm["pipe_flow_speed"])
        assert "내부" in internal["status"] or "정체" in internal["status"]
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_live_high_level_high_flow_policy():
    server, base_url = run_test_server()
    try:
        payload = get_json(
            f"{base_url}/api/v1/sensors/c/latest"
            "?mode=live&profile=mixed_unstable&tick=4&seed=policy"
        )
        latest = payload["latest"]

        assert float(latest["pipe_water_level"]) >= 0.70
        assert float(latest["pipe_flow_speed"]) >= 0.55
        assert latest["status"] == "배수 진행 중"
    finally:
        server.shutdown()
        server.server_close()


def test_sensor_api_realism_options_work_for_snapshot_and_timeseries():
    server, base_url = run_test_server()
    try:
        snapshot = get_json(
            f"{base_url}/api/v1/sensors/snapshot"
            "?steps=3&missing=true&missing_rate=1&seed=9"
        )
        timeseries = post_json(
            f"{base_url}/api/v1/sensors/scenario",
            {
                "scenario": "surface_blockage",
                "steps": 4,
                "realism": {
                    "noise": True,
                    "noise_scale": 0.03,
                    "seed": 9,
                },
            },
        )

        assert snapshot["realism"]["missing"]["enabled"] is True
        assert snapshot["readings"][0]["measurements"]["surface_water_level"] is None
        assert "missing" in snapshot["readings"][0]["quality_flags"]
        assert timeseries["realism"]["noise"]["enabled"] is True
        assert any("noisy" in record["quality_flags"] for record in timeseries["records"])
    finally:
        server.shutdown()
        server.server_close()
