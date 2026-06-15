import json
import threading
from http.server import ThreadingHTTPServer
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
