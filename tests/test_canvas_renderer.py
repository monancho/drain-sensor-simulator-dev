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
                    "surface_blockage": 0.0,
                    "internal_blockage": 0.8,
                    "surface_water_level": 0.1,
                    "inlet_flow": 0.05,
                    "upstream_pipe_flow": 0.0,
                    "downstream_backwater": 0.0,
                    "pipe_segment_outflow": 0.1,
                    "pipe_surcharge_to_surface": 0.0,
                    "pipe_water_level": 0.2,
                    "pipe_flow_speed": 0.5,
                    "pipe_flow_rate": 0.5,
                    "sensor_status": "정상 배수",
                    "internal_blocked": True,
                }
            ],
            "outfall": {"id": "OUTFALL", "x": 885, "y": 270},
        }
    )

    assert "drainCanvas" in html
    assert "min-width:960px" in html
    assert "DRAIN_A" in html
    assert "센서값 기반 흐름" in html
    assert "관로 제한" in html
