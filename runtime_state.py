"""Shared runtime snapshot storage for Streamlit-driven mock sensor state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

RUNTIME_DIR_ENV = "DRAIN_SIM_RUNTIME_DIR"
DEFAULT_RUNTIME_DIR = ".runtime"
RUNTIME_SNAPSHOT_FILENAME = "current_snapshot.json"


class RuntimeSnapshotError(RuntimeError):
    """Base error for runtime snapshot storage failures."""


class RuntimeSnapshotNotFound(RuntimeSnapshotError):
    """Raised when no runtime snapshot has been written yet."""


class RuntimeSnapshotInvalid(RuntimeSnapshotError):
    """Raised when the runtime snapshot exists but cannot be used."""


def get_runtime_dir() -> Path:
    """Return the runtime directory, honoring the Docker-friendly env override."""

    return Path(os.environ.get(RUNTIME_DIR_ENV, DEFAULT_RUNTIME_DIR))


def get_runtime_snapshot_path() -> Path:
    """Return the shared runtime snapshot path."""

    return get_runtime_dir() / RUNTIME_SNAPSHOT_FILENAME


def runtime_snapshot_exists() -> bool:
    """Return whether a runtime snapshot file currently exists."""

    return get_runtime_snapshot_path().is_file()


def write_runtime_snapshot(payload: dict[str, Any]) -> Path:
    """Atomically write the latest Streamlit runtime snapshot."""

    path = get_runtime_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)
    return path


def read_runtime_snapshot() -> dict[str, Any]:
    """Read the latest Streamlit runtime snapshot."""

    path = get_runtime_snapshot_path()
    if not path.is_file():
        raise RuntimeSnapshotNotFound(
            "runtime snapshot not found; run Streamlit and start the simulation first"
        )

    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise RuntimeSnapshotInvalid("runtime snapshot is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeSnapshotInvalid("runtime snapshot must be a JSON object")
    return payload


def get_runtime_latest_record(drain_id: str) -> dict[str, Any]:
    """Return the flat latest record for a drain from the runtime snapshot."""

    payload = read_runtime_snapshot()
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeSnapshotInvalid("runtime snapshot does not contain records")

    for record in records:
        if isinstance(record, dict) and record.get("drain_id") == drain_id:
            return record

    raise RuntimeSnapshotInvalid(f"runtime snapshot has no record for {drain_id}")
