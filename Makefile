.PHONY: install install-dev run run-api docker-build docker-up test lint format compile check

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

run:
	streamlit run app.py

run-api:
	python api.py

docker-build:
	docker build -t drain-sensor-simulator:local .

docker-up:
	docker compose up --build

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .

compile:
	python -m py_compile app.py simulation.py sensor_model.py visualization.py canvas_renderer.py sensor_payload.py sensor_api_service.py api.py runtime_state.py

check: lint test compile
