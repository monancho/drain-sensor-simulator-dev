"""Small mock sensor HTTP API for the drain simulator.

This is a local API contract for development and integration tests.
It does not connect to a real sensor backend.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from sensor_api_service import (
    DEFAULT_API_DRAIN_CONFIGS,
    REALISM_QUERY_FIELDS,
    SCHEMA_VERSION,
    available_scenarios,
    simulate_sensor_records,
    simulate_sensor_snapshot,
    simulate_sensor_timeseries,
)
from simulation import DRAIN_IDS


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for a parsed query key."""

    values = query.get(key)
    if not values:
        return None
    return values[0]


def request_from_query(query: dict[str, list[str]]) -> dict[str, Any]:
    """Convert query string values into a simulation request."""

    request: dict[str, Any] = {}
    for field in (
        "scenario",
        "rainfall",
        "pipe_capacity",
        "steps",
        "step_minutes",
        *REALISM_QUERY_FIELDS,
    ):
        value = first_query_value(query, field)
        if value is not None:
            request[field] = value

    drains: dict[str, dict[str, str]] = {}
    for drain_id in DRAIN_IDS:
        lower_id = drain_id.lower()
        location = first_query_value(query, f"{lower_id}_location")
        severity = first_query_value(query, f"{lower_id}_severity")
        if location is not None or severity is not None:
            drains[drain_id] = {}
            if location is not None:
                drains[drain_id]["location"] = location
            if severity is not None:
                drains[drain_id]["severity"] = severity

    if drains:
        request["drains"] = drains

    return request


class SensorAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for mock sensor endpoints."""

    server_version = "DrainSensorMockAPI/1.0"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        try:
            if parsed.path == "/health":
                self.send_json({"status": "ok", "schema_version": SCHEMA_VERSION})
                return

            if parsed.path == "/api/v1/sensors/schema":
                self.send_json(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "default_drains": DEFAULT_API_DRAIN_CONFIGS,
                        "scenarios": available_scenarios(),
                        "endpoints": [
                            "GET /api/v1/sensors/snapshot",
                            "GET /api/v1/sensors/records",
                            "GET /api/v1/sensors/timeseries",
                            "POST /api/v1/sensors/simulate",
                            "POST /api/v1/sensors/scenario",
                        ],
                    }
                )
                return

            if parsed.path == "/api/v1/sensors/snapshot":
                self.send_json(simulate_sensor_snapshot(request_from_query(query)))
                return

            if parsed.path == "/api/v1/sensors/records":
                self.send_json(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "records": simulate_sensor_records(request_from_query(query)),
                    }
                )
                return

            if parsed.path == "/api/v1/sensors/timeseries":
                self.send_json(simulate_sensor_timeseries(request_from_query(query)))
                return

            self.send_json({"error": "not_found"}, status=404)
        except ValueError as exc:
            self.send_json({"error": "bad_request", "detail": str(exc)}, status=400)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/v1/sensors/simulate", "/api/v1/sensors/scenario"):
            self.send_json({"error": "not_found"}, status=404)
            return

        try:
            request = self.read_json_body()
            if parsed.path == "/api/v1/sensors/scenario":
                self.send_json(simulate_sensor_timeseries(request))
                return
            self.send_json(simulate_sensor_snapshot(request))
        except ValueError as exc:
            self.send_json({"error": "bad_request", "detail": str(exc)}, status=400)

    def read_json_body(self) -> dict[str, Any]:
        """Read a JSON request body."""

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}

        body = self.rfile.read(content_length).decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        """Send a JSON response."""

        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep API logs concise."""

        return


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the mock sensor API server."""

    server = ThreadingHTTPServer((host, port), SensorAPIHandler)
    print(f"Mock sensor API listening on http://{host}:{port}")
    print("Try GET /health or /api/v1/sensors/snapshot")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping mock sensor API")
    finally:
        server.server_close()


def main() -> None:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(description="Run the drain sensor mock API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
