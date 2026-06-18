# Backend API Specification

Drain Sensor Simulator의 Mock API를 백엔드에서 polling 방식으로 연동하기 위한 명세입니다.

이 API는 실제 센서 API가 아니라 Streamlit 데모 화면 또는 시뮬레이션 모델이 만든 mock 센서값을 제공합니다.

## 기본 정보

| 항목 | 값 |
|---|---|
| 기본 API 주소 | `http://127.0.0.1:8765` |
| Docker 기본 UI 주소 | `http://127.0.0.1:8501` |
| 응답 형식 | JSON |
| 인증 | 없음 |
| CORS | `Access-Control-Allow-Origin: *` |
| 최신 schema | `virtual-drain-sensor.v1` |
| 권장 호출 방식 | HTTP GET polling |
| WebSocket/SSE | 지원하지 않음 |

Docker 실행:

```powershell
docker pull ghcr.io/monancho/drain-sensor-simulator-dev:latest
docker run --rm -p 8501:8501 -p 8765:8765 ghcr.io/monancho/drain-sensor-simulator-dev:latest
```

상태 확인:

```http
GET /health
```

응답:

```json
{
  "status": "ok",
  "schema_version": "virtual-drain-sensor.v1"
}
```

## 백엔드 연동 권장 흐름

1. Docker 컨테이너를 실행합니다.
2. Streamlit UI에서 시뮬레이션 조건을 조정합니다.
3. Streamlit UI에서 `1 step` 또는 `시작`을 눌러 runtime snapshot을 저장합니다.
4. 백엔드는 `/drains/{id}/latest`를 주기적으로 polling합니다.
5. 상세 mock/debug 필드가 필요할 때만 `/detail` endpoint를 사용합니다.

권장 polling 예:

```text
2초마다 GET /drains/b/latest
```

주의:

- `/drains/{id}/latest`는 Streamlit이 마지막으로 저장한 runtime snapshot을 읽습니다.
- Streamlit에서 아직 한 번도 `1 step` 또는 `시작`을 실행하지 않았다면 `404 runtime_snapshot_not_found`가 반환될 수 있습니다.
- 백엔드가 실제 센서처럼 최소 필드만 받으려면 `/drains/{id}/latest`를 사용하세요.
- `status`, `inlet_flow`, `blockage` 같은 시뮬레이터/판단용 필드는 기본 latest 응답에 포함하지 않습니다.

## 핵심 Endpoint

### Compact Latest

현재 Streamlit 화면 상태 기준으로 특정 빗물받이의 최신 센서값만 반환합니다.

```http
GET /drains/a/latest
GET /drains/b/latest
GET /drains/c/latest
```

alias도 지원합니다.

```http
GET /drains/drain_a/latest
GET /drains/drain_b/latest
GET /drains/drain_c/latest
```

응답 예:

```json
{
  "drain_id": "DRAIN_B",
  "timestamp": "2026-06-18T00:20:00",
  "surface_water_level": 0.61,
  "pipe_water_level": 0.42,
  "pipe_flow_speed": 0.31
}
```

필드:

| 필드 | 타입 | 범위/예시 | 설명 |
|---|---|---|---|
| `drain_id` | string | `DRAIN_A`, `DRAIN_B`, `DRAIN_C` | 배수구 ID |
| `timestamp` | string | ISO datetime | 해당 snapshot 생성 시각 |
| `surface_water_level` | number | `0.0`~`1.0` | 도로 위 물고임 수위 |
| `pipe_water_level` | number | `0.0`~`1.0` | 관로 내부 수위 |
| `pipe_flow_speed` | number | `0.0`~`1.0` | 관로 유속 |

기본 latest 응답에 없는 필드:

- `status`
- `inlet_flow`
- `blockage`
- `derived`
- `quality`
- `runtime`

이 필드들은 실제 센서값이라기보다 시뮬레이터/디버그/판단용이므로 compact latest에서는 제외합니다.

### Detail Latest

현재 Streamlit 화면 상태 기준으로 특정 빗물받이의 상세 mock record를 반환합니다.

```http
GET /drains/a/latest/detail
GET /drains/b/latest/detail
GET /drains/c/latest/detail
```

응답 예:

```json
{
  "schema_version": "virtual-drain-sensor.v1",
  "source": "drain-sensor-simulator",
  "mode": "runtime_latest",
  "drain_id": "DRAIN_B",
  "view": "detail",
  "runtime": {
    "producer": "streamlit",
    "generated_at": "2026-06-18T00:20:00",
    "time_step": 12,
    "elapsed_minutes": 12
  },
  "latest": {
    "sensor_id": "SIM-DRAIN_B",
    "drain_id": "DRAIN_B",
    "observed_at": "2026-06-18T00:20:00",
    "time_step": 12,
    "elapsed_minutes": 12.0,
    "quality": "mock",
    "quality_flags": "mock",
    "status": "상부 유입 막힘 의심",
    "blockage_location": "상부",
    "blockage_severity": 0.72,
    "surface_blockage": 0.72,
    "internal_blockage": 0.0,
    "surface_water_level": 0.61,
    "inlet_flow": 0.08,
    "pipe_water_level": 0.42,
    "pipe_flow_speed": 0.31,
    "pipe_flow_rate": 0.13
  }
}
```

상세 응답의 `latest`는 flat record입니다. 실제 응답에는 위 예시보다 더 많은 `derived` 계열 필드가 포함될 수 있습니다.

## 전체 Runtime Snapshot

현재 Streamlit 화면이 마지막으로 저장한 전체 snapshot을 가져옵니다.

```http
GET /api/v1/sensors/snapshot?source=runtime
```

용도:

- 전체 A/B/C 상태를 한 번에 확인
- 디버깅
- 백엔드 개발 중 필드 탐색

실제 백엔드 polling에는 `/drains/{id}/latest` 사용을 권장합니다.

## Legacy / Simulation Endpoint

아래 endpoint는 mock API 개발, scenario 테스트, 시뮬레이션 조건 테스트용입니다. 백엔드가 “현재 Streamlit 화면 상태”를 가져오려는 목적이라면 기본적으로 사용하지 않아도 됩니다.

| Endpoint | 용도 |
|---|---|
| `GET /api/v1/sensors/schema` | schema, scenario, live profile 목록 확인 |
| `GET /api/v1/sensors/snapshot` | query 조건으로 즉석 snapshot 생성 |
| `GET /api/v1/sensors/records` | query 조건 snapshot을 flat records로 반환 |
| `GET /api/v1/sensors/{a,b,c}/latest` | query 조건 기준 latest |
| `GET /api/v1/sensors/{a,b,c}/latest?source=runtime` | runtime latest 상세 wrapper |
| `GET /api/v1/sensors/{a,b,c}/latest?mode=live&profile=storm_pulse` | stateless live mock latest |
| `GET /api/v1/sensors/timeseries?scenario=rain_stops` | scenario timeseries |
| `POST /api/v1/sensors/simulate` | JSON body 조건으로 snapshot 생성 |
| `POST /api/v1/sensors/scenario` | JSON body 조건으로 scenario timeseries 생성 |

## Live Mock Latest

`mode=live`는 Streamlit 화면 상태와 별개로 API가 자체적으로 tick 기반 mock 값을 생성하는 테스트 기능입니다.

```http
GET /api/v1/sensors/b/latest?mode=live&profile=storm_pulse
```

재현 가능한 호출:

```http
GET /api/v1/sensors/b/latest?mode=live&profile=storm_pulse&tick=10&seed=demo
```

지원 profile:

| profile | 의미 |
|---|---|
| `normal_drain` | 정상 배수 |
| `storm_pulse` | 강우가 주기적으로 강해졌다 약해지는 상황 |
| `surface_debris_live` | 상부 막힘 변동 |
| `internal_stagnation_live` | 내부 정체 변동 |
| `mixed_unstable` | 복합 불안정 |

주의:

- 이 기능은 Streamlit 화면 조작값을 읽지 않습니다.
- 실제 백엔드가 데모 화면과 같은 값을 가져오려면 `/drains/{id}/latest`를 사용하세요.

## 에러 응답

### Runtime snapshot 없음

Streamlit에서 아직 `1 step` 또는 `시작`을 실행하지 않은 경우:

HTTP status:

```text
404
```

응답:

```json
{
  "error": "runtime_snapshot_not_found",
  "detail": "Runtime snapshot not found: ...",
  "hint": "Run Streamlit and start the simulation first."
}
```

처리 방법:

- UI에서 `1 step`을 한 번 누른 뒤 다시 호출합니다.
- 자동 진행 중이면 1~2초 뒤 다시 polling합니다.

### 잘못된 요청

HTTP status:

```text
400
```

응답:

```json
{
  "error": "bad_request",
  "detail": "scenario is for timeseries endpoints; use latest with snapshot query params"
}
```

### 없는 endpoint

HTTP status:

```text
404
```

응답:

```json
{
  "error": "not_found"
}
```

## 값 해석 기준

모든 주요 센서값은 mock normalized value입니다.

```text
0.0 = 낮음 / 거의 없음
1.0 = 높음 / 포화에 가까움
```

해석 정책:

| 패턴 | 의미 |
|---|---|
| 도로 위 물고임 증가 + 유입량 감소 | 상부 막힘 의심 |
| 관로 수위 증가 + 관로 유속 감소 | 내부 정체 의심 |
| 관로 수위 높음 + 관로 유속 높음 | 배수 진행 중 |
| 관로 수위 높음 + 관로 유속 낮음 | 정체 의심 |

주의:

- `surface_water_level`, `pipe_water_level`, `pipe_flow_speed`는 실제 단위 수치가 아니라 `0~1` 정규화된 mock 값입니다.
- Canvas는 실제 유체역학이 아니라 센서값을 직관적으로 보여주는 visual metaphor입니다.
- 이 프로젝트는 실제 센서 API, SWMM/PySWMM, XGBoost, YOLO, CSV 학습 데이터 생성기를 포함하지 않습니다.

## 백엔드 예시 코드

JavaScript fetch 예:

```js
async function fetchDrainLatest(drain = "b") {
  const response = await fetch(`http://127.0.0.1:8765/drains/${drain}/latest`);
  if (!response.ok) {
    throw new Error(`Drain API failed: ${response.status}`);
  }
  return response.json();
}

setInterval(async () => {
  const latest = await fetchDrainLatest("b");
  console.log(latest);
}, 2000);
```

Python requests 예:

```python
import time
import requests

while True:
    response = requests.get("http://127.0.0.1:8765/drains/b/latest", timeout=3)
    response.raise_for_status()
    print(response.json())
    time.sleep(2)
```

## 백엔드 연동 체크리스트

- [ ] Docker 컨테이너가 실행 중이다.
- [ ] `GET /health`가 `status: ok`를 반환한다.
- [ ] Streamlit UI에서 `1 step` 또는 `시작`을 실행했다.
- [ ] `GET /drains/b/latest`가 compact JSON을 반환한다.
- [ ] 백엔드는 1~2초 polling으로 최신값을 갱신한다.
- [ ] 상세 필드가 필요한 경우에만 `/detail` endpoint를 사용한다.
- [ ] 실제 운영 센서 연동과 혼동하지 않도록 mock source임을 표시한다.
