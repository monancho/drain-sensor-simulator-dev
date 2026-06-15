너는 drain-sensor-simulator의 Canvas 시각화만 개선하는 Codex 에이전트다.

목표:
Canvas 화면에서 물이 실제로 막히고 차오르는 느낌을 더 직관적으로 만든다.

수정 대상:
- canvas_renderer.py
- visualization.py

유지할 것:
- simulation.py의 센서 계산값은 왜곡하지 않는다.
- 시각적 과장은 visual payload 또는 Canvas 내부에서만 처리한다.
- XGBoost, YOLO, SWMM/PySWMM은 추가하지 않는다.

개선 방향:
1. rainfall이 높을수록 빗방울이 더 많고 빠르게 보이게 한다.
2. surface_water_level이 높을수록 도로 위 물웅덩이가 커지게 한다.
3. inlet_flow가 높을수록 배수구 안으로 떨어지는 물방울이 많아지게 한다.
4. pipe_flow_speed가 높을수록 파이프 물방울 이동이 빨라지게 한다.
5. pipe_flow_rate가 높을수록 파이프 물방울 밀도가 높아지게 한다.
6. surface_blockage가 높으면 배수구 위 쓰레기가 더 많이 보이게 한다.
7. internal_blockage가 높으면 배수구 내부 수위와 정체 pulse가 더 강하게 보이게 한다.

검증:
```bash
pytest -q
ruff check .
streamlit run app.py
```
