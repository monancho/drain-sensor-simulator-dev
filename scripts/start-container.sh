#!/usr/bin/env sh
set -eu

: "${DRAIN_SIM_RUNTIME_DIR:=/app/.runtime}"
: "${API_HOST:=0.0.0.0}"
: "${API_PORT:=8765}"
: "${STREAMLIT_HOST:=0.0.0.0}"
: "${STREAMLIT_PORT:=8501}"

mkdir -p "$DRAIN_SIM_RUNTIME_DIR"

python api.py --host "$API_HOST" --port "$API_PORT" &
API_PID="$!"

cleanup() {
  kill "$API_PID" 2>/dev/null || true
  wait "$API_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

streamlit run app.py \
  --server.address "$STREAMLIT_HOST" \
  --server.port "$STREAMLIT_PORT" \
  --server.headless true
