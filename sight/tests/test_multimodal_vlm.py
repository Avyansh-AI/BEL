"""Unit tests for Stage 8 Multimodal VLM Subsystem."""
from __future__ import annotations

import asyncio
import io
import pytest
from PIL import Image

from sight_core.multimodal_vlm import MultimodalVLM


def make_test_image(width=200, height=150, color=(100, 150, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vlm_image_properties():
    vlm = MultimodalVLM()
    img_bytes = make_test_image(300, 200, color=(20, 20, 30))
    props = vlm.inspect_image_properties(img_bytes)

    assert props["width"] == 300
    assert props["height"] == 200
    assert props["format"] == "PNG"
    assert props["is_dark_mode"] is True
    assert props["mean_luminance"] < 50.0


def test_vlm_query_fallback():
    vlm = MultimodalVLM(ollama_url="http://127.0.0.1:99999")  # unreachable URL
    img_bytes = make_test_image(200, 200)

    res = asyncio.run(vlm.query_image(img_bytes, prompt="What is in this image?"))
    assert res.status == "fallback"
    assert res.visual_metadata["width"] == 200
    assert "Prompt: 'What is in this image?'" in res.text


def test_vlm_analyze_chart():
    vlm = MultimodalVLM()
    img_bytes = make_test_image(400, 300)

    chart = asyncio.run(vlm.analyze_chart(img_bytes))
    assert chart.chart_type in ("bar", "line", "pie", "scatter")
    assert len(chart.data_points) >= 1
    assert chart.summary != ""


def test_vlm_analyze_wireframe():
    vlm = MultimodalVLM()
    img_bytes = make_test_image(800, 600, color=(240, 240, 240))

    wireframe = asyncio.run(vlm.analyze_wireframe(img_bytes))
    assert len(wireframe.elements) >= 2
    button_found = any(e.element_type == "button" for e in wireframe.elements)
    assert button_found is True
