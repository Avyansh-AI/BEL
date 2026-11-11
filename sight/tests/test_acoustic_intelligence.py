"""Unit tests for Stage 8 Acoustic Intelligence Subsystem."""
from __future__ import annotations

import math
import struct
import pytest

from sight_core.acoustic_intelligence import AcousticIntelligence


def generate_sine_wave(freq_hz: float, duration_sec: float, sample_rate: int = 16000, amp: float = 8000.0) -> bytes:
    num_samples = int(sample_rate * duration_sec)
    buf = bytearray()
    for i in range(num_samples):
        t = i / sample_rate
        val = int(amp * math.sin(2 * math.pi * freq_hz * t))
        buf.extend(struct.pack("<h", val))
    return bytes(buf)


def test_acoustic_silence():
    ai = AcousticIntelligence()
    # Near-zero noise
    silent_pcm = b"\x00\x00" * 8000  # 0.5s of silence
    res = ai.classify_scene(silent_pcm)

    assert res.scene_type == "silence"
    assert res.features.rms_energy < 50.0


def test_acoustic_alarm():
    ai = AcousticIntelligence()
    # High frequency 4000 Hz tone with loud amplitude
    alarm_pcm = generate_sine_wave(freq_hz=4000.0, duration_sec=0.5, amp=12000.0)
    res = ai.classify_scene(alarm_pcm)

    assert res.scene_type == "alarm"
    assert res.features.spectral_centroid_hz > 3000.0


def test_acoustic_speech_features():
    ai = AcousticIntelligence()
    # Simulated speech: modulated alternating frequencies with silence gaps
    buf = bytearray()
    for f in [200, 400, 300, 600, 0]:
        if f == 0:
            buf.extend(b"\x00\x00" * 800)
        else:
            buf.extend(generate_sine_wave(freq_hz=f, duration_sec=0.1, amp=4000.0))
    res = ai.classify_scene(bytes(buf))

    assert res.scene_type in ("speech", "ambient_noise")
    assert res.features.zero_crossing_rate > 0.0


def test_meeting_summarizer():
    ai = AcousticIntelligence()
    transcript = """
    Alice: Welcome everyone. Agenda: Finalizing Stage 8 Multimodal Architecture.
    Bob: We discussed the PDF parser and acoustic scene classifier.
    Alice: We agreed to proceed with pure-Python fallbacks for offline resilience.
    Bob will implement the acoustic classifier.
    Action: deploy the updated FastAPI endpoints by tomorrow morning.
    """
    summary = ai.summarize_meeting(transcript)

    assert len(summary.topics) >= 1
    assert "Stage 8 Multimodal Architecture" in summary.topics[0]
    assert len(summary.decisions) >= 1
    assert len(summary.action_items) >= 2
    bob_action = [a for a in summary.action_items if a.owner == "Bob"]
    assert len(bob_action) == 1
    assert "acoustic" in bob_action[0].task.lower()
