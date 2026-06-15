"""API-facing helpers for simulated or external sensor snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast
from urllib.request import Request, urlopen

from sensor_model import attach_sensor_status
from sensor_payload import (
    SCHEMA_VERSION,
    build_mock_sensor_payload,
    build_mock_sensor_records,
)
from simulation import DRAIN_IDS, BlockageLocation, initialize_drain_states, run_step

LOCATION_ALIASES: dict[str, BlockageLocation] = {
    "none": "없음",
    "normal": "없음",
    "surface": "상부",
    "top": "상부",
    "internal": "내부",
    "pipe": "내부",
    "complex": "복합",
    "both": "복합",
    "없음": "없음",
    "상부": "상부",
    "내부": "내부",
    "복합": "복합",
}
DEFAULT_API_DRAIN_CONFIGS: dict[str, dict[str, float | str]] = {
    "DRAIN_A": {"blockage_location": "없음", "blockage_severity": 0.20},
    "DRAIN_B": {"blockage_location": "상부", "blockage_severity": 0.55},
    "DRAIN_C": {"blockage_location": "복합", "blockage_severity": 0.85},
}


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a float value into an inclusive range."""

    return max(low, min(high, float(value)))


def normalize_location(value: Any) -> BlockageLocation:
    """Normalize Korean or English API location values."""

    location = LOCATION_ALIASES.get(str(value).strip().lower())
    if location is None:
        raise ValueError(f"Unknown blockage location: {value}")
    return location


def normalize_drain_configs(raw_drains: Any | None) -> dict[str, tuple[BlockageLocation, float]]:
    """Normalize API drain configs into simulator blockage configs."""

    raw_drains = raw_drains or {}
    configs: dict[str, tuple[BlockageLocation, float]] = {}

    for drain_id in DRAIN_IDS:
        default_config = DEFAULT_API_DRAIN_CONFIGS[drain_id]
        raw_config = raw_drains.get(drain_id, {}) if isinstance(raw_drains, dict) else {}
        raw_location = raw_config.get(
            "blockage_location",
            raw_config.get("location", default_config["blockage_location"]),
        )
        raw_severity = raw_config.get(
            "blockage_severity",
            raw_config.get("severity", default_config["blockage_severity"]),
        )
        location = normalize_location(raw_location)
        severity = 0.0 if location == "없음" else clamp(float(raw_severity), 0.0, 1.0)
        configs[drain_id] = (location, severity)

    return configs


def normalize_sensor_request(raw_request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize an API request body or query mapping."""

    raw_request = raw_request or {}
    rainfall = clamp(float(raw_request.get("rainfall", 0.7)), 0.0, 1.0)
    pipe_capacity = clamp(float(raw_request.get("pipe_capacity", 1.0)), 0.0, 1.5)
    steps = int(clamp(float(raw_request.get("steps", 1)), 0, 1440))
    step_minutes = clamp(float(raw_request.get("step_minutes", 1.0)), 0.1, 60.0)
    drain_configs = normalize_drain_configs(raw_request.get("drains"))

    return {
        "rainfall": rainfall,
        "pipe_capacity": pipe_capacity,
        "steps": steps,
        "step_minutes": step_minutes,
        "drain_configs": drain_configs,
    }


def simulate_sensor_snapshot(
    raw_request: dict[str, Any] | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run the simulator and return an API-ready mock sensor snapshot."""

    request = normalize_sensor_request(raw_request)
    generated_at = generated_at or datetime.now().isoformat(timespec="seconds")
    states = initialize_drain_states()

    for _ in range(request["steps"]):
        states = run_step(
            states,
            rainfall=request["rainfall"],
            pipe_capacity=request["pipe_capacity"],
            blockage_configs=request["drain_configs"],
            step_minutes=request["step_minutes"],
        )

    states = {
        drain_id: attach_sensor_status(states[drain_id])
        for drain_id in DRAIN_IDS
    }

    payload = build_mock_sensor_payload(
        states,
        rainfall=request["rainfall"],
        pipe_capacity=request["pipe_capacity"],
        time_step=request["steps"],
        elapsed_minutes=request["steps"] * request["step_minutes"],
        generated_at=generated_at,
    )
    payload["simulation"] = {
        "steps": request["steps"],
        "step_minutes": request["step_minutes"],
    }
    return payload


def simulate_sensor_records(
    raw_request: dict[str, Any] | None = None,
    *,
    generated_at: str | None = None,
) -> list[dict[str, Any]]:
    """Run the simulator and return flat API records."""

    return build_mock_sensor_records(
        simulate_sensor_snapshot(raw_request, generated_at=generated_at)
    )


def validate_sensor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the minimal contract expected from a real sensor API payload."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported sensor payload schema_version")
    readings = payload.get("readings")
    if not isinstance(readings, list) or not readings:
        raise ValueError("Sensor payload must include readings")

    for reading in readings:
        if not isinstance(reading, dict):
            raise ValueError("Each sensor reading must be an object")
        for field in ("sensor_id", "drain_id", "observed_at", "measurements"):
            if field not in reading:
                raise ValueError(f"Sensor reading missing field: {field}")
        measurements = reading["measurements"]
        if not isinstance(measurements, dict):
            raise ValueError("Sensor reading measurements must be an object")
        for metric in (
            "surface_water_level",
            "inlet_flow",
            "pipe_water_level",
            "pipe_flow_speed",
            "pipe_flow_rate",
        ):
            if metric not in measurements:
                raise ValueError(f"Sensor measurements missing metric: {metric}")

    return payload


def fetch_external_sensor_payload(
    endpoint_url: str,
    *,
    bearer_token: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Fetch and validate a future real sensor API payload with this contract."""

    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    request = Request(endpoint_url, headers=headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return validate_sensor_payload(cast(dict[str, Any], payload))
