"""Small mock sensor HTTP API for the drain simulator.

This is a local API contract for development and integration tests.
It does not connect to a real sensor backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from runtime_state import (
    RuntimeSnapshotError,
    RuntimeSnapshotInvalid,
    RuntimeSnapshotNotFound,
    get_runtime_latest_record,
    read_runtime_snapshot,
)
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

SENSOR_PATH_ALIASES = {
    "a": "DRAIN_A",
    "b": "DRAIN_B",
    "c": "DRAIN_C",
    "drain_a": "DRAIN_A",
    "drain_b": "DRAIN_B",
    "drain_c": "DRAIN_C",
}
LIVE_MODE = "live"
RUNTIME_SOURCE = "runtime"
DEFAULT_LIVE_PROFILE = "storm_pulse"
DEFAULT_LIVE_INTERVAL_SEC = 2.0
LIVE_PROFILES = {
    "normal_drain",
    "storm_pulse",
    "surface_debris_live",
    "internal_stagnation_live",
    "mixed_unstable",
}
LIVE_MEASUREMENT_FIELDS = (
    "surface_water_level",
    "inlet_flow",
    "pipe_water_level",
    "pipe_flow_speed",
    "pipe_flow_rate",
)


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
        "mode",
        "source",
        "profile",
        "tick",
        "interval_sec",
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


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a float value into an inclusive range."""

    return max(low, min(high, float(value)))


def drain_id_from_path(path: str) -> str | None:
    """Return a drain id for /api/v1/sensors/{a,b,c}/latest paths."""

    prefix = "/api/v1/sensors/"
    if not path.startswith(prefix):
        return None

    parts = [part for part in path[len(prefix):].split("/") if part]
    if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == "latest"):
        raw_drain_id = parts[0]
    else:
        return None

    return SENSOR_PATH_ALIASES.get(raw_drain_id.strip().lower())


def stable_seed_int(*parts: object) -> int:
    """Return a deterministic integer seed from request parts."""

    text = ":".join(str(part) for part in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def normalized_wave(value: float) -> float:
    """Return a smooth 0~1 wave for live mock input generation."""

    return (math.sin(value) + 1.0) / 2.0


def parse_live_request(request: dict[str, Any]) -> dict[str, Any]:
    """Normalize live latest query parameters."""

    profile = str(request.get("profile", DEFAULT_LIVE_PROFILE)).strip().lower()
    if profile not in LIVE_PROFILES:
        raise ValueError(f"Unknown live profile: {profile}")

    interval_sec = clamp(
        float(request.get("interval_sec", DEFAULT_LIVE_INTERVAL_SEC)),
        0.25,
        60.0,
    )
    seed = str(request.get("seed", "live-demo"))
    if "tick" in request:
        tick = max(0, int(float(request["tick"])))
    else:
        tick = max(0, int(time.time() / interval_sec))

    return {
        "profile": profile,
        "tick": tick,
        "interval_sec": interval_sec,
        "seed": seed,
        "next_poll_after_ms": int(interval_sec * 1000),
    }


def build_live_sensor_request(
    drain_id: str,
    live: dict[str, Any],
) -> dict[str, Any]:
    """Build a stateless simulation request for one live latest tick."""

    profile = str(live["profile"])
    tick = int(live["tick"])
    seed = str(live["seed"])
    phase_seed = stable_seed_int(profile, seed, drain_id) % 360
    phase = tick * 0.47 + phase_seed / 57.2958
    slow_phase = tick * 0.19 + phase_seed / 91.0
    wave = normalized_wave(phase)
    slow_wave = normalized_wave(slow_phase)
    jitter = ((stable_seed_int(profile, seed, tick, drain_id) % 1000) / 1000.0 - 0.5)

    rainfall = 0.35
    pipe_capacity = 1.0
    target_location = "none"
    target_severity = 0.0
    steps = 8

    if profile == "normal_drain":
        rainfall = clamp(0.22 + wave * 0.16 + jitter * 0.02, 0.05, 0.45)
        pipe_capacity = clamp(0.95 + slow_wave * 0.08, 0.85, 1.1)
        steps = 5 + tick % 4

    elif profile == "storm_pulse":
        rainfall = clamp(0.48 + wave * 0.47 + jitter * 0.03, 0.25, 1.0)
        pipe_capacity = clamp(0.88 + slow_wave * 0.16, 0.75, 1.1)
        steps = 7 + tick % 8

    elif profile == "surface_debris_live":
        rainfall = clamp(0.62 + wave * 0.25 + jitter * 0.03, 0.35, 1.0)
        pipe_capacity = clamp(0.92 + normalized_wave(phase + 1.4) * 0.10, 0.8, 1.05)
        target_location = "surface"
        target_severity = clamp(0.66 + slow_wave * 0.28 + jitter * 0.03, 0.58, 0.98)
        steps = 12 + tick % 8

    elif profile == "internal_stagnation_live":
        rainfall = clamp(0.62 + wave * 0.28 + jitter * 0.03, 0.35, 1.0)
        pipe_capacity = clamp(0.82 + normalized_wave(phase + 0.8) * 0.14, 0.65, 1.0)
        target_location = "internal"
        target_severity = clamp(0.66 + slow_wave * 0.30 + jitter * 0.03, 0.58, 1.0)
        steps = 12 + tick % 9

    elif profile == "mixed_unstable":
        rainfall = clamp(0.55 + wave * 0.34 + jitter * 0.04, 0.30, 1.0)
        pipe_capacity = clamp(0.74 + normalized_wave(phase + 2.1) * 0.22, 0.55, 1.0)
        target_location = "complex"
        target_severity = clamp(0.25 + slow_wave * 0.48 + jitter * 0.04, 0.18, 0.82)
        steps = 10 + tick % 10

    drains = {
        drain: {"location": "none", "severity": 0.0}
        for drain in DRAIN_IDS
    }
    drains[drain_id] = {
        "location": target_location,
        "severity": round(target_severity, 4),
    }

    return {
        "rainfall": round(rainfall, 4),
        "pipe_capacity": round(pipe_capacity, 4),
        "steps": int(steps),
        "step_minutes": 1.0,
        "drains": drains,
    }


def build_live_latest_payload(drain_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Return one stateless polling-friendly live latest reading."""

    live = parse_live_request(request)
    live_request = build_live_sensor_request(drain_id, live)
    observed_at = (
        datetime(1970, 1, 1)
        + timedelta(seconds=int(live["tick"] * live["interval_sec"]))
    ).isoformat(timespec="seconds")
    records = simulate_sensor_records(live_request, generated_at=observed_at)
    latest = next(
        record
        for record in records
        if record.get("drain_id") == drain_id
    )
    live["simulation"] = {
        "rainfall": live_request["rainfall"],
        "pipe_capacity": live_request["pipe_capacity"],
        "steps": live_request["steps"],
        "drain": live_request["drains"][drain_id],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "drain-sensor-simulator",
        "mode": "live_latest",
        "drain_id": drain_id,
        "live": live,
        "latest": latest,
    }


def runtime_metadata_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return compact runtime metadata for API responses."""

    runtime = snapshot.get("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}

    return {
        "producer": runtime.get("producer", "streamlit"),
        "generated_at": runtime.get("generated_at", snapshot.get("generated_at")),
        "time_step": runtime.get("time_step", snapshot.get("time_step")),
        "elapsed_minutes": runtime.get(
            "elapsed_minutes",
            snapshot.get("elapsed_minutes"),
        ),
    }


def runtime_latest_payload(drain_id: str) -> dict[str, Any]:
    """Build a latest-value response from the Streamlit runtime snapshot."""

    snapshot = read_runtime_snapshot()
    latest = get_runtime_latest_record(drain_id)
    return {
        "schema_version": snapshot.get("schema_version", SCHEMA_VERSION),
        "source": "drain-sensor-simulator",
        "mode": "runtime_latest",
        "drain_id": drain_id,
        "runtime": runtime_metadata_from_snapshot(snapshot),
        "latest": latest,
    }


def latest_sensor_payload(drain_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Build a compact latest-value response for one drain."""

    if "scenario" in request:
        raise ValueError(
            "scenario is for timeseries endpoints; use latest with snapshot query params"
        )

    if str(request.get("source", "")).strip().lower() == RUNTIME_SOURCE:
        return runtime_latest_payload(drain_id)

    if str(request.get("mode", "")).strip().lower() == LIVE_MODE:
        return build_live_latest_payload(drain_id, request)

    records = simulate_sensor_records(request)
    for record in records:
        if record.get("drain_id") == drain_id:
            return {
                "schema_version": SCHEMA_VERSION,
                "source": "drain-sensor-simulator",
                "mode": "snapshot_latest",
                "drain_id": drain_id,
                "latest": record,
            }

    raise ValueError(f"No record found for drain: {drain_id}")


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
                        "live_profiles": sorted(LIVE_PROFILES),
                        "endpoints": [
                            "GET /api/v1/sensors/snapshot",
                            "GET /api/v1/sensors/records",
                            "GET /api/v1/sensors/{a,b,c}/latest",
                            "GET /api/v1/sensors/timeseries",
                            "POST /api/v1/sensors/simulate",
                            "POST /api/v1/sensors/scenario",
                        ],
                    }
                )
                return

            if parsed.path == "/api/v1/sensors/snapshot":
                request = request_from_query(query)
                if str(request.get("source", "")).strip().lower() == RUNTIME_SOURCE:
                    self.send_json(read_runtime_snapshot())
                    return
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

            drain_id = drain_id_from_path(parsed.path)
            if drain_id is not None:
                self.send_json(
                    latest_sensor_payload(drain_id, request_from_query(query))
                )
                return

            self.send_json({"error": "not_found"}, status=404)
        except RuntimeSnapshotNotFound as exc:
            self.send_json(
                {
                    "error": "runtime_snapshot_not_found",
                    "detail": str(exc),
                    "hint": "Run Streamlit and start the simulation first.",
                },
                status=404,
            )
        except RuntimeSnapshotInvalid as exc:
            self.send_json(
                {
                    "error": "runtime_snapshot_invalid",
                    "detail": str(exc),
                },
                status=500,
            )
        except RuntimeSnapshotError as exc:
            self.send_json(
                {
                    "error": "runtime_snapshot_error",
                    "detail": str(exc),
                },
                status=500,
            )
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
