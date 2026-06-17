FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DRAIN_SIM_RUNTIME_DIR=/app/.runtime \
    API_HOST=0.0.0.0 \
    API_PORT=8765 \
    STREAMLIT_HOST=0.0.0.0 \
    STREAMLIT_PORT=8501

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p "$DRAIN_SIM_RUNTIME_DIR" && chmod +x scripts/start-container.sh

EXPOSE 8501 8765

CMD ["./scripts/start-container.sh"]
