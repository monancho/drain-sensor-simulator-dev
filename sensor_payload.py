"""Mock sensor payload builders for simulated drain readings."""

from __future__ import annotations

import json
from typing import Any

from simulation import DRAIN_IDS

SCHEMA_VERSION = "virtual-drain-sensor.v1"
NETWORK_TOPOLOGY = (
    ("DRAIN_A", "DRAIN_B"),
    ("DRAIN_B", "DRAIN_C"),
    ("DRAIN_C", "OUTFALL"),
)
SENSOR_MEASUREMENT_FIELDS = (
    "surface_water_level",
    "inlet_flow",
    "pipe_water_level",
    "pipe_flow_speed",
    "pipe_flow_rate",
)
QUALITY_FLAG_ORDER = (
    "mock",
    "noisy",
    "missing",
    "stale",
    "spike",
    "stuck",
    "delayed",
)
SENSOR_DERIVED_FIELDS = (
    "surface_recession",
    "surface_spill_in",
    "surface_spill_out",
    "pipe_surcharge_to_surface",
    "upstream_pipe_flow",
    "downstream_backwater",
    "pipe_segment_outflow",
    "surface_water_delta",
    "pipe_water_delta",
    "pipe_flow_delta",
    "level_flow_ratio",
    "stagnation_score",
    "remaining_surface_capacity",
    "remaining_pipe_capacity",
)
NORMALIZED_UNITS = {
    field: "normalized_0_1"
    for field in (
        *SENSOR_MEASUREMENT_FIELDS,
        "surface_recession",
        "surface_spill_in",
        "surface_spill_out",
        "pipe_surcharge_to_surface",
        "upstream_pipe_flow",
        "downstream_backwater",
        "pipe_segment_outflow",
        "surface_blockage",
        "internal_blockage",
        "stagnation_score",
        "remaining_surface_capacity",
        "remaining_pipe_capacity",
    )
}


def float_value(state: dict[str, float | str], field: str) -> float:
    """Return a rounded float from a state dictionary."""

    return round(float(state.get(field, 0.0)), 4)


def ordered_quality_flags(flags: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Return quality flags in a stable API order."""

    flag_set = set(flags) or {"mock"}
    ordered = [flag for flag in QUALITY_FLAG_ORDER if flag in flag_set]
    ordered.extend(sorted(flag_set.difference(QUALITY_FLAG_ORDER)))
    return ordered


def quality_label(flags: list[str] | tuple[str, ...] | set[str]) -> str:
    """Return a compact string label for quality flags."""

    return "+".join(ordered_quality_flags(flags))


def build_mock_sensor_reading(
    drain_id: str,
    state: dict[str, float | str],
    *,
    observed_at: str,
    time_step: int,
    elapsed_minutes: float,
) -> dict[str, Any]:
    """Build one API-like mock sensor reading for a drain."""

    measurements = {
        field: float_value(state, field)
        for field in SENSOR_MEASUREMENT_FIELDS
    }
    derived = {
        field: float_value(state, field)
        for field in SENSOR_DERIVED_FIELDS
    }
    measurement_quality = {
        field: ["mock"]
        for field in SENSOR_MEASUREMENT_FIELDS
    }

    return {
        "sensor_id": f"SIM-{drain_id}",
        "drain_id": drain_id,
        "observed_at": observed_at,
        "time_step": int(time_step),
        "elapsed_minutes": float(elapsed_minutes),
        "quality": "mock",
        "quality_flags": ["mock"],
        "measurement_quality": measurement_quality,
        "status": str(state.get("sensor_status", "정상 배수")),
        "blockage": {
            "location": str(state.get("blockage_location", "없음")),
            "severity": float_value(state, "blockage_severity"),
            "surface": float_value(state, "surface_blockage"),
            "internal": float_value(state, "internal_blockage"),
        },
        "measurements": measurements,
        "derived": derived,
    }


def build_mock_sensor_payload(
    states: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    pipe_capacity: float,
    time_step: int,
    elapsed_minutes: float,
    generated_at: str,
) -> dict[str, Any]:
    """Build a stable mock payload from the current simulator state."""

    readings = [
        build_mock_sensor_reading(
            drain_id,
            states[drain_id],
            observed_at=generated_at,
            time_step=time_step,
            elapsed_minutes=elapsed_minutes,
        )
        for drain_id in DRAIN_IDS
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "drain-sensor-simulator",
        "generated_at": generated_at,
        "network": {
            "nodes": [*DRAIN_IDS, "OUTFALL"],
            "topology": [
                {"from": upstream, "to": downstream}
                for upstream, downstream in NETWORK_TOPOLOGY
            ],
        },
        "inputs": {
            "rainfall": round(float(rainfall), 4),
            "pipe_capacity": round(float(pipe_capacity), 4),
        },
        "units": NORMALIZED_UNITS,
        "readings": readings,
    }


def build_mock_sensor_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a mock payload into rows suitable for tables or JSONL."""

    records = []
    for reading in payload["readings"]:
        measurements = reading["measurements"]
        derived = reading["derived"]
        blockage = reading["blockage"]
        quality_flags = ordered_quality_flags(reading.get("quality_flags", ["mock"]))
        measurement_quality = reading.get("measurement_quality", {})
        field_quality = {
            f"{field}_quality": quality_label(
                measurement_quality.get(field, quality_flags)
            )
            for field in SENSOR_MEASUREMENT_FIELDS
        }
        records.append(
            {
                "sensor_id": reading["sensor_id"],
                "drain_id": reading["drain_id"],
                "observed_at": reading["observed_at"],
                "time_step": reading["time_step"],
                "elapsed_minutes": reading["elapsed_minutes"],
                "quality": reading.get("quality", quality_label(quality_flags)),
                "quality_flags": quality_label(quality_flags),
                "status": reading["status"],
                "blockage_location": blockage["location"],
                "blockage_severity": blockage["severity"],
                "surface_blockage": blockage["surface"],
                "internal_blockage": blockage["internal"],
                **measurements,
                **field_quality,
                **derived,
            }
        )
    return records


def build_mock_sensor_timeseries_payload(
    snapshots: list[dict[str, Any]],
    *,
    scenario: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Build a reusable timeseries payload from snapshot payloads."""

    records: list[dict[str, Any]] = []
    for snapshot_index, snapshot in enumerate(snapshots):
        for record in build_mock_sensor_records(snapshot):
            records.append(
                {
                    "scenario_id": scenario["id"],
                    "snapshot_index": snapshot_index,
                    **record,
                }
            )

    first_snapshot = snapshots[0] if snapshots else {}

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "drain-sensor-simulator",
        "generated_at": generated_at,
        "scenario": scenario,
        "network": first_snapshot.get(
            "network",
            {
                "nodes": [*DRAIN_IDS, "OUTFALL"],
                "topology": [
                    {"from": upstream, "to": downstream}
                    for upstream, downstream in NETWORK_TOPOLOGY
                ],
            },
        ),
        "units": NORMALIZED_UNITS,
        "snapshots": snapshots,
        "records": records,
    }


def dumps_mock_sensor_payload(payload: dict[str, Any]) -> str:
    """Serialize a mock sensor payload as pretty JSON."""

    return json.dumps(payload, ensure_ascii=False, indent=2)


def dumps_mock_sensor_records_jsonl(records: list[dict[str, Any]]) -> str:
    """Serialize flattened mock records as JSON Lines."""

    return "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in records
    )
