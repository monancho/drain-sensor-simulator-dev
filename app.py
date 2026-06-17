"""Streamlit app for the drain sensor simulator."""

from __future__ import annotations

import html
import math
from datetime import datetime

import pandas as pd
import streamlit as st

from api import LIVE_PROFILES, build_live_latest_payload
from canvas_renderer import render_canvas
from runtime_state import get_runtime_snapshot_path, write_runtime_snapshot
from sensor_api_service import SCENARIO_DEFINITIONS, simulate_sensor_timeseries
from sensor_model import attach_sensor_status
from sensor_payload import (
    SCHEMA_VERSION,
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
LIVE_PROFILE_LABELS = {
    "normal_drain": "정상 배수",
    "storm_pulse": "강우 펄스",
    "surface_debris_live": "상부 막힘 변동",
    "internal_stagnation_live": "내부 정체 변동",
    "mixed_unstable": "복합 불안정",
}


def clamp_unit(value: float) -> float:
    """Clamp a normalized value to the sensor demo range."""

    return max(0.0, min(1.0, value))


def smooth_cycle_value(
    *,
    minimum: float,
    maximum: float,
    time_step: int,
    speed: float,
    phase: float = 0.0,
) -> float:
    """Return a smooth deterministic value inside a min/max range."""

    low, high = sorted((clamp_unit(minimum), clamp_unit(maximum)))
    if math.isclose(low, high):
        return low

    angle = (time_step + 1) * 0.075 * speed + phase
    wave = 0.5 + 0.5 * math.sin(angle)
    secondary_wave = 0.5 + 0.5 * math.sin(angle * 0.37 + phase * 0.5)
    blended = clamp_unit((wave * 0.82) + (secondary_wave * 0.18))
    return round(low + (high - low) * blended, 4)


def rainfall_variation_bounds(base_rainfall: float, variation: float) -> tuple[float, float]:
    """Return the clamped rainfall range for a base value and +/- variation."""

    base = clamp_unit(base_rainfall)
    amplitude = max(0.0, float(variation))
    return round(clamp_unit(base - amplitude), 4), round(clamp_unit(base + amplitude), 4)


def build_dynamic_blockage_configs(
    base_configs: dict[str, tuple[BlockageLocation, float]],
    *,
    time_step: int,
    amplitude: float,
    speed: float,
) -> dict[str, tuple[BlockageLocation, float]]:
    """Apply a small smooth wobble around manually selected blockage severities."""

    if amplitude <= 0:
        return base_configs

    adjusted_configs: dict[str, tuple[BlockageLocation, float]] = {}
    for index, drain_id in enumerate(DRAIN_IDS):
        location, severity = base_configs[drain_id]
        if location == "없음" or severity <= 0:
            adjusted_configs[drain_id] = (location, severity)
            continue

        phase = index * 1.9
        angle = (time_step + 1) * 0.055 * speed + phase
        wobble = math.sin(angle) * amplitude
        micro_wobble = math.sin(angle * 0.43 + phase) * amplitude * 0.35
        adjusted_configs[drain_id] = (
            location,
            round(clamp_unit(severity + wobble + micro_wobble), 4),
        )

    return adjusted_configs


def resolve_dynamic_inputs(
    *,
    base_rainfall: float,
    rainfall_variation: float,
    base_blockage_configs: dict[str, tuple[BlockageLocation, float]],
    time_step: int,
    rainfall_speed: float,
    blockage_amplitude: float,
    blockage_speed: float,
) -> tuple[float, dict[str, tuple[BlockageLocation, float]]]:
    """Resolve the effective inputs used for the next simulation step."""

    rainfall_min, rainfall_max = rainfall_variation_bounds(
        base_rainfall,
        rainfall_variation,
    )
    rainfall = smooth_cycle_value(
        minimum=rainfall_min,
        maximum=rainfall_max,
        time_step=time_step,
        speed=rainfall_speed,
    )
    blockage_configs = build_dynamic_blockage_configs(
        base_blockage_configs,
        time_step=time_step,
        amplitude=blockage_amplitude,
        speed=blockage_speed,
    )
    return rainfall, blockage_configs


def format_blockage_preview(
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
) -> str:
    """Format current blockage severities for the sidebar preview."""

    return " · ".join(
        f"{drain_id[-1]} {severity:.2f}"
        for drain_id, (_, severity) in blockage_configs.items()
    )


def build_latest_endpoint_url(
    *,
    base_url: str,
    drain_id: str,
    source: str,
    profile: str = "storm_pulse",
) -> str:
    """Build a Postman-friendly latest endpoint URL."""

    normalized_base_url = base_url.rstrip("/")
    drain_key = drain_id.replace("DRAIN_", "").lower()
    if source == "live":
        return (
            f"{normalized_base_url}/api/v1/sensors/{drain_key}/latest"
            f"?mode=live&profile={profile}"
        )
    if source == "snapshot":
        return f"{normalized_base_url}/api/v1/sensors/{drain_key}/latest"
    return f"{normalized_base_url}/api/v1/sensors/{drain_key}/latest?source=runtime"


def build_runtime_sensor_payload(
    states: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    pipe_capacity: float,
    time_step: int,
    generated_at: str,
) -> dict[str, object]:
    """Build the shared runtime snapshot written by the Streamlit UI."""

    elapsed_minutes = time_step * STEP_MINUTES
    payload = build_mock_sensor_payload(
        states,
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        time_step=time_step,
        elapsed_minutes=elapsed_minutes,
        generated_at=generated_at,
    )
    records = build_mock_sensor_records(payload)
    payload.update(
        {
            "schema_version": SCHEMA_VERSION,
            "mode": "runtime_snapshot",
            "rainfall": round(float(rainfall), 4),
            "pipe_capacity": round(float(pipe_capacity), 4),
            "time_step": int(time_step),
            "elapsed_minutes": elapsed_minutes,
            "records": records,
            "runtime": {
                "producer": "streamlit",
                "generated_at": generated_at,
                "time_step": int(time_step),
                "elapsed_minutes": elapsed_minutes,
                "state_file": str(get_runtime_snapshot_path()),
            },
        }
    )
    return payload


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


def render_demo_strip(
    *,
    rainfall: float,
    base_rainfall: float,
    rainfall_variation: float,
    pipe_capacity: float,
    time_step: int,
) -> None:
    """Render a compact demo context strip."""

    elapsed_minutes = time_step * STEP_MINUTES
    rainfall_label = "적용 강우 입력" if rainfall_variation > 0 else "현재 강우 입력"
    rainfall_detail = f'<div class="demo-strip__label">기준 {base_rainfall:.2f} · 변동 ±{rainfall_variation:.2f}</div>'
    st.markdown(
        f"""
        <div class="demo-strip">
          <div class="demo-strip__item">
            <div class="demo-strip__label">{rainfall_label}</div>
            <div class="demo-strip__value">{rainfall:.2f}</div>
            {rainfall_detail}
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

    if "runtime_snapshot_saved_at" not in st.session_state:
        st.session_state.runtime_snapshot_saved_at = None

    if "runtime_snapshot_error" not in st.session_state:
        st.session_state.runtime_snapshot_error = None

    if "auto_run_enabled" not in st.session_state:
        st.session_state.auto_run_enabled = False


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


def persist_runtime_snapshot(*, rainfall: float, pipe_capacity: float) -> None:
    """Write the current Streamlit sensor state for the mock API runtime source."""

    generated_at = datetime.now().isoformat(timespec="seconds")
    payload = build_runtime_sensor_payload(
        st.session_state.drain_states,
        rainfall=rainfall,
        pipe_capacity=pipe_capacity,
        time_step=st.session_state.time_step,
        generated_at=generated_at,
    )
    try:
        write_runtime_snapshot(payload)
    except OSError as exc:
        st.session_state.runtime_snapshot_error = str(exc)
    else:
        st.session_state.runtime_snapshot_saved_at = generated_at
        st.session_state.runtime_snapshot_error = None


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
    persist_runtime_snapshot(rainfall=rainfall, pipe_capacity=pipe_capacity)


def reset_simulation() -> None:
    """Reset all simulation state."""

    st.session_state.drain_states = initialize_drain_states()
    st.session_state.sensor_history = []
    st.session_state.time_step = 0
    st.session_state.runtime_snapshot_saved_at = None
    st.session_state.runtime_snapshot_error = None
    st.session_state.auto_run_enabled = False


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
    rainfall_variation: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    rainfall_speed: float,
    blockage_amplitude: float,
    blockage_speed: float,
    auto_run: bool,
    display_rainfall_override: float | None = None,
) -> None:
    """Render and optionally advance the live simulation area."""

    effective_rainfall, effective_blockage_configs = resolve_dynamic_inputs(
        base_rainfall=rainfall,
        rainfall_variation=rainfall_variation,
        base_blockage_configs=blockage_configs,
        time_step=st.session_state.time_step,
        rainfall_speed=rainfall_speed,
        blockage_amplitude=blockage_amplitude,
        blockage_speed=blockage_speed,
    )

    if auto_run:
        simulate_one_step(
            rainfall=effective_rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=effective_blockage_configs,
        )

    display_rainfall = (
        effective_rainfall
        if auto_run or display_rainfall_override is None
        else display_rainfall_override
    )
    render_demo_strip(
        rainfall=display_rainfall,
        base_rainfall=rainfall,
        rainfall_variation=rainfall_variation,
        pipe_capacity=pipe_capacity,
        time_step=st.session_state.time_step,
    )

    states = st.session_state.drain_states
    render_summary_cards(states)

    st.subheader("2D Canvas 센서 메타포")
    payload = build_visual_payload(
        states,
        rainfall=effective_rainfall,
        time_step=st.session_state.time_step,
        elapsed_minutes=st.session_state.time_step * STEP_MINUTES,
    )
    st.html(render_canvas(payload, height=600), unsafe_allow_javascript=True)


def render_detail_panels() -> None:
    """Render current tables and history charts."""

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

    st.caption(
        "수위 센서값은 0~1 정규화라 1.0에 도달하면 상단에서 평평해질 수 있습니다. "
        "포화 이후에도 이어지는 변화는 역류·도로 유출·변화량 그래프에서 확인합니다."
    )
    dynamics_cols = st.columns(2)
    with dynamics_cols[0]:
        st.pyplot(
            draw_history_plot(
                history_df,
                "pipe_surcharge_to_surface",
                "관로 역류 노면 유입",
            )
        )
        st.pyplot(draw_history_plot(history_df, "surface_spill_out", "도로 유출 변화"))

    with dynamics_cols[1]:
        st.pyplot(draw_history_plot(history_df, "surface_water_delta", "도로 수위 변화량"))
        st.pyplot(draw_history_plot(history_df, "pipe_water_delta", "관로 수위 변화량"))

    st.subheader("최근 센서 기록")
    if history_df.empty:
        st.info("아직 기록이 없습니다. `1 step`을 눌러 기록을 시작하세요.")
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


def render_runtime_api_status_panel() -> None:
    """Render the current Streamlit-to-API shared runtime status."""

    saved_at = st.session_state.get("runtime_snapshot_saved_at")
    error = st.session_state.get("runtime_snapshot_error")
    if error:
        st.error(f"runtime snapshot 저장 실패: {error}")
        return

    if saved_at:
        st.success(f"최근 저장: {saved_at}")
    else:
        st.info("API 공유 전: 1 step 실행 필요")


def render_api_settings_panel() -> None:
    """Render Postman-friendly API endpoint settings."""

    st.subheader("API 설정")
    render_runtime_api_status_panel()

    control_cols = st.columns([0.34, 0.18, 0.18, 0.30])
    base_url = control_cols[0].text_input(
        "Base URL",
        value="http://127.0.0.1:8765",
        key="api_settings_base_url",
    )
    drain_label = control_cols[1].selectbox(
        "대상",
        options=["A", "B", "C"],
        index=1,
        key="api_settings_drain",
    )
    source = control_cols[2].selectbox(
        "소스",
        options=["runtime", "live", "snapshot"],
        index=0,
        key="api_settings_source",
    )
    profile_options = sorted(LIVE_PROFILES)
    profile = control_cols[3].selectbox(
        "live profile",
        options=profile_options,
        index=profile_options.index("storm_pulse"),
        format_func=lambda value: LIVE_PROFILE_LABELS.get(value, value),
        disabled=source != "live",
        key="api_settings_profile",
    )
    drain_id = f"DRAIN_{drain_label}"
    endpoint_url = build_latest_endpoint_url(
        base_url=base_url,
        drain_id=drain_id,
        source=source,
        profile=profile,
    )

    st.code(f"GET {endpoint_url}", language="http")
    if source == "runtime":
        st.caption("runtime은 Streamlit 화면이 마지막으로 저장한 센서 상태를 읽습니다.")
    elif source == "live":
        st.caption("live는 API가 stateless mock 최신값을 생성합니다.")
    else:
        st.caption("snapshot은 API가 기본 요청 조건으로 즉석 mock 값을 생성합니다.")

    render_live_latest_polling_panel()


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


def render_live_latest_result(
    *,
    drain_id: str,
    profile: str,
    seed: str,
    interval_sec: float,
    fixed_tick: bool,
    tick: int,
) -> None:
    """Render one live latest reading from the polling mock generator."""

    request: dict[str, str | float | int] = {
        "mode": "live",
        "profile": profile,
        "seed": seed,
        "interval_sec": interval_sec,
    }
    if fixed_tick:
        request["tick"] = tick

    payload = build_live_latest_payload(drain_id, request)
    live = payload["live"]
    latest = payload["latest"]
    tone = status_tone(str(latest["status"]))

    st.caption(
        f"{drain_id} · {LIVE_PROFILE_LABELS.get(profile, profile)} · "
        f"tick {live['tick']} · next poll {live['next_poll_after_ms']} ms"
    )
    metric_cols = st.columns(5)
    metric_cols[0].metric("도로 수위", f"{float(latest['surface_water_level']):.2f}")
    metric_cols[1].metric("유입량", f"{float(latest['inlet_flow']):.2f}")
    metric_cols[2].metric("관로 수위", f"{float(latest['pipe_water_level']):.2f}")
    metric_cols[3].metric("관로 유속", f"{float(latest['pipe_flow_speed']):.2f}")
    metric_cols[4].badge(str(latest["status"]), color=badge_color(str(latest["status"])))

    st.progress(
        progress_value(float(latest["surface_water_level"])),
        text=f"도로 물고임 · {latest['blockage_location']} · 상태 tone {tone}",
    )
    st.dataframe(pd.DataFrame([latest]), width="stretch", hide_index=True)

    with st.expander("Live latest JSON"):
        st.json(payload, expanded=1)


def render_live_latest_polling_panel() -> None:
    """Render a lightweight polling test panel for live latest mock values."""

    st.subheader("Live Latest Polling 테스트")
    st.caption(
        "별도 API 서버 호출 없이 같은 live latest mock 생성기를 사용합니다. "
        "외부 클라이언트는 같은 조건으로 latest endpoint를 2초 안팎마다 polling하면 됩니다."
    )

    control_cols = st.columns([0.20, 0.28, 0.18, 0.18, 0.16])
    drain_id = control_cols[0].selectbox(
        "대상 배수구",
        options=list(DRAIN_IDS),
        index=1,
        key="live_latest_drain_id",
    )
    profile_options = sorted(LIVE_PROFILES)
    profile = control_cols[1].selectbox(
        "live profile",
        options=profile_options,
        index=profile_options.index("storm_pulse"),
        format_func=lambda value: LIVE_PROFILE_LABELS.get(value, value),
        key="live_latest_profile",
    )
    interval_sec = control_cols[2].slider(
        "poll interval",
        0.5,
        10.0,
        2.0,
        0.5,
        key="live_latest_interval_sec",
    )
    seed = control_cols[3].text_input(
        "seed",
        value="demo",
        key="live_latest_seed",
    )
    auto_poll = control_cols[4].checkbox(
        "자동 polling",
        value=False,
        key="live_latest_auto_poll",
    )

    tick_cols = st.columns([0.24, 0.24, 0.52])
    fixed_tick = tick_cols[0].checkbox(
        "tick 고정",
        value=False,
        key="live_latest_fixed_tick",
    )
    tick = tick_cols[1].number_input(
        "tick",
        min_value=0,
        max_value=1_000_000,
        value=10,
        step=1,
        disabled=not fixed_tick,
        key="live_latest_tick",
    )
    path_drain = drain_id.replace("DRAIN_", "").lower()
    tick_query = f"&tick={int(tick)}" if fixed_tick else ""
    endpoint = (
        f"/api/v1/sensors/{path_drain}/latest?mode=live"
        f"&profile={profile}&interval_sec={interval_sec:g}&seed={seed}{tick_query}"
    )
    tick_cols[2].code(f'curl "http://127.0.0.1:8765{endpoint}"', language="bash")

    run_every = interval_sec if auto_poll and not fixed_tick else None
    if auto_poll and fixed_tick:
        st.info("tick 고정 상태에서는 값 재현 확인용으로 동작하므로 자동 polling을 멈춥니다.")

    if hasattr(st, "fragment"):
        fragment = st.fragment(run_every=run_every)(render_live_latest_result)
        fragment(
            drain_id=drain_id,
            profile=profile,
            seed=seed,
            interval_sec=interval_sec,
            fixed_tick=fixed_tick,
            tick=int(tick),
        )
        return

    if auto_poll and not fixed_tick:
        st.warning("현재 Streamlit 버전은 패널 단위 자동 polling을 지원하지 않습니다.")
    render_live_latest_result(
        drain_id=drain_id,
        profile=profile,
        seed=seed,
        interval_sec=interval_sec,
        fixed_tick=fixed_tick,
        tick=int(tick),
    )


def render_live_dashboard_fragment(
    *,
    rainfall: float,
    rainfall_variation: float,
    pipe_capacity: float,
    blockage_configs: dict[str, tuple[BlockageLocation, float]],
    rainfall_speed: float,
    blockage_amplitude: float,
    blockage_speed: float,
    display_rainfall_override: float | None,
    auto_run: bool,
    auto_interval_ms: int,
) -> None:
    """Render the live dashboard in a fragment to avoid full-page auto refresh flicker."""

    run_every = auto_interval_ms / 1000 if auto_run else None
    if hasattr(st, "fragment"):
        fragment = st.fragment(run_every=run_every)(render_live_dashboard)
        fragment(
            rainfall=rainfall,
            rainfall_variation=rainfall_variation,
            pipe_capacity=pipe_capacity,
            blockage_configs=blockage_configs,
            rainfall_speed=rainfall_speed,
            blockage_amplitude=blockage_amplitude,
            blockage_speed=blockage_speed,
            display_rainfall_override=display_rainfall_override,
            auto_run=auto_run,
        )
        return

    if auto_run:
        st.warning("현재 Streamlit 버전은 부드러운 자동 실행을 지원하지 않습니다.")
    render_live_dashboard(
        rainfall=rainfall,
        rainfall_variation=rainfall_variation,
        pipe_capacity=pipe_capacity,
        blockage_configs=blockage_configs,
        rainfall_speed=rainfall_speed,
        blockage_amplitude=blockage_amplitude,
        blockage_speed=blockage_speed,
        display_rainfall_override=display_rainfall_override,
        auto_run=False,
    )


def render_detail_panels_fragment(*, auto_run: bool, auto_interval_ms: int) -> None:
    """Refresh detail charts during auto-run without advancing simulation twice."""

    run_every = auto_interval_ms / 1000 if auto_run else None
    if hasattr(st, "fragment"):
        fragment = st.fragment(run_every=run_every)(render_detail_panels)
        fragment()
        return

    render_detail_panels()


def render_detail_tabs(
    *,
    rainfall: float,
    pipe_capacity: float,
    auto_run: bool,
    auto_interval_ms: int,
) -> None:
    """Render secondary demo panels in compact tabs."""

    graph_tab, data_tab, scenario_tab, api_tab = st.tabs(
        ["실시간 그래프", "센서 데이터", "시나리오", "API 설정"]
    )
    with graph_tab:
        render_detail_panels_fragment(auto_run=auto_run, auto_interval_ms=auto_interval_ms)
    with data_tab:
        render_mock_sensor_panel(rainfall=rainfall, pipe_capacity=pipe_capacity)
    with scenario_tab:
        render_timeseries_preview_panel()
    with api_tab:
        render_api_settings_panel()


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
    st.sidebar.caption("기준값과 변동량으로 데모 입력을 조절합니다.")

    st.sidebar.subheader("강우")
    rainfall = st.sidebar.slider("기준 강우량", 0.0, 1.0, 0.70, 0.01)
    rainfall_variation = st.sidebar.slider("강우 변동량", 0.0, 0.50, 0.20, 0.01)
    rainfall_speed = st.sidebar.slider("강우 변화 속도", 0.2, 4.0, 1.0, 0.1)
    rainfall_min, rainfall_max = rainfall_variation_bounds(rainfall, rainfall_variation)
    st.sidebar.caption(
        f"범위 {rainfall_min:.2f}~{rainfall_max:.2f} · 변동량 0이면 고정"
    )

    st.sidebar.subheader("파이프")
    pipe_capacity = st.sidebar.slider("파이프 용량", 0.2, 1.5, 1.00, 0.05)

    blockage_configs: dict[str, tuple[BlockageLocation, float]] = {}

    st.sidebar.divider()
    st.sidebar.subheader("막힘 설정")

    for drain_id in DRAIN_IDS:
        drain_label = drain_id[-1]
        location = st.sidebar.selectbox(
            f"{drain_label} 위치",
            options=["없음", "상부", "내부", "복합"],
            index=["없음", "상부", "내부", "복합"].index(DEFAULT_LOCATIONS[drain_id]),
            key=f"{drain_id}_location",
        )
        severity = st.sidebar.slider(
            f"{drain_label} 정도",
            0.0,
            1.0,
            DEFAULT_SEVERITIES[drain_id],
            0.01,
            key=f"{drain_id}_severity",
        )
        blockage_configs[drain_id] = (location, severity)  # type: ignore[assignment]

    st.sidebar.divider()
    st.sidebar.subheader("막힘 변동")
    blockage_amplitude = st.sidebar.slider("막힘 변동량", 0.0, 0.25, 0.05, 0.01)
    blockage_speed = st.sidebar.slider("막힘 변화 속도", 0.2, 4.0, 0.8, 0.1)
    st.sidebar.caption("변동량 0이면 기준 막힘 정도로 고정됩니다.")

    st.sidebar.divider()
    st.sidebar.subheader("진행")
    auto_interval_ms = st.sidebar.slider("진행 간격(ms)", 800, 5000, 1500, 100)
    progress_cols = st.sidebar.columns(2)
    start_clicked = progress_cols[0].button("시작", width="stretch")
    stop_clicked = progress_cols[1].button("정지", width="stretch")
    run_clicked = st.sidebar.button("1 step", width="stretch")
    reset_clicked = st.sidebar.button("히스토리 초기화", width="stretch")

    if start_clicked:
        st.session_state.auto_run_enabled = True
    if stop_clicked:
        st.session_state.auto_run_enabled = False
    auto_run = bool(st.session_state.auto_run_enabled)
    st.sidebar.caption(f"자동 진행: {'ON' if auto_run else 'OFF'}")

    applied_rainfall, applied_blockage_configs = resolve_dynamic_inputs(
        base_rainfall=rainfall,
        rainfall_variation=rainfall_variation,
        base_blockage_configs=blockage_configs,
        time_step=st.session_state.time_step,
        rainfall_speed=rainfall_speed,
        blockage_amplitude=blockage_amplitude,
        blockage_speed=blockage_speed,
    )
    st.sidebar.caption(
        f"적용값: 강우 {applied_rainfall:.2f} · {format_blockage_preview(applied_blockage_configs)}"
    )

    if reset_clicked:
        reset_simulation()
        st.rerun()

    if run_clicked:
        simulate_one_step(
            rainfall=applied_rainfall,
            pipe_capacity=pipe_capacity,
            blockage_configs=applied_blockage_configs,
        )

    st.title("배수구 가상 센서 시뮬레이터")
    st.caption(
        "상부 막힘, 내부 막힘, 복합 막힘에 따라 도로 위 물고임과 관로 수위·유속을 분리해 보여주는 MVP입니다."
    )
    render_live_dashboard_fragment(
        rainfall=rainfall,
        rainfall_variation=rainfall_variation,
        pipe_capacity=pipe_capacity,
        blockage_configs=blockage_configs,
        rainfall_speed=rainfall_speed,
        blockage_amplitude=blockage_amplitude,
        blockage_speed=blockage_speed,
        display_rainfall_override=applied_rainfall if run_clicked else None,
        auto_run=auto_run,
        auto_interval_ms=auto_interval_ms,
    )
    render_detail_tabs(
        rainfall=applied_rainfall,
        pipe_capacity=pipe_capacity,
        auto_run=auto_run,
        auto_interval_ms=auto_interval_ms,
    )

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
