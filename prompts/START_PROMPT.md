너는 drain-sensor-simulator 프로젝트를 이어서 구현하는 Codex 에이전트다.

먼저 아래 파일을 반드시 읽어라.

1. AGENTS.md
2. README.md
3. docs/SENSOR_SIMULATION_POLICY.md
4. app.py
5. simulation.py
6. sensor_model.py
7. visualization.py
8. canvas_renderer.py

목표:
현재 구현된 Streamlit 기반 가상 배수구 센서 시뮬레이터를 점검하고, 실행 가능한 상태로 다듬어라.

중요 범위:
- 이 프로젝트는 XGBoost 학습기가 아니다.
- YOLO 실행기를 만들지 않는다.
- SWMM/PySWMM을 붙이지 않는다.
- 실제 센서 API를 붙이지 않는다.
- CSV 학습 데이터 생성기를 만들지 않는다.

반드시 유지할 정책:
- 상부 막힘과 내부 막힘을 구분한다.
- 상부 막힘은 도로 위 물고임 증가 + inlet_flow 감소로 표현한다.
- 내부 막힘은 pipe_water_level 증가 + pipe_flow_speed 감소로 표현한다.
- 수위 높음 + 유속 높음은 위험이 아니라 `배수 진행 중`으로 해석한다.
- 수위 높음 + 유속 낮음은 `정체 의심` 또는 `내부 정체 의심`으로 해석한다.
- Canvas 시각화는 실제 유체역학이 아니라 센서값을 직관적으로 보여주는 visual metaphor다.

해야 할 작업:
1. 프로젝트가 `pip install -r requirements-dev.txt` 후 실행 가능한지 점검한다.
2. `pytest -q`를 실행하고 실패하면 고친다.
3. `ruff check .`를 실행하고 심각한 오류가 있으면 고친다.
4. `streamlit run app.py` 실행 시 import/syntax 오류가 없는지 점검한다.
5. 상부 막힘/내부 막힘/복합 막힘 기본 시나리오가 의도한 센서 패턴을 만드는지 확인한다.
6. 문제가 있으면 최소 변경으로 수정한다.

완료 후 반드시 채팅으로 아래 형식으로 보고하라.

## 작업 결과
- 변경 파일:
- 핵심 변경:
- 실행/검증:
- 남은 이슈:

## 다음 작업 프롬프트
아래 프롬프트를 다음 작업에서 그대로 사용하세요.

```text
<현재 상태에 맞는 다음 작업 프롬프트>
```
