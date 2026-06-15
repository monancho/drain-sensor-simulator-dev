import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api import SensorAPIHandler
from sensor_payload import SCHEMA_VERSION


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
