.PHONY: install install-dev run run-api test lint format check

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

run:
	streamlit run app.py

run-api:
	python api.py

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .

check: lint test
