# Team PoC Reference Notes

팀에서 임시로 만든 `xgboost (1).zip` PoC는 다음 용도로만 참고한다.

## 참고할 점

- Streamlit으로 이미지 업로드 영역과 판단 결과를 한 화면에 보여주는 구조
- `st.cache_resource`로 모델을 캐싱하는 패턴
- YOLO 결과와 XGBoost 판단 결과를 UI에 함께 배치하는 대시보드 방향

## 그대로 쓰지 않을 점

- 절대 경로 기반 `best.pt` 로딩
- `yolo_score`, `velocity`, `water_level` 3개만 사용하는 단순 XGBoost 입력
- 상부 막힘과 내부 막힘을 구분하지 않는 구조
- 수위/유속을 사용자가 직접 입력하는 구조
- 실제 정확도처럼 보일 수 있는 랜덤 학습 데이터 표현

## 현재 프로젝트와의 관계

현재 `drain-sensor-simulator`는 YOLO/XGBoost 통합 전 단계다.

목표는 아래 센서값을 가상으로 생성하고 시각화하는 것이다.

- `surface_water_level`
- `inlet_flow`
- `pipe_water_level`
- `pipe_flow_speed`
- `pipe_flow_rate`
- `stagnation_score`

향후 통합 단계에서 팀 PoC의 화면 구성을 참고하되, 센서 모델은 이 프로젝트의 상부/내부/복합 막힘 구조를 기반으로 한다.
