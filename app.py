"""Streamlit app for the drain sensor simulator."""

from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from canvas_renderer import render_canvas
from sensor_api_service import SCENARIO_DEFINITIONS, simulate_sensor_timeseries
from sensor_model import attach_sensor_status
from sensor_payload import (
    build_mock_sensor_payload,
    build_mock_sensor_records,
    dumps_mock_sensor_payload,
    dumps_mock_sensor_records_jsonl,
)
from simulation import DRAIN_IDS, BlockageLocation, initialize_drain_states, run_step
from visualization import build_current_table, build_visual_payload, draw_history_plot

DEFAULT_LOCATIONS: dict[str, BlockageLocation] = {
    "DRAIN_A": "없음",
    "DRAIN_B": "상부",
    "DRAIN_C": "복합",
}
DEFAULT_SEVERITIES = {
    "DRAIN_A": 0.20,
    "DRAIN_B": 0.55,
    "DRAIN_C": 0.85,
}
STEP_MINUTES = 1


def inject_theme_styles() -> None:
    """Apply small presentation styles for the Streamlit demo shell."""

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
        }
        .demo-strip {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0 1.1rem;
        }
        .demo-strip__item,
        .sensor-card {
            border: 1px solid #d8e0ea;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
        }
        .demo-strip__item {
            padding: 0.8rem 0.95rem;
        }
        .demo-strip__label,
        .sensor-card__label {
            color: #667085;
            font-size: 0.76rem;
            line-height: 1.2;
        }
        .demo-strip__value {
            color: #1d2939;
            font-size: 1.05rem;
            font-weight: 700;
            margin-top: 0.15rem;
        }
        .sensor-card {
            padding: 0.95rem;
            min-height: 246px;
        }
        .sensor-card--good {
            border-top: 4px solid #12b76a;
        }
        .sensor-card--watch {
            border-top: 4px solid #f79009;
        }
        .sensor-card--warning {
            border-top: 4px solid #f04438;
        }
        .sensor-card--danger {
            border-top: 4px solid #b42318;
        }
        .sensor-card__top {
            align-items: center;
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.75rem;
        }
        .sensor-card__id {
            color: #101828;
            font-weight: 800;
            letter-spacing: 0.02em;
        }
        .sensor-badge {
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 700;
            padding: 0.18rem 0.5rem;
            white-space: nowrap;
        }
        .sensor-badge--good {
            background: #dcfae6;
            color: #027a48;
        }
        .sensor-badge--watch {
            background: #fef0c7;
            color: #b54708;
        }
        .sensor-badge--warning {
            background: #fee4e2;
            color: #b42318;
        }
        .sensor-badge--danger {
            background: #fecdca;
            color: #912018;
        }
        .sensor-card__grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.7rem 0.85rem;
        }
        .sensor-card__metric {
            min-width: 0;
        }
        .sensor-card__metric-head {
            align-items: baseline;
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
        }
        .sensor-card__value {
            color: #101828;
            font-size: 1.05rem;
            font-weight: 750;
            margin-top: 0.08rem;
        }
        .sensor-card__bar {
            background: #eef2f6;
            border-radius: 999px;
            height: 6px;
            margin-top: 0.35rem;
            overflow: hidden;
        }
        .sensor-card__bar span {
            display: block;
            height: 100%;
        }
        .sensor-card__bar--surface span {
            background: #2e90fa;
        }
        .sensor-card__bar--inlet span {
            background: #12b76a;
        }
        .sensor-card__bar--pipe span {
            background: #0e9384;
        }
        .sensor-card__bar--flow span {
            background: #7a5af8;
        }
        .sensor-card__footer {
            border-top: 1px solid #eef2f6;
            color: #475467;
            font-size: 0.78rem;
            line-height: 1.45;
            margin-top: 0.85rem;
            padding-top: 0.65rem;
        }
        .sensor-card__hint {
            color: #175cd3;
            font-weight: 700;
            margin-top: 0.15rem;
        }
        .metric-note {
            color: #667085;
            font-size: 0.86rem;
            margin: -0.35rem 0 0.9rem;
        }
        .timeline-strip {
            align-items: stretch;
            display: flex;
            gap: 3px;
            height: 28px;
            margin: 0.4rem 0 0.7rem;
        }
        .timeline-segment {
            border-radius: 3px;
            min-width: 6px;
        }
        .timeline-segment--good {
            background: #12b76a;
        }
        .timeline-segment--watch {
            background: #f79009;
        }
        .timeline-segment--warning {
            background: #f04438;
        }
        .timeline-segment--danger {
            background: #b42318;
        }
        .timeline-summary {
            color: #475467;
            display: grid;
            font-size: 0.82rem;
            gap: 0.45rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            margin-bottom: 0.75rem;
        }
        .timeline-summary strong {
            color: #101828;
            display: block;
            font-size: 0.95rem;
        }
        @media (max-width: 900px) {
            .demo-strip {
                grid-template-columns: 1fr;
            }
            .timeline-summary {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_tone(status: str) -> str:
    """Map a Korean sensor status to a UI tone."""

    if "복합" in status:
        return "danger"
    if "상부" in status or "내부" in status or "병목" in status:
        return "warning"
    if "물고임" in status or "흐름" in status:
        return "watch"
    return "good"


def badge_color(status: str) -> str:
    """Map a Korean sensor status to a Streamlit badge color."""

    tone = status_tone(status)
    if tone == "danger":
        return "red"
    if tone == "warning":
        return "orange"
    if tone == "watch":
        return "yellow"
    return "green"


def progress_value(value: float) -> float:
    """Return a bounded value for Streamlit progress bars."""

    return max(0.0, min(1.0, value))


def percent_width(value: float) -> str:
    """Return a CSS percentage width for normalized values."""

    return f"{progress_value(value) * 100:.1f}%"


def metric_block(label: str, value: float, bar_class: str) -> str:
    """Render one metric cell for the custom sensor cards."""

    safe_label = html.escape(label)
    return f"""
      <div class="sensor-card__metric">
        <div class="sensor-card__metric-head">
          <div class="sensor-card__label">{safe_label}</div>
          <div class="sensor-card__value">{value:.2f}</div>
        </div>
        <div class="sensor-card__bar sensor-card__bar--{bar_class}">
          <span style="width:{percent_width(value)}"></span>
        </div>
      </div>
    """


def render_sensor_card_html(drain_id: str, state: dict[str, float | str]) -> str:
    """Render one compact sensor card as HTML."""

    status = str(state["sensor_status"])
    tone = status_tone(status)
    surface_water_level = float(state["surface_water_level"])
    inlet_flow = float(state["inlet_flow"])
    upstream_pipe_flow = float(state["upstream_pipe_flow"])
    pipe_segment_outflow = float(state["pipe_segment_outflow"])
    pipe_water_level = float(state["pipe_water_level"])
    pipe_flow_speed = float(state["pipe_flow_speed"])
    downstream_backwater = float(state.get("downstream_backwater", 0.0))
    pipe_surcharge_to_surface = float(state.get("pipe_surcharge_to_surface", 0.0))
    surface_spill_in = float(state.get("surface_spill_in", 0.0))
    surface_spill_out = float(state.get("surface_spill_out", 0.0))
    surface_blockage = float(state["surface_blockage"])
    internal_blockage = float(state["internal_blockage"])
    blockage_location = str(state["blockage_location"])
    passthrough_hint = ""
    if surface_blockage >= 0.25 and internal_blockage < 0.25 and upstream_pipe_flow > 0.02:
        passthrough_hint = (
            '<div class="sensor-card__hint">상부는 막혔지만 하부 관로 흐름은 통과 중</div>'
        )

    return f"""
    <div class="sensor-card sensor-card--{tone}">
      <div class="sensor-card__top">
        <div>
          <div class="sensor-card__id">{html.escape(drain_id)}</div>
          <div class="sensor-card__label">
            막힘 {html.escape(blockage_location)}
            · 상부 {surface_blockage:.2f}
            · 내부 {internal_blockage:.2f}
          </div>
        </div>
        <div class="sensor-badge sensor-badge--{tone}">{html.escape(status)}</div>
      </div>
      <div class="sensor-card__grid">
        {metric_block("도로 수위", surface_water_level, "surface")}
        {metric_block("유입량", inlet_flow, "inlet")}
        {metric_block("관로 수위", pipe_water_level, "pipe")}
        {metric_block("관로 유속", pipe_flow_speed, "flow")}
      </div>
      <div class="sensor-card__footer">
        상류 유입 {upstream_pipe_flow:.2f} · 하부 통과 {pipe_segment_outflow:.2f}<br>
        하류 병목 {downstream_backwater:.2f} · 역류 노면 {pipe_surcharge_to_surface:.2f}<br>
        도로 유입/유출 {surface_spill_in:.2f}/{surface_spill_out:.2f}
        {passthrough_hint}
      </div>
    </div>
    """


def render_demo_strip(*, rainfall: float, pipe_capacity: float, time_step: int) -> None:
    """Render a compact demo context strip."""

    elapsed_minutes = time_step * STEP_MINUTES
    st.markdown(
        f"""
        <div class="demo-strip">
          <div class="demo-strip__item">
            <div class="demo-strip__label">현재 강우 입력</div>
            <div class="demo-strip__value">{rainfall:.2f}</div>
          </div>
          <div class="demo-strip__item">
            <div class="demo-strip__label">파이프 용량 계수</div>
            <div class="demo-strip__value">{pipe_capacity:.2f}</div>
          </div>
          <div class="demo-strip__item">
            <div class="demo-strip__label">시뮬레이션 경과</div>
            <div class="demo-strip__value">{elapsed_minutes} min · step {time_step}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def initialize_session_state() -> None:
    """Initialize Streamlit session state."""

    if "drain_states" not in st.session_state:
        states = initialize_drain_states()
        for drain_id in DRAIN_IDS:
            states[drain_id]["blockage_location"] = DEFAULT_LOCATIONS[drain_id]
            states[drain_id]["blockage_severity"] = DEFAULT_SEVERITIES[drain_id]
        st.session_state.drain_states = states

    if "sensor_history" not in st.session_state:
        st.session_state.sensor_history = []

    if "time_step" not in st.session_state:
        st.session_state.time_step = 0


def append_history(
    *,
    rainfall: float,
    pipe_capacity: float,
    states: dict[str, dict[str, float | str]],
) -> None:
    """Append current states to session history."""

    timestamp = datetime.now().isoformat(timespec="seconds")
    elapsed_minutes = st.session_state.time_step * STEP_MINUTES

    for drain_id in DRAIN_IDS:
        state = states[drain_id]
        st.session_state.sensor_history.append(
            {
                "timestamp": timestamp,
                "time_step": st.session_state.time_step,
                "elapsed_minutes": elapsed_minutes,
                "drain_id": drain_id,
                "rainfall": round(float(rainfall), 4),
                "pipe_capacity": round(float(pipe_capacity), 4),
                "blockage_location": state["blockage_location"],
                "blockage_severity": state["blockage_severity"],
                "surface_blockage": state["surface_blockage"],
                "internal_blockage": state["internal_blockage"],
                "surface_water_level": state["surface_water_level"],
                "inlet_flow": state["inlet_flow"],
                "surface_recession": state["surface_recession"],
                "surface_spill_in": state["surface_spill_in"],
                "surface_spill_out": state["surface_spill_out"],
                "pipe_surcharge_to_surface": state["pipe_surcharge_to_surface"],
                "upstream_pipe_flow": state["upstream_pipe_flow"],
                "downstream_backwater": state["downstream_backwater"],
                "pipe_segment_outflow": state["pipe_segment_outflow"],
                "pipe_water_level": state["pipe_water_level"],
                "pipe_flow_speed": state["pipe_flow_speed"],
                "pipe_flow_rate": state["pipe_flow_rate"],
                "surface_water_delta": state["surface_water_delta"],
                "pipe_water_delta": state["pipe_water_delta"],
                "pipe_flow_delta": state["pipe_flow_delta"],
                "level_flow_ratio": state["level_flow_ratio"],
                "stagnation_score": state["stagnation_score"],
                "remaining_surface_capacity": state["remaining_surface_capacity"],
                "remaining_pipe_capacity": state["remaining_pipe_capacity"],
                "sensor_status": state["sensor_status"],
            }
        )


def simulate_one_step(
    *,
    rainfall: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
) -> None:
    """Run one simulation step and record sensor history."""

    st.session_state.time_step += 1
    next_states = run_step(
        st.session_state.drain_states,
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        blockage_configs=blockage_configs,
        step_minutes=STEP_MINUTES,
    )

    next_states = {
        drain_id: attach_sensor_status(next_states[drain_id])
        for drain_id in DRAIN_IDS
    }

    st.session_state.drain_states = next_states
    append_history(rainfall=rainfall, pipe_capacity=pipe_capacity, states=next_states)


def reset_simulation() -> None:
    """Reset all simulation state."""

    st.session_state.drain_states = initialize_drain_states()
    st.session_state.sensor_history = []
    st.session_state.time_step = 0


def render_summary_cards(states: dict[str, dict[str, float | str]]) -> None:
    """Render top summary cards."""

    st.subheader("현재 센서 패턴")
    st.markdown(
        '<div class="metric-note">상부 막힘은 도로 물고임과 유입량, 내부 막힘은 관로 수위와 유속을 분리해 봅니다.</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(3)

    for col, drain_id in zip(cols, DRAIN_IDS, strict=True):
        state = states[drain_id]
        col.markdown(
            render_sensor_card_html(drain_id, state),
            unsafe_allow_html=True,
        )


def render_live_dashboard(
    *,
    rainfall: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    auto_run: bool,
) -> None:
    """Render and optionally advance the live simulation area."""

    if auto_run:
        simulate_one_step(
            rainfall=rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=blockage_configs,
        )

    render_demo_strip(
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        time_step=st.session_state.time_step,
    )

    states = st.session_state.drain_states
    render_summary_cards(states)

    st.subheader("2D Canvas 센서 메타포")
    payload = build_visual_payload(
        states,
        rainfall=rainfall,
        time_step=st.session_state.time_step,
        elapsed_minutes=st.session_state.time_step * STEP_MINUTES,
    )
    st.html(render_canvas(payload, height=600), unsafe_allow_javascript=True)


def render_detail_panels() -> None:
    """Render non-live detail tables and history charts outside auto-refresh."""

    states = st.session_state.drain_states

    st.subheader("현재 센서값 테이블")
    current_table = build_current_table(states)
    st.dataframe(current_table, width="stretch", hide_index=True)

    history_df = pd.DataFrame(st.session_state.sensor_history)

    st.subheader("센서값 히스토리")
    graph_cols = st.columns(2)
    with graph_cols[0]:
        st.pyplot(draw_history_plot(history_df, "surface_water_level", "도로 위 물고임 변화"))
        st.pyplot(draw_history_plot(history_df, "pipe_water_level", "관로 수위 변화"))

    with graph_cols[1]:
        st.pyplot(draw_history_plot(history_df, "pipe_flow_speed", "관로 유속 변화"))
        st.pyplot(draw_history_plot(history_df, "inlet_flow", "배수구 유입량 변화"))

    st.subheader("최근 센서 기록")
    if history_df.empty:
        st.info("아직 기록이 없습니다. `시뮬레이션 실행`을 눌러 1 step을 기록하세요.")
    else:
        st.dataframe(history_df.tail(30), width="stretch", hide_index=True)


def render_mock_sensor_panel(*, rainfall: float, pipe_capacity: float) -> None:
    """Render current simulated sensor values as reusable mock payloads."""

    generated_at = datetime.now().isoformat(timespec="seconds")
    payload = build_mock_sensor_payload(
        st.session_state.drain_states,
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        time_step=st.session_state.time_step,
        elapsed_minutes=st.session_state.time_step * STEP_MINUTES,
        generated_at=generated_at,
    )
    records = build_mock_sensor_records(payload)
    payload_json = dumps_mock_sensor_payload(payload)
    records_jsonl = dumps_mock_sensor_records_jsonl(records)

    st.subheader("목업 센서 데이터")
    st.dataframe(pd.DataFrame(records), width="stretch", hide_index=True)

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "JSON snapshot",
        data=payload_json,
        file_name="mock_sensor_snapshot.json",
        mime="application/json",
        width="stretch",
    )
    download_cols[1].download_button(
        "JSONL records",
        data=records_jsonl,
        file_name="mock_sensor_records.jsonl",
        mime="application/x-ndjson",
        width="stretch",
    )

    with st.expander("현재 JSON payload"):
        st.json(payload, expanded=2)


def numeric_max(values: pd.Series) -> float:
    """Return a numeric max, treating all-null series as 0."""

    value = pd.to_numeric(values, errors="coerce").max()
    if pd.isna(value):
        return 0.0
    return float(value)


def numeric_min(values: pd.Series) -> float:
    """Return a numeric min, treating all-null series as 0."""

    value = pd.to_numeric(values, errors="coerce").min()
    if pd.isna(value):
        return 0.0
    return float(value)


def timeline_tone(statuses: pd.Series) -> str:
    """Return the strongest UI tone for a group of statuses."""

    joined = " ".join(str(status) for status in statuses)
    if "복합" in joined:
        return "danger"
    if "상부" in joined or "내부" in joined or "정체" in joined or "병목" in joined:
        return "warning"
    if "물고임" in joined or "흐름" in joined or "배수 진행" in joined:
        return "watch"
    return "good"


def render_timeseries_timeline(records_df: pd.DataFrame) -> None:
    """Render a compact visual summary for scenario records."""

    if records_df.empty:
        return

    segments = []
    for _, group in records_df.groupby("snapshot_index", sort=True):
        tone = timeline_tone(group["status"])
        step = int(numeric_max(group["time_step"]))
        surface = numeric_max(group["surface_water_level"])
        pipe_level = numeric_max(group["pipe_water_level"])
        pipe_speed = numeric_min(group["pipe_flow_speed"])
        title = html.escape(
            f"step {step} | 도로 {surface:.2f} | 관로 {pipe_level:.2f} | "
            f"최소 유속 {pipe_speed:.2f}"
        )
        segments.append(
            f'<div class="timeline-segment timeline-segment--{tone}" title="{title}"></div>'
        )

    peak_surface = numeric_max(records_df["surface_water_level"])
    peak_pipe = numeric_max(records_df["pipe_water_level"])
    min_speed = numeric_min(records_df["pipe_flow_speed"])
    final_status = html.escape(str(records_df.iloc[-1]["status"]))
    timeline_html = "".join(segments)

    st.markdown(
        f"""
        <div class="timeline-strip">{timeline_html}</div>
        <div class="timeline-summary">
          <div>최대 도로 수위<strong>{peak_surface:.2f}</strong></div>
          <div>최대 관로 수위<strong>{peak_pipe:.2f}</strong></div>
          <div>최소 관로 유속<strong>{min_speed:.2f}</strong></div>
          <div>마지막 상태<strong>{final_status}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_timeseries_preview_panel() -> None:
    """Render a scenario-based mock sensor timeseries preview."""

    st.subheader("시나리오 타임라인 목업")
    scenario_ids = list(SCENARIO_DEFINITIONS)
    control_cols = st.columns([0.55, 0.45])
    scenario_id = control_cols[0].selectbox(
        "시나리오",
        options=scenario_ids,
        index=scenario_ids.index("surface_blockage"),
        format_func=lambda key: SCENARIO_DEFINITIONS[key]["title_ko"],
        key="timeseries_scenario_id",
    )
    preview_steps = control_cols[1].slider(
        "타임라인 steps",
        6,
        60,
        int(SCENARIO_DEFINITIONS[scenario_id]["default_steps"]),
        1,
        key="timeseries_preview_steps",
    )
    realism_enabled = st.checkbox(
        "센서 현실감 적용",
        value=False,
        key="timeseries_realism_enabled",
    )
    realism_request: dict[str, float | int | str | bool] = {}
    if realism_enabled:
        realism_cols = st.columns([0.42, 0.28, 0.30])
        selected_realism = realism_cols[0].multiselect(
            "현실감 옵션",
            options=["noise", "missing", "stale", "spike", "stuck", "delay"],
            default=["noise"],
            key="timeseries_realism_options",
        )
        realism_seed = realism_cols[1].number_input(
            "seed",
            min_value=0,
            max_value=999999,
            value=42,
            step=1,
            key="timeseries_realism_seed",
        )
        realism_intensity = realism_cols[2].slider(
            "강도",
            0.0,
            1.0,
            0.35,
            0.05,
            key="timeseries_realism_intensity",
        )
        realism_request = {
            "seed": int(realism_seed),
            "noise": "noise" in selected_realism,
            "noise_scale": round(0.08 * realism_intensity, 4),
            "missing": "missing" in selected_realism,
            "missing_rate": round(0.18 * realism_intensity, 4),
            "stale": "stale" in selected_realism,
            "stale_rate": round(0.20 * realism_intensity, 4),
            "spike": "spike" in selected_realism,
            "spike_rate": round(0.16 * realism_intensity, 4),
            "spike_magnitude": round(0.45 * realism_intensity, 4),
            "stuck": "stuck" in selected_realism,
            "stuck_drain_id": "DRAIN_C",
            "stuck_field": "pipe_flow_speed",
            "delay": "delay" in selected_realism,
            "delay_steps": 1,
        }

    generated_at = datetime.now().isoformat(timespec="seconds")
    timeseries = simulate_sensor_timeseries(
        {
            "scenario": scenario_id,
            "steps": preview_steps,
            "step_minutes": STEP_MINUTES,
            "realism": realism_request,
        },
        generated_at=generated_at,
    )
    records_df = pd.DataFrame(timeseries["records"])
    scenario = timeseries["scenario"]
    timeseries_json = dumps_mock_sensor_payload(timeseries)
    timeseries_records_jsonl = dumps_mock_sensor_records_jsonl(timeseries["records"])

    st.caption(
        f"{scenario['title_ko']} · {scenario['steps']} steps · "
        f"{scenario['step_minutes']} min/step"
    )

    if not records_df.empty:
        render_timeseries_timeline(records_df)
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.pyplot(draw_history_plot(records_df, "surface_water_level", "도로 위 물고임 변화"))
        with chart_cols[1]:
            st.pyplot(draw_history_plot(records_df, "pipe_flow_speed", "관로 유속 변화"))
        st.dataframe(records_df.tail(12), width="stretch", hide_index=True)

    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Timeseries JSON",
        data=timeseries_json,
        file_name=f"mock_sensor_timeseries_{scenario_id}.json",
        mime="application/json",
        width="stretch",
    )
    download_cols[1].download_button(
        "Timeseries JSONL records",
        data=timeseries_records_jsonl,
        file_name=f"mock_sensor_timeseries_{scenario_id}.jsonl",
        mime="application/x-ndjson",
        width="stretch",
    )

    with st.expander("시나리오 JSON payload"):
        st.json(timeseries, expanded=1)


def render_live_dashboard_fragment(
    *,
    rainfall: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    auto_run: bool,
    auto_interval_ms: int,
) -> None:
    """Render the live dashboard in a fragment to avoid full-page auto refresh flicker."""

    run_every = auto_interval_ms / 1000 if auto_run else None
    if hasattr(st, "fragment"):
        fragment = st.fragment(run_every=run_every)(render_live_dashboard)
        fragment(
            rainfall=rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=blockage_configs,
            auto_run=auto_run,
        )
        return

    if auto_run:
        st.warning("현재 Streamlit 버전은 부드러운 자동 실행을 지원하지 않습니다.")
    render_live_dashboard(
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        blockage_configs=blockage_configs,
        auto_run=False,
    )


def main() -> None:
    """App entry point."""

    st.set_page_config(
        page_title="Drain Sensor Simulator",
        layout="wide",
        page_icon="🌧️",
    )
    inject_theme_styles()

    initialize_session_state()

    st.sidebar.title("시뮬레이션 입력")
    st.sidebar.caption("강우량과 배수구 막힘 위치를 조절합니다.")

    rainfall = st.sidebar.slider("강우량", 0.0, 1.0, 0.70, 0.01)
    pipe_capacity = st.sidebar.slider("파이프 용량", 0.2, 1.5, 1.00, 0.05)

    blockage_configs: dict[str, tuple[BlockageLocation, float]] = {}

    st.sidebar.divider()
    st.sidebar.subheader("배수구별 막힘 설정")

    for drain_id in DRAIN_IDS:
        location = st.sidebar.selectbox(
            f"{drain_id} 막힘 위치",
            options=["없음", "상부", "내부", "복합"],
            index=["없음", "상부", "내부", "복합"].index(DEFAULT_LOCATIONS[drain_id]),
            key=f"{drain_id}_location",
        )
        severity = st.sidebar.slider(
            f"{drain_id} 막힘 정도",
            0.0,
            1.0,
            DEFAULT_SEVERITIES[drain_id],
            0.01,
            key=f"{drain_id}_severity",
        )
        blockage_configs[drain_id] = (location, severity)  # type: ignore[assignment]

    st.sidebar.divider()

    auto_run = st.sidebar.checkbox("자동 실행", value=False)
    auto_interval_ms = st.sidebar.slider("자동 실행 간격(ms)", 800, 5000, 1500, 100)
    run_clicked = st.sidebar.button("시뮬레이션 실행", width="stretch")
    reset_clicked = st.sidebar.button("히스토리 초기화", width="stretch")

    if reset_clicked:
        reset_simulation()
        st.rerun()

    if run_clicked:
        simulate_one_step(
            rainfall=rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=blockage_configs,
        )

    st.title("배수구 가상 센서 시뮬레이터")
    st.caption(
        "상부 막힘, 내부 막힘, 복합 막힘에 따라 도로 위 물고임과 관로 수위·유속을 분리해 보여주는 MVP입니다."
    )
    render_live_dashboard_fragment(
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        blockage_configs=blockage_configs,
        auto_run=auto_run,
        auto_interval_ms=auto_interval_ms,
    )
    render_detail_panels()
    render_mock_sensor_panel(rainfall=rainfall, pipe_capacity=pipe_capacity)
    render_timeseries_preview_panel()

    with st.expander("이 시뮬레이터의 한계"):
        st.markdown(
            """
            - 실제 SWMM/PySWMM 또는 CFD 기반 시뮬레이터가 아닙니다.
            - 실제 수위·유속 예측 정확도를 보장하지 않습니다.
            - 목적은 실제 센서가 없을 때 센서값 흐름과 UI/UX를 검증하는 것입니다.
            - 향후 YOLO 결과와 실제 센서 API, XGBoost 판단 모델로 대체·확장할 수 있도록 필드명을 유지합니다.
            """
        )


if __name__ == "__main__":
    main()
