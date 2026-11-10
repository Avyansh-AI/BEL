import struct
import pytest

from sight_core.wake_detector import (
    AcousticWakeDetector,
    WakeState,
    SAMPLE_RATE,
    BYTES_PER_SAMPLE,
)


def make_sine_pcm(duration_sec: float = 0.1, freq: float = 440.0, amplitude: int = 10000) -> bytes:
    """Generates synthetic 16 kHz 16-bit mono PCM."""
    import math
    num_samples = int(SAMPLE_RATE * duration_sec)
    samples = []
    for i in range(num_samples):
        val = int(amplitude * math.sin(2 * math.pi * freq * (i / SAMPLE_RATE)))
        samples.append(val)
    return struct.pack(f"<{len(samples)}h", *samples)


def test_wake_detector_initial_state():
    detector = AcousticWakeDetector(wake_phrase="bel")
    assert detector.state == WakeState.IDLE
    status = detector.status()
    assert status["state"] == "idle"
    assert status["wake_phrase"] == "bel"
    assert status["buffered_bytes"] == 0


def test_silence_handling():
    detector = AcousticWakeDetector(wake_phrase="bel")
    silence = b"\x00" * 3200  # 100ms silence
    res = detector.process_chunk(silence)
    assert not res.triggered
    assert not res.speech_detected
    assert res.energy_rms < 0.001
    assert detector.state == WakeState.IDLE


def test_speech_detection_and_vad():
    detector = AcousticWakeDetector(wake_phrase="bel", energy_threshold=0.01)
    tone = make_sine_pcm(duration_sec=0.1, freq=300.0, amplitude=8000)
    res = detector.process_chunk(tone)
    assert res.energy_rms > 0.05
    assert res.speech_detected is True
    assert detector.state == WakeState.LISTENING


def test_wake_trigger_simulation():
    detector = AcousticWakeDetector(wake_phrase="bel", cooldown_duration=0.5)
    tone = make_sine_pcm(duration_sec=0.2, freq=400.0, amplitude=15000)
    res = detector.process_chunk(tone, simulate_trigger=True)
    assert res.triggered is True
    assert res.confidence > 0.5
    assert detector.state == WakeState.COOLDOWN
    # In cooldown, subsequent chunks do not re-trigger
    next_res = detector.process_chunk(tone)
    assert not next_res.triggered


def test_detector_reset():
    detector = AcousticWakeDetector(wake_phrase="bel")
    tone = make_sine_pcm(duration_sec=0.2, freq=400.0, amplitude=10000)
    detector.process_chunk(tone)
    assert detector.status()["buffered_bytes"] > 0
    detector.reset()
    assert detector.status()["buffered_bytes"] == 0
    assert detector.state == WakeState.IDLE
