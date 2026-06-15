from canvas_renderer import render_canvas


def test_canvas_renderer_contains_canvas_and_korean_text():
    html = render_canvas(
        {
            "rainfall": 0.7,
            "rainParticleCount": 20,
            "timeStep": 1,
            "elapsedMinutes": 1,
            "drains": [
                {
                    "id": "DRAIN_A",
                    "x": 150,
                    "y": 270,
                    "blockage_severity": 0.0,
                    "surface_water_level": 0.1,
                    "inlet_flow": 0.05,
                    "pipe_water_level": 0.2,
                    "pipe_flow_speed": 0.5,
                    "pipe_flow_rate": 0.5,
                    "sensor_status": "정상 배수",
                }
            ],
            "outfall": {"id": "OUTFALL", "x": 885, "y": 270},
        }
    )

    assert "drainCanvas" in html
    assert "DRAIN_A" in html
    assert "상부/내부 막힘" in html
