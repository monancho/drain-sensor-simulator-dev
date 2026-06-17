"""Static chart helpers for Streamlit."""

from __future__ import annotations

from typing import Literal

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

MetricName = Literal[
    "surface_water_level",
    "pipe_water_level",
    "pipe_flow_speed",
    "inlet_flow",
    "pipe_flow_rate",
    "stagnation_score",
    "pipe_surcharge_to_surface",
    "surface_spill_out",
    "surface_water_delta",
    "pipe_water_delta",
]

KOREAN_FONT_CANDIDATES = (
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "NanumGothic",
    "Malgun Gothic",
    "AppleGothic",
)
TITLE_FALLBACKS = {
    "도로 위 물고임 변화": "Surface water level",
    "관로 수위 변화": "Pipe water level",
    "관로 유속 변화": "Pipe flow speed",
    "배수구 유입량 변화": "Inlet flow",
    "관로 역류 노면 유입": "Pipe surcharge to surface",
    "도로 유출 변화": "Surface spill out",
    "도로 수위 변화량": "Surface water delta",
    "관로 수위 변화량": "Pipe water delta",
}
EMPTY_MESSAGE = "No records yet."
DRAIN_COLORS = {
    "DRAIN_A": "#175cd3",
    "DRAIN_B": "#027a48",
    "DRAIN_C": "#b42318",
}


def find_korean_plot_font() -> str | None:
    """Return a Korean-capable Matplotlib font name when one is installed."""

    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in KOREAN_FONT_CANDIDATES:
        if font_name in available_fonts:
            return font_name
    return None


KOREAN_PLOT_FONT = find_korean_plot_font()
if KOREAN_PLOT_FONT:
    plt.rcParams["font.family"] = KOREAN_PLOT_FONT
    plt.rcParams["axes.unicode_minus"] = False


def plot_title(title: str) -> str:
    """Use Korean chart titles only when a Korean-capable font is available."""

    if KOREAN_PLOT_FONT:
        return title
    return TITLE_FALLBACKS.get(title, title)


def build_current_table(states: dict[str, dict[str, float | str]]) -> pd.DataFrame:
    """Build a readable current-state table."""

    rows = []

    for drain_id in ["DRAIN_A", "DRAIN_B", "DRAIN_C"]:
        state = states[drain_id]
        rows.append(
            {
                "배수구": drain_id,
                "막힘 위치": state.get("blockage_location"),
                "막힘 정도": round(float(state.get("blockage_severity", 0.0)), 2),
                "도로 수위": round(float(state.get("surface_water_level", 0.0)), 3),
                "유입량": round(float(state.get("inlet_flow", 0.0)), 3),
                "노면 자연 감소": round(float(state.get("surface_recession", 0.0)), 3),
                "도로 유입": round(float(state.get("surface_spill_in", 0.0)), 3),
                "도로 유출": round(float(state.get("surface_spill_out", 0.0)), 3),
                "관로 역류 노면 유입": round(
                    float(state.get("pipe_surcharge_to_surface", 0.0)),
                    3,
                ),
                "상류 관로 유입": round(float(state.get("upstream_pipe_flow", 0.0)), 3),
                "하류 역류 영향": round(float(state.get("downstream_backwater", 0.0)), 3),
                "관로 통과 유량": round(float(state.get("pipe_segment_outflow", 0.0)), 3),
                "관로 수위": round(float(state.get("pipe_water_level", 0.0)), 3),
                "관로 유속": round(float(state.get("pipe_flow_speed", 0.0)), 3),
                "관로 유량": round(float(state.get("pipe_flow_rate", 0.0)), 3),
                "상태": state.get("sensor_status"),
            }
        )

    return pd.DataFrame(rows)


def draw_history_plot(history_df: pd.DataFrame, metric: MetricName, title: str):
    """Draw a simple time-series chart for each drain."""

    fig, ax = plt.subplots(figsize=(10, 3.2))

    if history_df.empty or metric not in history_df.columns:
        ax.set_title(plot_title(title))
        ax.text(0.5, 0.5, EMPTY_MESSAGE, ha="center", va="center")
        ax.axis("off")
        return fig

    for drain_id, group in history_df.groupby("drain_id"):
        group = group.sort_values("time_step")
        y_values = pd.to_numeric(group[metric], errors="coerce")
        ax.plot(
            group["elapsed_minutes"],
            y_values,
            color=DRAIN_COLORS.get(str(drain_id), "#175cd3"),
            linewidth=2.2,
            marker="o",
            markersize=4.5,
            label=drain_id,
        )

    ax.set_title(plot_title(title))
    ax.set_xlabel("elapsed minutes")
    ax.set_ylabel(metric)
    ax.set_ylim(-0.05, 1.05)
    ax.set_facecolor("#f8fafc")
    ax.grid(True, color="#d0d5dd", alpha=0.55, linewidth=0.8)
    ax.legend(loc="best", frameon=False)
    for spine in ax.spines.values():
        spine.set_color("#d0d5dd")
    fig.tight_layout()
    return fig


def build_visual_payload(
    states: dict[str, dict[str, float | str]],
    *,
    rainfall: float,
    time_step: int,
    elapsed_minutes: float,
) -> dict:
    """Prepare state data for the Canvas renderer."""

    drains = []
    x_positions = {"DRAIN_A": 150, "DRAIN_B": 400, "DRAIN_C": 650}

    for drain_id in ["DRAIN_A", "DRAIN_B", "DRAIN_C"]:
        state = states[drain_id]
        pipe_flow_speed = float(state.get("pipe_flow_speed", 0.0))
        pipe_flow_rate = float(state.get("pipe_flow_rate", 0.0))
        upstream_pipe_flow = float(state.get("upstream_pipe_flow", 0.0))
        pipe_segment_outflow = float(state.get("pipe_segment_outflow", 0.0))
        downstream_backwater = float(state.get("downstream_backwater", 0.0))
        pipe_surcharge_to_surface = float(state.get("pipe_surcharge_to_surface", 0.0))
        surface_spill_in = float(state.get("surface_spill_in", 0.0))
        surface_spill_out = float(state.get("surface_spill_out", 0.0))
        surface_water_level = float(state.get("surface_water_level", 0.0))
        pipe_water_level = float(state.get("pipe_water_level", 0.0))
        surface_blockage = float(state.get("surface_blockage", 0.0))
        internal_blockage = float(state.get("internal_blockage", 0.0))
        stagnation_score = float(state.get("stagnation_score", 0.0))
        blockage_severity = float(state.get("blockage_severity", 0.0))
        sensor_status = str(state.get("sensor_status", "정상 배수"))

        drains.append(
            {
                "id": drain_id,
                "x": x_positions[drain_id],
                "y": 270,
                "blockage_location": state.get("blockage_location", "없음"),
                "blockage_severity": blockage_severity,
                "surface_blockage": surface_blockage,
                "internal_blockage": internal_blockage,
                "surface_water_level": surface_water_level,
                "inlet_flow": float(state.get("inlet_flow", 0.0)),
                "upstream_pipe_flow": upstream_pipe_flow,
                "downstream_backwater": downstream_backwater,
                "surface_spill_in": surface_spill_in,
                "surface_spill_out": surface_spill_out,
                "pipe_segment_outflow": pipe_segment_outflow,
                "pipe_surcharge_to_surface": pipe_surcharge_to_surface,
                "pipe_water_level": pipe_water_level,
                "pipe_flow_speed": pipe_flow_speed,
                "pipe_flow_rate": pipe_flow_rate,
                "stagnation_score": stagnation_score,
                "sensor_status": sensor_status,
                "status_tone": resolve_status_tone(sensor_status),
                "puddle_radius": max(0.0, surface_water_level - 0.28) * 180 + surface_blockage * 26,
                "pipe_thickness": 5 + pipe_flow_speed * 12,
                "particle_speed": 0.35 + pipe_flow_speed * 2.8,
                "particle_count": int(3 + pipe_flow_rate * 18),
                "surface_blockage_intensity": surface_blockage,
                "internal_blockage_intensity": internal_blockage,
                "blockage_intensity": blockage_severity,
                "stagnation_intensity": min(1.0, max(0.0, stagnation_score) * 3.2),
                "overflow_intensity": min(1.0, max(0.0, surface_water_level - 0.80) / 0.20),
                "surface_blocked": surface_blockage >= 0.25,
                "internal_blocked": internal_blockage >= 0.25,
                "passthrough_visible": (
                    surface_blockage >= 0.25
                    and internal_blockage < 0.25
                    and upstream_pipe_flow > 0.02
                ),
            }
        )

    return {
        "rainfall": float(rainfall),
        "rainParticleCount": int(float(rainfall) * 110),
        "timeStep": int(time_step),
        "elapsedMinutes": float(elapsed_minutes),
        "drains": drains,
        "outfall": {"id": "OUTFALL", "x": 885, "y": 270},
    }


def resolve_status_tone(status: str) -> str:
    """Return a visual tone for a sensor status string."""

    if "복합" in status:
        return "danger"
    if "상부" in status or "내부" in status or "병목" in status:
        return "warning"
    if "물고임" in status or "흐름" in status:
        return "watch"
    return "good"
