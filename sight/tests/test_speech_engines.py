import asyncio
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import sys
import wave

import pytest

from sight_core import asr_assets, speech_engines
from sight_core.local_speech import SpeechBusy, SpeechInputError, SpeechUnavailable, validate_audio
from sight_core.speech_engines import SpeechService, WhisperCpp


def audio(value=2048):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 16000, 3200, 'NONE', 'not compressed'))
        stream.writeframes(int(value).to_bytes(2, 'little', signed=True) * 3200)
    return output.getvalue()


@pytest.mark.parametrize('value', [0, 1, -1, 15, -15])
def test_near_silence_is_rejected_without_recognizer(value):
    with pytest.raises(SpeechInputError, match='silent'):
        validate_audio(audio(value))


class Engine:
    def __init__(self, *, available=True, locales=None, error=None):
        self.available, self.locales, self.error = available, locales or ['en-US'], error
        self.calls = 0

    async def status(self):
        return {'available': self.available, 'locales': self.locales, 'reason': 'Fixture'}

    async def transcribe(self, raw, locale):
        self.calls += 1
        if self.error:
            raise self.error('fixture')
        return {'text': 'untrusted draft', 'locale': locale, 'confidence': .4, 'review_required': True}


def service(primary=None, fallback=None):
    item = SpeechService(True)
    item.engines = {'whisper_cpp': primary or Engine(), 'windows': fallback or Engine()}
    return item


@pytest.mark.parametrize('primary', [Engine(available=False), Engine(error=SpeechUnavailable)])
def test_safe_failure_can_only_fall_back_to_validated_local_engine(primary):
    item = service(primary)
    result = asyncio.run(item.transcribe(audio()))
    assert result['engine_id'] == 'windows' and result['fallback_from'] == 'whisper_cpp'
    assert result['review_required'] and result['fallback_reason']


def test_disallowed_fallback_and_unsupported_language_never_start_second_engine():
    item = service(Engine(available=False))
    with pytest.raises(SpeechUnavailable):
        asyncio.run(item.transcribe(audio(), allow_fallback=False))
    with pytest.raises(SpeechUnavailable):
        asyncio.run(item.transcribe(audio(), locale='hi-IN'))
    assert item.engines['windows'].calls == 0


@pytest.mark.parametrize('failure', [SpeechInputError, SpeechBusy, asyncio.CancelledError])
def test_silence_busy_and_cancellation_do_not_fall_back(failure):
    item = service(Engine(error=failure))
    with pytest.raises(failure):
        asyncio.run(item.transcribe(audio()))
    assert item.engines['windows'].calls == 0 and not item._busy.locked()


def test_all_engine_execution_is_serialized():
    async def run():
        began, release = asyncio.Event(), asyncio.Event()
        class Pending(Engine):
            async def transcribe(self, raw, locale):
                began.set()
                await release.wait()
                return await super().transcribe(raw, locale)
        item = service(Pending())
        task = asyncio.create_task(item.transcribe(audio()))
        await began.wait()
        with pytest.raises(SpeechBusy):
            await item.transcribe(audio(), engine='windows')
        assert item.engines['windows'].calls == 0
        release.set()
        await task
    asyncio.run(run())


def test_status_reports_actual_degraded_engine_and_missing_models():
    item = service(Engine(available=False))
    status = asyncio.run(item.status())
    assert status['degraded'] and status['default_engine'] == 'windows'
    assert status['preferred_engine'] == 'whisper_cpp'
    assert len(status['engines']) == 2


@pytest.fixture
def fake_assets(monkeypatch, tmp_path):
    @contextmanager
    def verified(*args):
        yield tmp_path / 'runtime/whisper-cli.exe', tmp_path / 'model.bin'
    monkeypatch.setattr(speech_engines, 'verified_assets', verified)
    monkeypatch.setattr(speech_engines, 'available_memory', lambda: 1024**3)
    return tmp_path


def test_fixed_cpu_command_has_no_prompt_or_output_file_switch(fake_assets, monkeypatch):
    def run(command, payload, cancelled, timeout, **kwargs):
        assert command[command.index('--language') + 1] == 'hi'
        assert '--no-gpu' in command and '--prompt' not in command
        assert '--output-json' not in command and '--output-txt' not in command
        assert command[-3:] == ['--output-file', 'BEL-memory-only', '-']
        assert kwargs['memory_limit'] == 1536 * 1024**2
        assert payload == audio() and timeout <= 60
        return 'नमस्ते'.encode('utf-8')
    monkeypatch.setattr(speech_engines, 'run_process', run)
    result = asyncio.run(WhisperCpp(fake_assets).transcribe(audio(), 'hi-IN'))
    assert result['text'] == 'नमस्ते' and result['confidence'] is None
    assert result['confidence_kind'] == 'unavailable' and result['review_required']


@pytest.mark.parametrize('output,error', [(b'', SpeechInputError), (b'\xff', SpeechUnavailable),
                                         (b'draft\x00injection', SpeechUnavailable), (b'x' * 8001, SpeechUnavailable)])
def test_bad_worker_output_never_becomes_a_draft(fake_assets, monkeypatch, output, error):
    monkeypatch.setattr(speech_engines, 'run_process', lambda *args, **kwargs: output)
    with pytest.raises(error):
        asyncio.run(WhisperCpp(fake_assets).transcribe(audio()))


def test_low_memory_does_not_start_worker(fake_assets, monkeypatch):
    monkeypatch.setattr(speech_engines, 'available_memory', lambda: 128 * 1024**2)
    monkeypatch.setattr(speech_engines, 'run_process', lambda *a, **k: pytest.fail('low-memory worker launched'))
    with pytest.raises(SpeechUnavailable, match='RAM'):
        asyncio.run(WhisperCpp(fake_assets).transcribe(audio()))


def test_no_engine_or_download_starts_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_engines, 'verified_assets', lambda *a: pytest.fail('disabled assets inspected'))
    item = SpeechService(False, asset_dir=tmp_path)
    assert not asyncio.run(item.status())['available']
    with pytest.raises(SpeechUnavailable):
        asyncio.run(item.transcribe(audio()))


def test_worker_environment_drops_plugin_and_secret_variables(monkeypatch):
    monkeypatch.setenv('GGML_BACKEND_DL_PATH', 'untrusted')
    monkeypatch.setenv('GROQ_API_KEY', 'fixture')
    monkeypatch.setenv('PYTHONPATH', 'untrusted')
    assert not {'GGML_BACKEND_DL_PATH', 'GROQ_API_KEY', 'PYTHONPATH'} & speech_engines.worker_environment().keys()


@pytest.fixture
def pinned_install(tmp_path, monkeypatch):
    runtime = {'whisper-cli.exe': [3, hashlib.sha256(b'exe').hexdigest()]}
    models = {'base-q5_1': [5, hashlib.sha256(b'model').hexdigest()]}
    monkeypatch.setattr(asr_assets, 'RUNTIME_FILES', runtime)
    monkeypatch.setattr(asr_assets, 'MODELS', models)
    (tmp_path / 'runtime').mkdir()
    (tmp_path / 'models').mkdir()
    (tmp_path / 'runtime/whisper-cli.exe').write_bytes(b'exe')
    (tmp_path / 'models/ggml-base-q5_1.bin').write_bytes(b'model')
    (tmp_path / 'manifest.json').write_text(json.dumps(asr_assets.manifest(['base-q5_1'])), encoding='utf-8')
    return tmp_path


@pytest.mark.skipif(os.name != 'nt', reason='Windows asset lock')
@pytest.mark.parametrize('damage', ['runtime', 'weight', 'missing', 'extra', 'manifest', 'oversized-manifest'])
def test_incomplete_or_tampered_installation_fails_closed(pinned_install, damage):
    root = pinned_install
    if damage == 'runtime':
        (root / 'runtime/whisper-cli.exe').write_bytes(b'bad')
    elif damage == 'weight':
        (root / 'models/ggml-base-q5_1.bin').write_bytes(b'other')
    elif damage == 'missing':
        (root / 'models/ggml-base-q5_1.bin').unlink()
    elif damage == 'extra':
        (root / 'runtime/extra.dll').write_bytes(b'extra')
    else:
        (root / 'manifest.json').write_text('{}' if damage == 'manifest' else ' ' * 17000)
    with pytest.raises((ValueError, OSError)):
        with asr_assets.verified_assets(root, 'base-q5_1'):
            pytest.fail('Damaged installation accepted')


@pytest.mark.skipif(os.name != 'nt', reason='Windows asset lock')
def test_runtime_and_model_cannot_be_replaced_during_worker_use(pinned_install):
    with asr_assets.verified_assets(pinned_install, 'base-q5_1') as (exe, model):
        for path in (exe, model):
            with pytest.raises(OSError):
                path.write_bytes(b'alteration')


def test_hash_verification_honors_cancellation(pinned_install):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ValueError, match='cancelled'):
        asr_assets.verify_file(pinned_install / 'runtime/whisper-cli.exe', asr_assets.RUNTIME_FILES['whisper-cli.exe'], cancelled)


@pytest.mark.parametrize('models', [None, {}, [{}], [[]], [1], ['unknown'], ['base-q5_1', 'base-q5_1']])
def test_invalid_manifest_models_rejected_as_integrity_error(models):
    with pytest.raises(ValueError):
        asr_assets.manifest(models)


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows Job Object memory containment')
def test_real_child_allocation_is_limited_without_host_exhaustion():
    from sight_core.local_speech import run_process
    code = ('import sys; sys.stdin.buffer.read();\n'
            'try: data=bytearray(128*1024**2); print("unlimited")\n'
            'except MemoryError: print("limited")\n')
    # Use the actual interpreter: the venv redirector creates another process,
    # which the recognizer's one-process Job Object correctly forbids.
    result = run_process([str(Path(sys.base_prefix) / 'python.exe'), '-c', code], b'start', threading.Event(), 10,
                         memory_limit=64 * 1024**2)
    assert result.strip() == b'limited'
