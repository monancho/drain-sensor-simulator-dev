"""API-facing helpers for simulated or external sensor snapshots."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.request import Request, urlopen

from sensor_model import attach_sensor_status
from sensor_payload import (
    SCHEMA_VERSION,
    SENSOR_MEASUREMENT_FIELDS,
    build_mock_sensor_payload,
    build_mock_sensor_records,
    build_mock_sensor_timeseries_payload,
    ordered_quality_flags,
    quality_label,
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
REALISM_QUERY_FIELDS = (
    "seed",
    "noise",
    "noise_scale",
    "missing",
    "missing_rate",
    "stale",
    "stale_rate",
    "spike",
    "spike_rate",
    "spike_magnitude",
    "stuck",
    "stuck_drain_id",
    "stuck_field",
    "delay",
    "delay_steps",
    "realism_noise",
    "realism_missing",
    "realism_stale",
    "realism_spike",
    "realism_stuck",
    "realism_delay",
)
DEFAULT_TIMESERIES_SCENARIO = "surface_blockage"
SCENARIO_DEFINITIONS: dict[str, dict[str, Any]] = {
    "light_rain": {
        "id": "light_rain",
        "title_ko": "약한 비",
        "description_ko": "막힘 없이 약한 비가 지속되는 안정 배수 기준 시나리오입니다.",
        "default_steps": 18,
    },
    "heavy_rain": {
        "id": "heavy_rain",
        "title_ko": "집중호우",
        "description_ko": "강우가 점진적으로 강해지며 관로가 정상 배수하는 패턴입니다.",
        "default_steps": 24,
    },
    "rain_stops": {
        "id": "rain_stops",
        "title_ko": "비 그침 후 노면 감소",
        "description_ko": "상부 막힘으로 생긴 도로 물고임이 비가 그친 뒤 서서히 줄어드는 패턴입니다.",
        "default_steps": 30,
    },
    "surface_blockage": {
        "id": "surface_blockage",
        "title_ko": "상부 막힘 진행",
        "description_ko": "B 배수구 상부 유입구가 점점 막히며 도로 물고임이 증가하는 패턴입니다.",
        "default_steps": 24,
    },
    "internal_stagnation": {
        "id": "internal_stagnation",
        "title_ko": "내부 정체 진행",
        "description_ko": "C 하류 관로 내부 막힘이 악화되며 관로 수위가 오르고 유속이 낮아지는 패턴입니다.",
        "default_steps": 24,
    },
    "complex_worsening": {
        "id": "complex_worsening",
        "title_ko": "복합 막힘 악화",
        "description_ko": "상부와 내부 문제가 동시에 악화되는 데모용 복합 패턴입니다.",
        "default_steps": 28,
    },
    "network_passthrough": {
        "id": "network_passthrough",
        "title_ko": "상부 막힘 노드 통과 흐름",
        "description_ko": "B/C 상부가 막혀도 A에서 들어온 관로 내부 흐름은 하류로 통과하는 패턴입니다.",
        "default_steps": 18,
    },
}


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a float value into an inclusive range."""

    return max(low, min(high, float(value)))


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parse common API boolean values."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off", ""}:
        return False
    return default


def optional_int(value: Any) -> int | None:
    """Parse an optional integer value."""

    if value is None or value == "":
        return None
    return int(float(value))


def realism_value(
    raw_request: dict[str, Any],
    raw_realism: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """Return a realism option from nested or top-level request fields."""

    if key in raw_realism:
        return raw_realism[key]
    prefixed_key = f"realism_{key}"
    if prefixed_key in raw_request:
        return raw_request[prefixed_key]
    if key in raw_request:
        return raw_request[key]
    return default


def normalize_realism_config(raw_request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize optional sensor realism controls for mock sensor payloads."""

    raw_request = raw_request or {}
    raw_realism = raw_request.get("realism", {})
    if not isinstance(raw_realism, dict):
        raw_realism = {}

    seed = optional_int(realism_value(raw_request, raw_realism, "seed"))
    noise_enabled = parse_bool(realism_value(raw_request, raw_realism, "noise"))
    missing_enabled = parse_bool(realism_value(raw_request, raw_realism, "missing"))
    stale_enabled = parse_bool(realism_value(raw_request, raw_realism, "stale"))
    spike_enabled = parse_bool(realism_value(raw_request, raw_realism, "spike"))
    stuck_enabled = parse_bool(realism_value(raw_request, raw_realism, "stuck"))
    delay_enabled = parse_bool(realism_value(raw_request, raw_realism, "delay"))

    config = {
        "enabled": any(
            (
                noise_enabled,
                missing_enabled,
                stale_enabled,
                spike_enabled,
                stuck_enabled,
                delay_enabled,
            )
        ),
        "seed": seed,
        "noise": {
            "enabled": noise_enabled,
            "scale": clamp(
                float(realism_value(raw_request, raw_realism, "noise_scale", 0.025)),
                0.0,
                0.25,
            ),
        },
        "missing": {
            "enabled": missing_enabled,
            "rate": clamp(
                float(realism_value(raw_request, raw_realism, "missing_rate", 0.04)),
                0.0,
                1.0,
            ),
        },
        "stale": {
            "enabled": stale_enabled,
            "rate": clamp(
                float(realism_value(raw_request, raw_realism, "stale_rate", 0.05)),
                0.0,
                1.0,
            ),
        },
        "spike": {
            "enabled": spike_enabled,
            "rate": clamp(
                float(realism_value(raw_request, raw_realism, "spike_rate", 0.03)),
                0.0,
                1.0,
            ),
            "magnitude": clamp(
                float(realism_value(raw_request, raw_realism, "spike_magnitude", 0.25)),
                0.0,
                1.0,
            ),
        },
        "stuck": {
            "enabled": stuck_enabled,
            "drain_id": str(
                realism_value(raw_request, raw_realism, "stuck_drain_id", "DRAIN_C")
            ),
            "field": str(
                realism_value(raw_request, raw_realism, "stuck_field", "pipe_flow_speed")
            ),
        },
        "delay": {
            "enabled": delay_enabled,
            "steps": int(
                clamp(
                    float(realism_value(raw_request, raw_realism, "delay_steps", 1)),
                    1,
                    12,
                )
            ),
        },
    }
    return config


def public_realism_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly realism summary."""

    return deepcopy(config)


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
    realism = normalize_realism_config(raw_request)

    return {
        "rainfall": rainfall,
        "pipe_capacity": pipe_capacity,
        "steps": steps,
        "step_minutes": step_minutes,
        "drain_configs": drain_configs,
        "realism": realism,
    }


def available_scenarios() -> list[dict[str, Any]]:
    """Return public scenario metadata for schema/API/UI consumers."""

    return [
        {
            "id": scenario["id"],
            "title_ko": scenario["title_ko"],
            "description_ko": scenario["description_ko"],
            "default_steps": scenario["default_steps"],
        }
        for scenario in SCENARIO_DEFINITIONS.values()
    ]


def normalize_timeseries_request(raw_request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a scenario/timeseries request."""

    raw_request = raw_request or {}
    scenario_id = str(raw_request.get("scenario", DEFAULT_TIMESERIES_SCENARIO)).strip()
    scenario_id = scenario_id.lower()
    if scenario_id not in SCENARIO_DEFINITIONS:
        raise ValueError(f"Unknown scenario: {scenario_id}")

    definition = SCENARIO_DEFINITIONS[scenario_id]
    steps = int(clamp(float(raw_request.get("steps", definition["default_steps"])), 1, 240))
    step_minutes = clamp(float(raw_request.get("step_minutes", 1.0)), 0.1, 60.0)

    rainfall_override = None
    if "rainfall" in raw_request:
        rainfall_override = clamp(float(raw_request["rainfall"]), 0.0, 1.0)

    pipe_capacity_override = None
    if "pipe_capacity" in raw_request:
        pipe_capacity_override = clamp(float(raw_request["pipe_capacity"]), 0.0, 1.5)

    drain_configs = None
    if "drains" in raw_request:
        drain_configs = normalize_drain_configs(raw_request.get("drains"))
    realism = normalize_realism_config(raw_request)

    return {
        "scenario_id": scenario_id,
        "steps": steps,
        "step_minutes": step_minutes,
        "rainfall_override": rainfall_override,
        "pipe_capacity_override": pipe_capacity_override,
        "drain_configs": drain_configs,
        "realism": realism,
    }


def default_clear_configs() -> dict[str, tuple[BlockageLocation, float]]:
    """Return an all-clear drain configuration."""

    return {drain_id: ("없음", 0.0) for drain_id in DRAIN_IDS}


def scenario_progress(step_index: int, steps: int) -> float:
    """Return 0~1 progress for a zero-based step index."""

    if steps <= 1:
        return 1.0
    return clamp(step_index / (steps - 1), 0.0, 1.0)


def scenario_frame(
    request: dict[str, Any],
    *,
    step_index: int,
) -> dict[str, Any]:
    """Build one scenario input frame for the simulator."""

    scenario_id = request["scenario_id"]
    steps = int(request["steps"])
    progress = scenario_progress(step_index, steps)
    configs = default_clear_configs()
    rainfall = 0.7
    pipe_capacity = 1.0

    if scenario_id == "light_rain":
        rainfall = 0.35

    elif scenario_id == "heavy_rain":
        rainfall = 0.55 + 0.45 * progress

    elif scenario_id == "rain_stops":
        rainfall = 0.9 if progress < 0.45 else 0.0
        configs["DRAIN_B"] = ("상부", 0.95)

    elif scenario_id == "surface_blockage":
        rainfall = 0.85
        configs["DRAIN_B"] = ("상부", max(0.15, progress))

    elif scenario_id == "internal_stagnation":
        rainfall = 0.85
        configs["DRAIN_C"] = ("내부", 0.20 + 0.80 * progress)

    elif scenario_id == "complex_worsening":
        rainfall = 0.65 + 0.35 * progress
        pipe_capacity = 0.9
        configs["DRAIN_B"] = ("상부", 0.45 + 0.35 * progress)
        configs["DRAIN_C"] = ("복합", 0.35 + 0.65 * progress)

    elif scenario_id == "network_passthrough":
        rainfall = 1.0
        configs["DRAIN_B"] = ("상부", 0.95)
        configs["DRAIN_C"] = ("상부", 0.95)

    if request["rainfall_override"] is not None:
        rainfall = request["rainfall_override"]

    if request["pipe_capacity_override"] is not None:
        pipe_capacity = request["pipe_capacity_override"]

    if request["drain_configs"] is not None:
        configs = request["drain_configs"]

    return {
        "rainfall": round(float(rainfall), 4),
        "pipe_capacity": round(float(pipe_capacity), 4),
        "blockage_configs": configs,
    }


def configs_as_metadata(
    configs: dict[str, tuple[BlockageLocation, float]],
) -> dict[str, dict[str, float | str]]:
    """Serialize blockage configs for JSON metadata."""

    return {
        drain_id: {
            "location": location,
            "severity": round(float(severity), 4),
        }
        for drain_id, (location, severity) in configs.items()
    }


def observed_at_for_step(generated_at: str, elapsed_minutes: float) -> str:
    """Create a deterministic observed_at timestamp for a scenario step."""

    try:
        base_time = datetime.fromisoformat(generated_at)
    except ValueError:
        return generated_at
    return (base_time + timedelta(minutes=elapsed_minutes)).isoformat(timespec="seconds")


def build_scenario_metadata(request: dict[str, Any]) -> dict[str, Any]:
    """Build public metadata for a timeseries scenario payload."""

    definition = SCENARIO_DEFINITIONS[request["scenario_id"]]
    return {
        "id": definition["id"],
        "title_ko": definition["title_ko"],
        "description_ko": definition["description_ko"],
        "steps": request["steps"],
        "step_minutes": request["step_minutes"],
        "quality": "mock",
    }


def add_measurement_quality_flag(
    reading: dict[str, Any],
    field: str,
    flag: str,
) -> None:
    """Attach a quality flag to one measurement and its parent reading."""

    measurement_quality = reading.setdefault("measurement_quality", {})
    field_flags = measurement_quality.setdefault(field, ["mock"])
    if flag not in field_flags:
        field_flags.append(flag)
    reading_flags = reading.setdefault("quality_flags", ["mock"])
    if flag not in reading_flags:
        reading_flags.append(flag)


def finalize_reading_quality(reading: dict[str, Any]) -> None:
    """Update stable quality labels after realism transforms."""

    flags = ordered_quality_flags(reading.get("quality_flags", ["mock"]))
    measurement_quality = reading.setdefault("measurement_quality", {})
    for field in SENSOR_MEASUREMENT_FIELDS:
        measurement_quality[field] = ordered_quality_flags(
            measurement_quality.get(field, ["mock"])
        )
    reading["quality_flags"] = flags
    reading["quality"] = quality_label(flags)


def matching_stuck_field(config: dict[str, Any], field: str) -> bool:
    """Return whether a measurement field is affected by stuck-sensor mode."""

    selected = str(config["stuck"]["field"])
    return selected in {"*", "all", field}


def matching_stuck_drain(config: dict[str, Any], drain_id: str) -> bool:
    """Return whether a drain is affected by stuck-sensor mode."""

    selected = str(config["stuck"]["drain_id"]).upper()
    return selected in {"*", "ALL", drain_id}


def should_apply_rate(rng: random.Random, rate: float) -> bool:
    """Return whether a probabilistic realism event should apply."""

    if rate <= 0:
        return False
    if rate >= 1:
        return True
    return rng.random() < rate


def bounded_measurement(value: float) -> float:
    """Round and bound a normalized measurement value."""

    return round(clamp(value, 0.0, 1.0), 4)


def add_noise(value: float, *, rng: random.Random, scale: float) -> float:
    """Apply bounded additive sensor noise."""

    return bounded_measurement(value + rng.uniform(-scale, scale))


def add_spike(value: float, *, rng: random.Random, magnitude: float) -> float:
    """Apply a bounded one-sample spike."""

    direction = -1.0 if rng.random() < 0.5 else 1.0
    return bounded_measurement(value + direction * magnitude)


def apply_sensor_realism_to_snapshots(
    snapshots: list[dict[str, Any]],
    realism: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply optional sensor-quality artifacts to measurement fields only."""

    if not realism.get("enabled"):
        return snapshots

    realistic_snapshots = deepcopy(snapshots)
    clean_snapshots = deepcopy(snapshots)
    rng = random.Random(realism.get("seed"))
    previous_values: dict[tuple[str, str], float | None] = {}
    stuck_values: dict[tuple[str, str], float | None] = {}
    realism_metadata = public_realism_config(realism)
    realism_metadata["applies_to"] = "measurements"

    for snapshot_index, snapshot in enumerate(realistic_snapshots):
        snapshot["realism"] = realism_metadata

        for reading_index, reading in enumerate(snapshot["readings"]):
            drain_id = str(reading["drain_id"])
            measurements = reading["measurements"]

            for field in SENSOR_MEASUREMENT_FIELDS:
                value = measurements[field]
                key = (drain_id, field)

                if realism["delay"]["enabled"]:
                    delay_steps = int(realism["delay"]["steps"])
                    delayed_index = snapshot_index - delay_steps
                    if delayed_index >= 0:
                        value = clean_snapshots[delayed_index]["readings"][
                            reading_index
                        ]["measurements"][field]
                        add_measurement_quality_flag(reading, field, "delayed")

                if (
                    realism["stale"]["enabled"]
                    and key in previous_values
                    and should_apply_rate(rng, float(realism["stale"]["rate"]))
                ):
                    value = previous_values[key]
                    add_measurement_quality_flag(reading, field, "stale")

                if (
                    realism["stuck"]["enabled"]
                    and matching_stuck_drain(realism, drain_id)
                    and matching_stuck_field(realism, field)
                ):
                    if key not in stuck_values:
                        stuck_values[key] = value
                    value = stuck_values[key]
                    add_measurement_quality_flag(reading, field, "stuck")

                if value is not None and realism["noise"]["enabled"]:
                    value = add_noise(
                        float(value),
                        rng=rng,
                        scale=float(realism["noise"]["scale"]),
                    )
                    add_measurement_quality_flag(reading, field, "noisy")

                if (
                    value is not None
                    and realism["spike"]["enabled"]
                    and should_apply_rate(rng, float(realism["spike"]["rate"]))
                ):
                    value = add_spike(
                        float(value),
                        rng=rng,
                        magnitude=float(realism["spike"]["magnitude"]),
                    )
                    add_measurement_quality_flag(reading, field, "spike")

                if (
                    realism["missing"]["enabled"]
                    and should_apply_rate(rng, float(realism["missing"]["rate"]))
                ):
                    value = None
                    add_measurement_quality_flag(reading, field, "missing")

                measurements[field] = value
                previous_values[key] = value

            finalize_reading_quality(reading)

    return realistic_snapshots


def attach_realism_metadata(payload: dict[str, Any], realism: dict[str, Any]) -> None:
    """Attach public realism metadata when optional artifacts are enabled."""

    if realism.get("enabled"):
        metadata = public_realism_config(realism)
        metadata["applies_to"] = "measurements"
        payload["realism"] = metadata


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
    payload = apply_sensor_realism_to_snapshots([payload], request["realism"])[0]
    attach_realism_metadata(payload, request["realism"])
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


def simulate_sensor_timeseries(
    raw_request: dict[str, Any] | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run a named scenario and return a reusable mock sensor timeseries."""

    request = normalize_timeseries_request(raw_request)
    generated_at = generated_at or datetime.now().isoformat(timespec="seconds")
    states = initialize_drain_states()
    snapshots: list[dict[str, Any]] = []

    for step_index in range(request["steps"]):
        frame = scenario_frame(request, step_index=step_index)
        states = run_step(
            states,
            rainfall=frame["rainfall"],
            pipe_capacity=frame["pipe_capacity"],
            blockage_configs=frame["blockage_configs"],
            step_minutes=request["step_minutes"],
        )
        states = {
            drain_id: attach_sensor_status(states[drain_id])
            for drain_id in DRAIN_IDS
        }

        time_step = step_index + 1
        elapsed_minutes = time_step * request["step_minutes"]
        observed_at = observed_at_for_step(generated_at, elapsed_minutes)
        snapshot = build_mock_sensor_payload(
            states,
            rainfall=frame["rainfall"],
            pipe_capacity=frame["pipe_capacity"],
            time_step=time_step,
            elapsed_minutes=elapsed_minutes,
            generated_at=observed_at,
        )
        snapshot["simulation"] = {
            "scenario_id": request["scenario_id"],
            "time_step": time_step,
            "step_minutes": request["step_minutes"],
            "elapsed_minutes": elapsed_minutes,
            "frame": {
                "rainfall": frame["rainfall"],
                "pipe_capacity": frame["pipe_capacity"],
                "drains": configs_as_metadata(frame["blockage_configs"]),
            },
        }
        snapshots.append(snapshot)

    snapshots = apply_sensor_realism_to_snapshots(snapshots, request["realism"])
    payload = build_mock_sensor_timeseries_payload(
        snapshots,
        scenario=build_scenario_metadata(request),
        generated_at=generated_at,
    )
    attach_realism_metadata(payload, request["realism"])
    return payload


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


def validate_sensor_timeseries_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the minimal contract for a mock sensor timeseries payload."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported sensor timeseries schema_version")
    scenario = payload.get("scenario")
    if not isinstance(scenario, dict) or "id" not in scenario:
        raise ValueError("Sensor timeseries must include scenario metadata")
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Sensor timeseries must include snapshots")
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ValueError("Each timeseries snapshot must be an object")
        validate_sensor_payload(snapshot)
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("Sensor timeseries must include records")
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
