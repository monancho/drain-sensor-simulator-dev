"""HTML Canvas renderer for dramatic 2D water-flow visualization."""

from __future__ import annotations

import html
import json


def render_canvas(payload: dict, *, height: int = 560) -> str:
    """Return a self-contained HTML Canvas animation."""

    data_json = json.dumps(payload, ensure_ascii=False)
    escaped_data = html.escape(data_json, quote=False).replace("`", "\\`")
    canvas_height = str(int(height))
    canvas_id = "drainCanvas-main"

    template = """
<div style="width:100%; border:1px solid #d8e0ea; border-radius:8px; overflow:hidden; background:#f7fbff; min-height:__CANVAS_HEIGHT__px;">
  <canvas id="__CANVAS_ID__" width="1040" height="__CANVAS_HEIGHT__" style="width:100%; height:__CANVAS_HEIGHT__px; display:block;"></canvas>
</div>
<script>
(() => {
const payload = JSON.parse(`__PAYLOAD_JSON__`);
const canvas = document.getElementById("__CANVAS_ID__");
if (!canvas) return;
const ctx = canvas.getContext("2d");
const W = canvas.width;
const H = canvas.height;
const animationKey = "__CANVAS_ID__";
window.__drainCanvasAnimations = window.__drainCanvasAnimations || {};
window.__drainCanvasFrames = window.__drainCanvasFrames || {};
if (window.__drainCanvasAnimations[animationKey]) {
  cancelAnimationFrame(window.__drainCanvasAnimations[animationKey]);
}
let frame = window.__drainCanvasFrames[animationKey] || 0;

const drains = payload.drains;
const outfall = payload.outfall;

const STATUS = {
  good: {line: "#039855", fill: "#dcfae6", text: "#027a48"},
  watch: {line: "#f79009", fill: "#fef0c7", text: "#b54708"},
  warning: {line: "#f04438", fill: "#fee4e2", text: "#b42318"},
  danger: {line: "#b42318", fill: "#fecdca", text: "#912018"}
};

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function drawRoundedRect(x, y, w, h, r, fill, stroke) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }
}

function palette(drain) {
  return STATUS[drain.status_tone || "good"] || STATUS.good;
}

function drawGauge(x, y, w, label, value, color) {
  const bounded = clamp01(value);
  ctx.fillStyle = "#667085";
  ctx.font = "11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(label, x, y);
  ctx.fillStyle = "#1d2939";
  ctx.textAlign = "right";
  ctx.fillText(bounded.toFixed(2), x + w, y);
  drawRoundedRect(x, y + 6, w, 5, 3, "#e4e7ec", null);
  drawRoundedRect(x, y + 6, Math.max(4, w * bounded), 5, 3, color, null);
}

function drawStatusPill(text, tone, x, y) {
  const selected = STATUS[tone || "good"] || STATUS.good;
  ctx.font = "bold 12px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const width = Math.max(72, ctx.measureText(text).width + 20);
  drawRoundedRect(x - width / 2, y - 14, width, 24, 8, selected.fill, selected.line);
  ctx.fillStyle = selected.text;
  ctx.textAlign = "center";
  ctx.fillText(text, x, y + 2);
}

function drawBackground() {
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, "#eef8ff");
  grad.addColorStop(0.55, "#f8fbff");
  grad.addColorStop(1, "#eef4f2");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = "#1d2939";
  ctx.font = "bold 20px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("2D 배수 네트워크 · 상부/내부 막힘 분리 시각화", 44, 42);

  ctx.font = "13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillStyle = "#667085";
  ctx.fillText(`rainfall ${payload.rainfall.toFixed(2)} · time step ${payload.timeStep} · elapsed ${payload.elapsedMinutes} min`, 44, 66);

  drawRoundedRect(42, 88, 250, 42, 8, "rgba(255,255,255,0.86)", "#d0d5dd");
  drawGauge(58, 112, 206, "강우량", payload.rainfall || 0, "#2e90fa");

  // road deck
  drawRoundedRect(58, 306, 924, 82, 8, "#e6e8ec", "#cbd5e1");
  ctx.fillStyle = "#c8d0da";
  for (let x = 88; x < 950; x += 82) {
    ctx.fillRect(x, 346, 42, 4);
  }
  ctx.fillStyle = "#667085";
  ctx.font = "bold 12px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("도로면", 72, 298);

  // underground zone
  drawRoundedRect(66, 405, 908, 118, 8, "#dcefeb", "#b9ccdb");
  ctx.fillStyle = "rgba(25, 76, 85, 0.08)";
  ctx.fillRect(66, 405, 908, 118);
  ctx.fillStyle = "#667085";
  ctx.fillText("관로 내부", 80, 398);
}

function drawRain() {
  const count = Math.max(0, payload.rainParticleCount || 0);
  if (count <= 0) return;
  ctx.strokeStyle = "rgba(24, 119, 242, 0.45)";
  ctx.lineWidth = 1.4;
  for (let i = 0; i < count; i++) {
    const x = (i * 79 + frame * (2.4 + payload.rainfall * 5.5)) % W;
    const y = (i * 37 + frame * (4.5 + payload.rainfall * 7.0)) % 292;
    const len = 8 + payload.rainfall * 12;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - 4, y + len);
    ctx.stroke();
  }
}

function drawPipe(from, to, index) {
  const flow = clamp01(from.pipe_flow_speed);
  const rate = clamp01(from.pipe_flow_rate);
  const segmentOutflow = clamp01(from.pipe_segment_outflow || from.pipe_flow_rate || 0);
  const thick = from.pipe_thickness || (5 + flow * 12);

  ctx.lineCap = "round";
  ctx.strokeStyle = "rgba(12, 74, 110, 0.18)";
  ctx.lineWidth = thick + 12;
  ctx.beginPath();
  ctx.moveTo(from.x, 430);
  ctx.lineTo(to.x, 430);
  ctx.stroke();

  ctx.strokeStyle = flow > 0.12 ? "rgba(13, 107, 179, 0.72)" : "rgba(102, 112, 133, 0.42)";
  ctx.lineWidth = thick;
  ctx.beginPath();
  ctx.moveTo(from.x, 430);
  ctx.lineTo(to.x, 430);
  ctx.stroke();

  const count = flow < 0.06 ? 1 : Math.max(3, from.particle_count || 3);
  ctx.globalAlpha = 0.24 + Math.max(rate, segmentOutflow) * 0.76;
  for (let i = 0; i < count; i++) {
    const speed = Math.max(0.18, from.particle_speed || 0.35);
    const t = ((frame * 0.006 * speed) + i / count + index * 0.17) % 1;
    const x = lerp(from.x + 12, to.x - 12, t);
    const y = 430 + Math.sin(frame * 0.05 + i) * 2;
    const size = 3.5 + rate * 5.5;
    ctx.beginPath();
    ctx.fillStyle = "rgba(64, 169, 255, 0.92)";
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // direction arrow
  const mid = (from.x + to.x) / 2;
  ctx.fillStyle = flow > 0.12 ? "rgba(13, 107, 179, 0.75)" : "rgba(102, 112, 133, 0.50)";
  ctx.beginPath();
  ctx.moveTo(mid + 24, 430);
  ctx.lineTo(mid + 8, 421);
  ctx.lineTo(mid + 8, 439);
  ctx.closePath();
  ctx.fill();

  if (segmentOutflow > 0.05) {
    ctx.fillStyle = "rgba(52, 64, 84, 0.78)";
    ctx.font = "11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`통과 ${segmentOutflow.toFixed(2)}`, mid, 458);
  }
}

function drawInternalBlockage(drain, to) {
  if (!drain.internal_blocked) return;
  const severity = clamp01(drain.internal_blockage);
  const x = lerp(drain.x, to.x, 0.34);
  const h = 18 + severity * 26;
  const color = severity > 0.7 ? "#b42318" : "#dc6803";

  ctx.strokeStyle = "rgba(14, 165, 233, 0.35)";
  ctx.lineWidth = 22;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(Math.max(drain.x + 28, x - 92), 430);
  ctx.lineTo(x - 18, 430);
  ctx.stroke();

  drawRoundedRect(x - 18, 430 - h / 2, 36, h, 5, color, "#7a271a");
  ctx.strokeStyle = "rgba(255,255,255,0.62)";
  ctx.lineWidth = 2;
  for (let i = -10; i <= 10; i += 10) {
    ctx.beginPath();
    ctx.moveTo(x + i, 430 - h / 2 + 4);
    ctx.lineTo(x + i - 8, 430 + h / 2 - 4);
    ctx.stroke();
  }
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 10px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("내부", x, 434);

  ctx.fillStyle = "#912018";
  ctx.font = "bold 11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("관로 정체", x, 404);
}

function drawSurfacePuddle(drain) {
  const radius = drain.puddle_radius || 0;
  if (radius <= 4) return;

  const x = drain.x;
  const y = 332;
  const grad = ctx.createRadialGradient(x, y, 8, x, y, Math.max(20, radius));
  grad.addColorStop(0, "rgba(56, 189, 248, 0.50)");
  grad.addColorStop(0.65, "rgba(125, 211, 252, 0.26)");
  grad.addColorStop(1, "rgba(186, 230, 253, 0.02)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.ellipse(x, y, radius * 1.45, radius * 0.38, 0, 0, Math.PI * 2);
  ctx.fill();

  if ((drain.overflow_intensity || 0) > 0.1) {
    ctx.strokeStyle = "rgba(220, 38, 38, 0.50)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(x, y, radius * 1.58, radius * 0.48, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawSurfaceBlockage(drain) {
  if (!drain.surface_blocked) return;
  const x = drain.x;
  const severity = clamp01(drain.surface_blockage);

  drawRoundedRect(x - 58, 247, 116, 26, 7, "rgba(255, 250, 235, 0.97)", "#dc6803");
  ctx.fillStyle = "#b54708";
  ctx.font = "bold 11px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(`상부 유입 차단 ${severity.toFixed(2)}`, x, 264);

  ctx.strokeStyle = "rgba(180, 35, 24, 0.72)";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x - 28, 238);
  ctx.lineTo(x + 28, 238);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x - 12, 232);
  ctx.lineTo(x + 12, 244);
  ctx.moveTo(x + 12, 232);
  ctx.lineTo(x - 12, 244);
  ctx.stroke();

  for (let i = 0; i < 7; i++) {
    const dx = -42 + i * 14;
    const color = i % 2 === 0 ? "#854d0e" : "#475467";
    drawRoundedRect(x + dx, 272 + (i % 3) * 3, 12, 8, 2, color, null);
  }
}

function drawPassthroughAtDrain(drain) {
  if (!drain.passthrough_visible) return;
  const x = drain.x;
  const upstream = clamp01(drain.upstream_pipe_flow);

  ctx.save();
  ctx.setLineDash([9, 6]);
  ctx.strokeStyle = "rgba(21, 112, 239, 0.88)";
  ctx.lineWidth = 4 + upstream * 8;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x - 70, 430);
  ctx.lineTo(x + 70, 430);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "rgba(21, 112, 239, 0.90)";
  ctx.beginPath();
  ctx.moveTo(x + 78, 430);
  ctx.lineTo(x + 62, 421);
  ctx.lineTo(x + 62, 439);
  ctx.closePath();
  ctx.fill();

  drawRoundedRect(x - 54, 444, 108, 20, 6, "rgba(219, 234, 254, 0.96)", "#2e90fa");
  ctx.fillStyle = "#175cd3";
  ctx.font = "bold 10px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(`하부 통과 ${upstream.toFixed(2)}`, x, 458);
  ctx.restore();
}

function drawDrain(drain) {
  const x = drain.x;
  const y = drain.y;

  drawSurfacePuddle(drain);

  // inlet shaft
  drawRoundedRect(x - 38, y + 26, 76, 116, 8, "#344054", "#1d2939");

  // inner water fill
  const fillH = 104 * Math.min(1, drain.pipe_water_level || 0);
  const waveOffset = Math.sin(frame * 0.07 + x * 0.01) * 3;
  ctx.fillStyle = "rgba(14, 165, 233, 0.80)";
  drawRoundedRect(x - 32, y + 134 - fillH + waveOffset, 64, fillH, 8, "rgba(14, 165, 233, 0.80)", null);

  // grate
  drawRoundedRect(x - 50, y - 8, 100, 38, 8, "#475467", "#101828");
  ctx.strokeStyle = "#98a2b3";
  ctx.lineWidth = 3;
  for (let i = -34; i <= 34; i += 17) {
    ctx.beginPath();
    ctx.moveTo(x + i, y - 3);
    ctx.lineTo(x + i, y + 25);
    ctx.stroke();
  }
  drawSurfaceBlockage(drain);
  drawPassthroughAtDrain(drain);

  // water entering from surface to pipe
  const inletFlow = clamp01(drain.inlet_flow);
  const dropCount = Math.floor(2 + inletFlow * 80);
  ctx.fillStyle = "rgba(59, 130, 246, 0.85)";
  for (let i = 0; i < dropCount; i++) {
    const dx = ((i * 17 + frame * 1.8) % 74) - 37;
    const dy = ((i * 29 + frame * 2.3) % 74);
    ctx.beginPath();
    ctx.arc(x + dx, y + 34 + dy, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }

  // debris
  const debrisCount = drain.debris_count || 0;
  for (let i = 0; i < debrisCount; i++) {
    const dx = ((i * 23) % 78) - 39;
    const dy = ((i * 19) % 34) - 11;
    ctx.fillStyle = i % 2 === 0 ? "#854d0e" : "#667085";
    drawRoundedRect(x + dx, y + dy, 10 + (i % 3) * 3, 7 + (i % 2) * 3, 2, ctx.fillStyle, null);
  }

  // status label
  const selected = palette(drain);
  ctx.fillStyle = selected.text;
  ctx.font = "bold 13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(drain.id, x, drain.surface_blocked ? y - 50 : y - 28);

  // stagnation pulse
  if ((drain.stagnation_intensity || 0) > 0.12) {
    const pulse = 8 + Math.sin(frame * 0.08) * 5;
    ctx.strokeStyle = "rgba(220, 38, 38, 0.55)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(x, y + 18, 70 + pulse, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawDrainPanel(drain) {
  const x = drain.x - 106;
  const y = 512;
  const selected = palette(drain);
  drawRoundedRect(x, y, 212, 72, 8, "rgba(255,255,255,0.92)", selected.line);
  ctx.fillStyle = "#1d2939";
  ctx.textAlign = "left";
  ctx.font = "bold 12px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(drain.id, x + 12, y + 21);
  drawStatusPill(drain.sensor_status || "정상 배수", drain.status_tone, x + 142, y + 19);
  drawGauge(x + 12, y + 42, 84, "도로", drain.surface_water_level, "#2e90fa");
  drawGauge(x + 116, y + 42, 84, "유입", drain.inlet_flow, "#12b76a");
  drawGauge(x + 12, y + 63, 84, "관로", drain.pipe_water_level, "#0e9384");
  drawGauge(x + 116, y + 63, 84, "유속", drain.pipe_flow_speed, "#7a5af8");
}

function drawOutfall() {
  const x = outfall.x;
  drawRoundedRect(x - 42, 390, 84, 80, 8, "#667085", "#344054");
  ctx.fillStyle = "#e0f2fe";
  ctx.beginPath();
  ctx.arc(x, 430, 24, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#344054";
  ctx.textAlign = "center";
  ctx.font = "bold 13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("OUTFALL", x, 365);
}

function drawLegend() {
  drawRoundedRect(752, 28, 252, 154, 8, "rgba(255,255,255,0.90)", "#d0d5dd");
  ctx.textAlign = "left";
  ctx.fillStyle = "#344054";
  ctx.font = "bold 13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("표현 기준", 770, 54);
  ctx.font = "12px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

  ctx.fillStyle = "rgba(56, 189, 248, 0.55)";
  ctx.beginPath();
  ctx.ellipse(778, 76, 16, 6, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#344054";
  ctx.fillText("도로 물웅덩이 = surface water", 802, 80);

  drawRoundedRect(766, 92, 24, 12, 4, "#fef0c7", "#dc6803");
  ctx.fillStyle = "#344054";
  ctx.fillText("상부 막힘 = 유입구 위 차단", 802, 103);

  drawRoundedRect(766, 116, 24, 14, 4, "#b42318", "#7a271a");
  ctx.fillStyle = "#344054";
  ctx.fillText("내부 막힘 = 관로 속 정체", 802, 128);

  ctx.strokeStyle = "rgba(21, 112, 239, 0.88)";
  ctx.lineWidth = 4;
  ctx.setLineDash([8, 5]);
  ctx.beginPath();
  ctx.moveTo(766, 148);
  ctx.lineTo(790, 148);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#344054";
  ctx.fillText("하부 통과 = upstream pipe flow", 802, 152);

  ctx.fillStyle = "rgba(64, 169, 255, 0.92)";
  ctx.beginPath();
  ctx.arc(778, 168, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#344054";
  ctx.fillText("입자 속도/밀도 = flow speed/rate", 802, 172);
}

function animate() {
  if (!canvas.isConnected) return;
  frame += 1;
  ctx.clearRect(0, 0, W, H);
  drawBackground();
  drawRain();

  for (let i = 0; i < drains.length; i++) {
    const from = drains[i];
    const to = i < drains.length - 1 ? drains[i + 1] : outfall;
    drawPipe(from, to, i);
  }

  for (let i = 0; i < drains.length; i++) {
    const to = i < drains.length - 1 ? drains[i + 1] : outfall;
    drawInternalBlockage(drains[i], to);
  }

  for (const drain of drains) {
    drawDrain(drain);
  }

  drawOutfall();
  for (const drain of drains) {
    drawDrainPanel(drain);
  }
  drawLegend();

  window.__drainCanvasFrames[animationKey] = frame;
  window.__drainCanvasAnimations[animationKey] = requestAnimationFrame(animate);
}

animate();
})();
</script>
"""
    return template.replace("__PAYLOAD_JSON__", escaped_data).replace(
        "__CANVAS_HEIGHT__", canvas_height
    ).replace("__CANVAS_ID__", canvas_id)


def render_canvas_fallback_message() -> str:
    """Fallback HTML if rendering data is unavailable."""

    return """
<div style="padding:24px;border:1px solid #ddd;border-radius:12px;">
  Canvas 시각화 데이터를 불러오지 못했습니다.
</div>
"""
