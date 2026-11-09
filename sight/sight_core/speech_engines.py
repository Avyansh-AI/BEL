"""Local-only speech selection. Audio and recognized text are untrusted drafts."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import threading
import time

from .asr_assets import MODELS, default_directory, verified_assets
from .local_speech import LocalSpeech, LOCALES, SpeechBusy, SpeechInputError, SpeechUnavailable, run_process, validate_audio
from .speech_resources import available_memory

WHISPER_LOCALES = sorted(LOCALES | {'auto'})
ENGINE_LABELS = {'windows': 'Windows System.Speech', 'whisper_cpp': 'whisper.cpp CPU'}


def worker_environment():
    # Exclude caller-controlled backend/plugin injection paths and cloud keys.
    result = {key: value for key, value in os.environ.items()
              if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC'}}
    result['PATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
    result['OMP_NUM_THREADS'] = '4'
    return result


class WhisperCpp(LocalSpeech):
    def __init__(self, asset_dir=None, model='small-q5_1', enabled=True):
        super().__init__(enabled)
        if model not in MODELS:
            raise ValueError('Unsupported offline ASR model')
        self.asset_dir = Path(asset_dir) if asset_dir is not None else default_directory()
        self.model = model

    def _probe(self, request, cancelled, timeout):
        try:
            with verified_assets(self.asset_dir, self.model, cancelled):
                return True
        except (ValueError, OSError) as exc:
            raise SpeechUnavailable('Pinned offline speech assets are unavailable or incomplete') from exc

    async def status(self):
        if not self.enabled:
            return {'available': False, 'locales': [], 'reason': 'Local dictation is off. Launch BEL with --local-dictation to offer it. Wake detection remains unavailable.'}
        if self._cached_status is not None and time.monotonic() < self._status_until:
            return dict(self._cached_status)
        try:
            await self._request({}, 10, self._probe)
            status = {'available': True, 'locales': WHISPER_LOCALES,
                      'reason': 'Pinned CPU recognizer installed. Review every transcript; multilingual accuracy requires separate evaluation.'}
        except SpeechBusy:
            return dict(self._cached_status) if self._cached_status else {'available': False, 'locales': [], 'reason': 'Recognition is busy.'}
        except SpeechUnavailable:
            status = {'available': False, 'locales': [], 'reason': 'Install the pinned whisper.cpp runtime and model explicitly; no automatic download is performed.'}
        self._cached_status, self._status_until = status, time.monotonic() + 30
        return dict(status)

    def _recognize(self, request, cancelled, timeout):
        raw, locale = request
        started = time.monotonic()
        try:
            if available_memory() < 256 * 1024**2:
                raise SpeechUnavailable('Insufficient available RAM for local recognition')
            with verified_assets(self.asset_dir, self.model, cancelled) as (executable, weights):
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise SpeechUnavailable('Speech asset verification deadline exceeded')
                language = 'auto' if locale == 'auto' else locale.split('-')[0]
                # Upstream Windows --output-json --output-file - writes to CON,
                # not the redirected pipe. Use the segment stdout callback. A
                # fixed unused output basename enables it for stdin input; no
                # --output-* switch is set, so no audio/transcript file is made.
                command = [str(executable), '--model', str(weights), '--no-gpu', '--threads', '4',
                           '--processors', '1', '--language', language, '--no-prints', '--no-timestamps',
                           '--output-file', 'BEL-memory-only', '-']
                output = run_process(command, raw, cancelled, remaining, cwd=executable.parent,
                                     env=worker_environment(), memory_limit=1536 * 1024**2)
            text = output.decode('utf-8-sig').strip()
        except (OSError, ValueError, UnicodeError) as exc:
            raise SpeechUnavailable('Pinned offline speech worker failed safely') from exc
        if len(text) > 8000 or any(ord(c) < 32 and c not in '\r\n\t' for c in text):
            raise SpeechUnavailable('Invalid offline recognition response')
        if not text:
            raise SpeechInputError('No speech recognized')
        return {'text': text, 'confidence': None, 'confidence_kind': 'unavailable', 'locale': locale,
                'engine': ENGINE_LABELS['whisper_cpp'], 'engine_id': 'whisper_cpp', 'model': self.model,
                'review_required': True}

    async def transcribe(self, raw, locale='en-US'):
        if not self.enabled:
            raise SpeechUnavailable('Local dictation is disabled')
        validate_audio(raw)
        if locale not in WHISPER_LOCALES:
            raise SpeechInputError('Unsupported language')
        return await self._request((raw, locale), 60, self._recognize)


class SpeechService:
    """Serialize all engines and expose only validated, explicitly local fallback."""
    def __init__(self, enabled=False, *, asset_dir=None, model='small-q5_1', preferred='whisper_cpp'):
        if preferred not in ENGINE_LABELS:
            raise ValueError('Unknown speech engine')
        self.enabled, self.preferred = enabled, preferred
        self.engines = {'whisper_cpp': WhisperCpp(asset_dir, model, enabled), 'windows': LocalSpeech(enabled)}
        self._busy = threading.Lock()

    async def status(self):
        engines = []
        for identifier, engine in self.engines.items():
            status = await engine.status()
            engines.append({'id': identifier, 'label': ENGINE_LABELS[identifier], **status})
        selected = next(item for item in engines if item['id'] == self.preferred)
        fallback = selected if selected['available'] else next((e for e in engines if e['available']), selected)
        reason = fallback['reason']
        if fallback['id'] != self.preferred:
            reason = 'Preferred engine unavailable; using installed ' + fallback['label'] + '. ' + reason
        return {'available': fallback['available'], 'locales': fallback['locales'], 'reason': reason,
                'engine': fallback['label'], 'engines': engines, 'default_engine': fallback['id'],
                'preferred_engine': self.preferred, 'degraded': fallback['id'] != self.preferred}

    async def transcribe(self, raw, locale='en-US', *, engine=None, allow_fallback=True):
        if not self.enabled:
            raise SpeechUnavailable('Local dictation is disabled')
        validate_audio(raw)
        requested = engine or self.preferred
        if requested not in self.engines or locale not in WHISPER_LOCALES or type(allow_fallback) is not bool:
            raise SpeechInputError('Unsupported speech selection')
        if not self._busy.acquire(blocking=False):
            raise SpeechBusy('A local recognition worker is running')
        try:
            candidates = [requested] + ([name for name in self.engines if name != requested] if allow_fallback else [])
            for identifier in candidates:
                recognizer = self.engines[identifier]
                status = await recognizer.status()
                if not status['available'] or locale not in status['locales']:
                    continue
                try:
                    result = await recognizer.transcribe(raw, locale)
                except SpeechUnavailable:
                    continue
                # Cancellation, invalid audio/no speech and busy errors propagate:
                # none may start a second engine or produce a late transcript.
                return {**result, 'engine_id': identifier, 'requested_engine': requested,
                        'confidence_kind': result.get('confidence_kind', 'engine_score'),
                        'fallback_from': requested if requested != identifier else None,
                        'fallback_reason': 'Requested engine or language unavailable, or its worker failed safely.' if requested != identifier else None}
            raise SpeechUnavailable('No available local recognizer completed this request')
        finally:
            self._busy.release()
