# Drain Sensor Simulator

`drain-sensor-simulator`는 실제 수위·유속 센서가 아직 없는 상황에서, 강우량과 배수구 막힘 위치에 따라 가상의 센서값을 생성하고 2D로 시각화하는 Streamlit 기반 MVP입니다.

## 핵심 목적

이 프로젝트는 다음이 아닙니다.

- XGBoost 학습기 아님
- YOLO 실행기 아님
- SWMM/PySWMM 수리해석 모델 아님
- 실제 침수 예측기 아님

현재 목적은 다음입니다.

```text
강우량
+ 상부 막힘 / 내부 막힘 / 복합 막힘
+ 시간 흐름
↓
도로 위 물고임
+ 배수구 유입량
+ 관로 수위
+ 관로 유속
+ 관로 유량
↓
드라마틱 2D Canvas 시각화
```

## 막힘 구분

| 구분 | 의미 |
|---|---|
| 상부 막힘 | 배수구 위 그레이팅/도로면에 쓰레기가 쌓여 물이 지하로 내려가지 못하는 상태 |
| 내부 막힘 | 물은 배수구 안으로 들어가지만 내부 관로에서 정체되는 상태 |
| 복합 막힘 | 상부와 내부 문제가 동시에 있는 상태 |

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run app.py
```

목업 센서 API를 따로 실행하려면:

```bash
python api.py
curl "http://127.0.0.1:8765/api/v1/sensors/snapshot?rainfall=1&steps=12&drain_b_location=surface&drain_b_severity=1"
```

Dev Container를 쓰는 경우:

```bash
code .
# VS Code에서 Reopen in Container
make run
```

## 개발 명령

```bash
make install-dev
make test
make lint
make run
```

## 주요 파일

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit UI, 세션 상태, 히스토리 관리 |
| `simulation.py` | 시간 기반 가상 센서 시뮬레이션 |
| `sensor_model.py` | 센서 상태 해석 |
| `visualization.py` | 그래프 및 Canvas payload 생성 |
| `canvas_renderer.py` | HTML Canvas 기반 드라마틱 물 흐름 렌더링 |
| `sensor_payload.py` | 목업 센서 payload/records 생성 |
| `sensor_api_service.py` | API 요청 정규화, 시뮬레이션 snapshot 생성, 외부 payload 검증 |
| `api.py` | 로컬 목업 센서 HTTP API |
| `docs/SENSOR_SIMULATION_POLICY.md` | 시뮬레이션 정책과 한계 |

## 목업 센서 API

`api.py`는 실제 센서 API가 아니라, 향후 실제 API 연결을 염두에 둔 로컬 계약 서버입니다.

| Endpoint | 설명 |
|---|---|
| `GET /health` | API 상태 확인 |
| `GET /api/v1/sensors/schema` | schema version, 기본 drain 설정, endpoint 목록 |
| `GET /api/v1/sensors/snapshot` | 현재 요청 조건으로 시뮬레이션한 JSON snapshot |
| `GET /api/v1/sensors/records` | snapshot을 flat records로 변환 |
| `POST /api/v1/sensors/simulate` | JSON body로 조건을 받아 snapshot 반환 |

Query 예시:

```bash
curl "http://127.0.0.1:8765/api/v1/sensors/snapshot?rainfall=0.8&pipe_capacity=1.0&steps=10&drain_a_location=none&drain_b_location=surface&drain_b_severity=0.9&drain_c_location=internal&drain_c_severity=0.8"
```

POST body 예시:

```json
{
  "rainfall": 0.8,
  "pipe_capacity": 1.0,
  "steps": 10,
  "drains": {
    "DRAIN_A": {"location": "none", "severity": 0.0},
    "DRAIN_B": {"location": "surface", "severity": 0.9},
    "DRAIN_C": {"location": "internal", "severity": 0.8}
  }
}
```

## 향후 통합

현재의 `blockage_location`, `blockage_severity`는 나중에 YOLO 결과로 대체할 수 있습니다.

```text
YOLO 결과
→ 정상 / 더러움 / 막힘
→ surface_blockage, internal_blockage 추정

실제 센서 API
→ surface_water_level, pipe_water_level, pipe_flow_speed 대체

XGBoost
→ YOLO 결과 + 센서값으로 최종 위험도 판단
```
