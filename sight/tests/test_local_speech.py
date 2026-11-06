import asyncio
import io
import json
import os
import subprocess
import sys
import threading
import time
import wave

import pytest

from sight_core.local_speech import LocalSpeech, SpeechInputError, SpeechUnavailable, SpeechBusy, validate_audio
from sight_core import local_speech


def recording(frames=3200, channels=1, rate=16000, width=2, silent=False):
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setparams((channels, width, rate, frames, 'NONE', 'not compressed'))
        writer.writeframes((b'\x00' if silent else b'\x40') * frames * channels * width)
    return output.getvalue()


@pytest.mark.parametrize('raw', [b'RIFFbad', recording(frames=320001), recording(frames=1599),
                                recording(channels=2), recording(rate=44100), recording(width=1),
                                recording()[:-2], recording() + b'trailer', recording(silent=True)],
                         ids=['bad-header', 'too-long', 'too-short', 'stereo', 'wrong-rate',
                              'wrong-width', 'truncated', 'trailer', 'silence'])
def test_invalid_or_unbounded_audio_never_launches_worker(raw, monkeypatch):
    monkeypatch.setattr(local_speech, 'run_worker', lambda *args: pytest.fail('Invalid audio reached worker'))
    with pytest.raises(SpeechInputError):
        asyncio.run(LocalSpeech(True).transcribe(raw))


def test_valid_audio_and_default_off_never_start_a_process(monkeypatch):
    validate_audio(recording())
    monkeypatch.setattr(local_speech, 'run_worker', lambda *args: pytest.fail('Disabled feature reached worker'))
    service = LocalSpeech()
    assert asyncio.run(service.status())['available'] is False
    with pytest.raises(SpeechUnavailable):
        asyncio.run(service.transcribe(recording()))


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1, 1.1, True, '0.9'])
def test_worker_confidence_is_finite_numeric_and_bounded(monkeypatch, bad):
    monkeypatch.setattr(local_speech, 'run_worker', lambda *args: {'ok': True, 'text': 'draft', 'confidence': bad, 'locale': 'en-US'})
    with pytest.raises(SpeechUnavailable):
        asyncio.run(LocalSpeech(True).transcribe(recording()))


def test_low_confidence_is_editable_data_and_never_a_tool_call(monkeypatch):
    monkeypatch.setattr(local_speech, 'run_worker', lambda *args: {'ok': True, 'text': 'open notepad', 'confidence': .2, 'locale': 'en-US'})
    result = asyncio.run(LocalSpeech(True).transcribe(recording()))
    assert result == {'text': 'open notepad', 'confidence': .2, 'locale': 'en-US',
                      'engine': 'Windows System.Speech', 'review_required': True}


def test_language_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(local_speech, 'run_worker', lambda *args: {'ok': True, 'text': 'draft', 'confidence': .8, 'locale': 'en-US'})
    with pytest.raises(SpeechUnavailable):
        asyncio.run(LocalSpeech(True).transcribe(recording(), 'hi-IN'))


def test_repeated_cancellation_drains_worker_before_allowing_another(monkeypatch):
    began, release, finished = threading.Event(), threading.Event(), threading.Event()
    def worker(request, cancel, timeout):
        began.set()
        while not cancel.is_set():
            time.sleep(.005)
        release.wait(3)
        finished.set()
        raise SpeechUnavailable('cancelled')
    monkeypatch.setattr(local_speech, 'run_worker', worker)
    async def scenario():
        speech = LocalSpeech(True)
        task = asyncio.create_task(speech.transcribe(recording()))
        while not began.is_set():
            await asyncio.sleep(.005)
        task.cancel()
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(SpeechBusy):
            await speech.transcribe(recording())
        assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and not speech._busy.locked()
    asyncio.run(scenario())


def test_expired_worker_is_killed_and_drained(monkeypatch):
    class Process:
        killed = False
        drained = False
        terminated = threading.Event()
        def __init__(self, *args, **kwargs):
            assert args[0][1:4] == ['-NoLogo', '-NoProfile', '-NonInteractive']
            assert kwargs['creationflags'] == 0x08000000
        def communicate(self, input=None, timeout=None):
            assert self.terminated.wait(3), 'Worker was not terminated'
            self.drained = True
            return b'', b''
        def poll(self):
            return 1 if self.killed else None
        def kill(self):
            self.killed = True
            self.terminated.set()
        def wait(self):
            assert self.terminated.wait(3)
            return 1
    process = Process(['runtime', '-NoLogo', '-NoProfile', '-NonInteractive'], creationflags=0x08000000)
    monkeypatch.setattr(local_speech, 'powershell_path', lambda: 'trusted-system-powershell')
    monkeypatch.setattr(local_speech.subprocess, 'Popen', lambda *args, **kwargs: process)
    with pytest.raises(SpeechUnavailable):
        local_speech.run_worker({'operation': 'status'}, threading.Event(), .01)
    assert process.killed and process.drained


@pytest.mark.skipif(os.name != 'nt', reason='Windows pipe cancellation regression')
@pytest.mark.parametrize('stop', ['deadline', 'cancel'])
def test_stalled_real_child_cannot_block_audio_upload_cancellation(monkeypatch, stop):
    """A real hidden child deliberately never consumes its large stdin payload."""
    real_popen = subprocess.Popen
    owned = []
    def stalled_child(command, **kwargs):
        assert command[1:4] == ['-NoLogo', '-NoProfile', '-NonInteractive']
        assert kwargs['creationflags'] == 0x08000000
        child = real_popen([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
        owned.append(child)
        return child
    monkeypatch.setattr(local_speech, 'powershell_path', lambda: 'trusted-system-powershell')
    monkeypatch.setattr(local_speech.subprocess, 'Popen', stalled_child)
    cancelled = threading.Event()
    timer = threading.Timer(.15, cancelled.set)
    if stop == 'cancel':
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(SpeechUnavailable, match='cancelled or deadline'):
            local_speech.run_worker({'audio': 'A' * 900000}, cancelled, .15 if stop == 'deadline' else 5)
        assert time.monotonic() - started < 3
        assert len(owned) == 1 and owned[0].poll() is not None
        assert owned[0].stdin.closed and owned[0].stdout.closed and owned[0].stderr.closed
        assert not any(thread.name == 'BEL-speech-pipes' for thread in threading.enumerate())
    finally:
        timer.cancel()
        for child in owned:
            if child.poll() is None:
                child.kill()
            child.wait()


def test_failed_pipe_exchange_is_reported_without_payload(monkeypatch):
    class FailedProcess:
        def communicate(self, **kwargs):
            raise OSError('private payload')
        def poll(self):
            return 1
        def wait(self):
            return 1
    monkeypatch.setattr(local_speech, 'powershell_path', lambda: 'trusted-system-powershell')
    monkeypatch.setattr(local_speech.subprocess, 'Popen', lambda *args, **kwargs: FailedProcess())
    with pytest.raises(SpeechUnavailable, match='transport failed') as error:
        local_speech.run_worker({'audio': 'private payload'}, threading.Event(), 1)
    assert 'private' not in str(error.value)
