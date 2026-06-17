import pytest

from runtime_state import (
    RuntimeSnapshotNotFound,
    get_runtime_latest_record,
    get_runtime_snapshot_path,
    read_runtime_snapshot,
    runtime_snapshot_exists,
    write_runtime_snapshot,
)
from sensor_payload import SCHEMA_VERSION


def sample_runtime_payload():
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "drain-sensor-simulator",
        "mode": "runtime_snapshot",
        "generated_at": "2026-06-17T00:00:00",
        "rainfall": 0.7,
        "pipe_capacity": 1.0,
        "time_step": 3,
        "elapsed_minutes": 3,
        "runtime": {
            "producer": "streamlit",
            "generated_at": "2026-06-17T00:00:00",
            "time_step": 3,
            "elapsed_minutes": 3,
        },
        "records": [
            {"drain_id": "DRAIN_A", "surface_water_level": 0.1},
            {"drain_id": "DRAIN_B", "surface_water_level": 0.4},
            {"drain_id": "DRAIN_C", "surface_water_level": 0.2},
        ],
    }


def test_runtime_snapshot_write_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAIN_SIM_RUNTIME_DIR", str(tmp_path))
    payload = sample_runtime_payload()

    path = write_runtime_snapshot(payload)

    assert path == get_runtime_snapshot_path()
    assert runtime_snapshot_exists()
    assert read_runtime_snapshot() == payload


def test_runtime_latest_record_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAIN_SIM_RUNTIME_DIR", str(tmp_path))
    write_runtime_snapshot(sample_runtime_payload())

    latest = get_runtime_latest_record("DRAIN_B")

    assert latest["drain_id"] == "DRAIN_B"
    assert latest["surface_water_level"] == 0.4


def test_runtime_snapshot_missing_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAIN_SIM_RUNTIME_DIR", str(tmp_path))

    assert not runtime_snapshot_exists()
    with pytest.raises(RuntimeSnapshotNotFound):
        read_runtime_snapshot()
