# Drain Sensor Simulator

실제 센서 없이 배수구 수위/유속 mock 값을 테스트하기 위한 Streamlit + Mock API 시뮬레이터입니다.

Docker 이미지 하나로 화면 데모와 백엔드 polling API를 함께 실행할 수 있습니다.

## Quick Start

### Windows PowerShell

```powershell
docker pull ghcr.io/monancho/drain-sensor-simulator-dev:latest
docker run --rm -p 8501:8501 -p 8765:8765 ghcr.io/monancho/drain-sensor-simulator-dev:latest
```

### Linux/macOS/Git Bash

```bash
docker pull ghcr.io/monancho/drain-sensor-simulator-dev:latest

docker run --rm \
  -p 8501:8501 \
  -p 8765:8765 \
  ghcr.io/monancho/drain-sensor-simulator-dev:latest
```

접속:

- Streamlit UI: `http://127.0.0.1:8501`
- Mock API: `http://127.0.0.1:8765`

## 기본 사용 흐름

1. Docker 컨테이너를 실행합니다.
2. 브라우저에서 `http://127.0.0.1:8501`을 엽니다.
3. 왼쪽 사이드바에서 강우량, 파이프 용량, A/B/C 막힘 조건을 조정합니다.
4. `1 step` 또는 `시작`을 눌러 현재 상태를 저장합니다.
5. 백엔드/Postman에서 `GET /drains/b/latest`를 polling합니다.

처음에는 Streamlit이 아직 snapshot을 저장하지 않았으므로 latest API가 `runtime_snapshot_not_found`를 반환할 수 있습니다. UI에서 `1 step`을 한 번 누른 뒤 다시 호출하세요.

## 핵심 API

상태 확인:

```http
GET /health
```

최신 센서값:

```http
GET /drains/a/latest
GET /drains/b/latest
GET /drains/c/latest
```

상세 mock/debug 값:

```http
GET /drains/b/latest/detail
```

compact latest 응답 예:

```json
{
  "drain_id": "DRAIN_B",
  "timestamp": "2026-06-18T00:20:00",
  "surface_water_level": 0.61,
  "pipe_water_level": 0.42,
  "pipe_flow_speed": 0.31
}
```

백엔드 연동 상세 명세는 [`docs/BACKEND_API_SPEC.md`](docs/BACKEND_API_SPEC.md)를 확인하세요.

## 설정 공유

다른 컴퓨터와 같은 시뮬레이션 조건을 맞출 수 있습니다.

1. 왼쪽 사이드바에서 `설정 공유`를 엽니다.
2. `현재 설정 JSON`을 복사하거나 JSON 파일로 다운로드합니다.
3. 다른 컴퓨터에서 같은 Docker 이미지를 실행합니다.
4. `설정 공유`에 JSON을 붙여넣고 `붙여넣은 설정 적용`을 누릅니다.

공유되는 값:

- 강우 기준값/변동량/변화 속도
- 파이프 용량
- A/B/C 막힘 위치와 정도
- 막힘 변동량/변화 속도
- 자동 진행 간격

## 문서

- 백엔드 API 명세: [`docs/BACKEND_API_SPEC.md`](docs/BACKEND_API_SPEC.md)
- 시뮬레이션 정책: [`docs/SENSOR_SIMULATION_POLICY.md`](docs/SENSOR_SIMULATION_POLICY.md)

## 로컬 개발

```bash
pip install -r requirements-dev.txt
streamlit run app.py
```

별도 터미널에서 Mock API 실행:

```bash
python api.py
```

검증:

```bash
pytest -q
ruff check .
python -m py_compile app.py simulation.py sensor_model.py visualization.py canvas_renderer.py sensor_payload.py sensor_api_service.py api.py runtime_state.py
```

Docker Compose는 로컬 개발/통합 테스트용으로만 사용합니다.

```bash
docker compose up --build
```

## 범위

이 프로젝트는 mock sensor simulator입니다.

- 실제 센서 API를 붙이지 않습니다.
- WebSocket/SSE를 제공하지 않습니다.
- Redis/DB를 사용하지 않습니다.
- XGBoost, YOLO, SWMM/PySWMM, CSV 학습 데이터 생성기를 포함하지 않습니다.
- Canvas는 실제 유체역학이 아니라 센서값을 직관적으로 보여주는 visual metaphor입니다.
