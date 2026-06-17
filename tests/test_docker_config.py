from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_runs_streamlit_and_api_entrypoint():
    dockerfile = read_text("Dockerfile")

    assert "FROM python:3.11-slim" in dockerfile
    assert "DRAIN_SIM_RUNTIME_DIR=/app/.runtime" in dockerfile
    assert "EXPOSE 8501 8765" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:{port}/health" in dockerfile
    assert 'CMD ["./scripts/start-container.sh"]' in dockerfile


def test_compose_exposes_ui_api_and_shared_runtime_volume():
    compose = read_text("docker-compose.yml")

    assert "8501:8501" in compose
    assert "8765:8765" in compose
    assert "DRAIN_SIM_RUNTIME_DIR: /app/.runtime" in compose
    assert "drain-sensor-runtime:/app/.runtime" in compose
    assert "healthcheck:" in compose
    assert "http://127.0.0.1:8765/health" in compose


def test_container_start_script_launches_api_and_streamlit():
    script = read_text("scripts/start-container.sh")

    assert '"api.py",' in script
    assert '"--host",' in script
    assert '"--port",' in script
    assert '"streamlit",' in script
    assert '"run",' in script
    assert '"app.py",' in script
    assert "--server.address" in script
    assert "subprocess.Popen(api_cmd)" in script
    assert "subprocess.Popen(streamlit_cmd)" in script
    assert "signal.signal(signal.SIGTERM, handle_signal)" in script
    assert "stop_processes()" in script


def test_github_container_registry_workflow_builds_image():
    workflow = read_text(".github/workflows/docker-image.yml")

    assert "ghcr.io/monancho/drain-sensor-simulator-dev" in workflow
    assert "packages: write" in workflow
    assert "docker/login-action@v3" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "type=raw,value=latest" in workflow
