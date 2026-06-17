#!/usr/bin/env sh
set -eu

: "${DRAIN_SIM_RUNTIME_DIR:=/app/.runtime}"
: "${API_HOST:=0.0.0.0}"
: "${API_PORT:=8765}"
: "${STREAMLIT_HOST:=0.0.0.0}"
: "${STREAMLIT_PORT:=8501}"

mkdir -p "$DRAIN_SIM_RUNTIME_DIR"

python - <<'PY'
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


api_cmd = [
    sys.executable,
    "api.py",
    "--host",
    os.environ.get("API_HOST", "0.0.0.0"),
    "--port",
    os.environ.get("API_PORT", "8765"),
]
streamlit_cmd = [
    "streamlit",
    "run",
    "app.py",
    "--server.address",
    os.environ.get("STREAMLIT_HOST", "0.0.0.0"),
    "--server.port",
    os.environ.get("STREAMLIT_PORT", "8501"),
    "--server.headless",
    "true",
]

processes: list[subprocess.Popen[bytes]] = []
stopping = False


def stop_processes() -> None:
    global stopping
    if stopping:
        return
    stopping = True
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in processes:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def handle_signal(signum: int, _frame: object) -> None:
    stop_processes()
    raise SystemExit(128 + signum)


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

processes.append(subprocess.Popen(api_cmd))
processes.append(subprocess.Popen(streamlit_cmd))

try:
    while True:
        for process in processes:
            exit_code = process.poll()
            if exit_code is not None:
                stop_processes()
                raise SystemExit(exit_code)
        time.sleep(1)
finally:
    stop_processes()
PY
