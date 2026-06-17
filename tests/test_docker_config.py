from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_runs_streamlit_and_api_entrypoint():
    dockerfile = read_text("Dockerfile")

    assert "FROM python:3.11-slim" in dockerfile
    assert "DRAIN_SIM_RUNTIME_DIR=/app/.runtime" in dockerfile
    assert "EXPOSE 8501 8765" in dockerfile
    assert 'CMD ["./scripts/start-container.sh"]' in dockerfile


def test_compose_exposes_ui_api_and_shared_runtime_volume():
    compose = read_text("docker-compose.yml")

    assert "8501:8501" in compose
    assert "8765:8765" in compose
    assert "DRAIN_SIM_RUNTIME_DIR: /app/.runtime" in compose
    assert "drain-sensor-runtime:/app/.runtime" in compose


def test_container_start_script_launches_api_and_streamlit():
    script = read_text("scripts/start-container.sh")

    assert "python api.py --host" in script
    assert "streamlit run app.py" in script
    assert "--server.address" in script
    assert "trap cleanup INT TERM EXIT" in script
