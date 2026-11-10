import asyncio
import io
import os
import wave
import pytest

from sight_core.speech_tts import LocalTTS, TTSInputError, TTSUnavailable, TTSBusy


def test_tts_disabled():
    tts = LocalTTS(enabled=False)
    status = asyncio.run(tts.status())
    assert not status["available"]
    assert not status["enabled"]

    with pytest.raises(TTSUnavailable, match="Local TTS is disabled"):
        asyncio.run(tts.synthesize("Hello"))

    with pytest.raises(TTSUnavailable):
        asyncio.run(tts.list_voices())


def test_tts_input_validation():
    tts = LocalTTS(enabled=True)
    with pytest.raises(TTSInputError, match="Text must be a non-empty string"):
        asyncio.run(tts.synthesize(""))

    with pytest.raises(TTSInputError, match="Text must be a non-empty string"):
        asyncio.run(tts.synthesize("   \n\t  "))

    with pytest.raises(TTSInputError, match="maximum supported length"):
        asyncio.run(tts.synthesize("a" * 4001))

    with pytest.raises(TTSInputError, match="control characters"):
        asyncio.run(tts.synthesize("Hello\x00World"))


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows OS with PowerShell")
def test_tts_windows_status_and_voices():
    tts = LocalTTS(enabled=True)
    status = asyncio.run(tts.status())
    assert status["available"] is True
    assert status["enabled"] is True
    assert len(status["voices"]) > 0
    assert status["default_voice"] is not None

    voices = asyncio.run(tts.list_voices())
    assert len(voices) > 0
    names = [v["name"] for v in voices]
    assert any("David" in n or "Zira" in n or "Mark" in n for n in names)


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows OS with PowerShell")
def test_tts_windows_synthesis_wav():
    tts = LocalTTS(enabled=True)
    text = "BEL voice synthesis is operational."
    wav_bytes = asyncio.run(tts.synthesize(text, rate=1.0))
    assert isinstance(wav_bytes, bytes)
    assert len(wav_bytes) > 1000
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"

    with wave.open(io.BytesIO(wav_bytes), "rb") as audio:
        assert audio.getnchannels() in (1, 2)
        assert audio.getsampwidth() == 2
        assert audio.getframerate() >= 16000
        frames = audio.getnframes()
        duration = frames / audio.getframerate()
        assert 0.5 < duration < 10.0

