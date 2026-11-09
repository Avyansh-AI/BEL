"""Opt-in Windows dictation with bounded input and disposable fixed workers."""
from __future__ import annotations

import asyncio
from array import array
import base64
import ctypes
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import subprocess
import threading
import time
import wave

from .speech_worker import POWERSHELL

MAX_AUDIO_BYTES = 700000
LOCALES = frozenset({'en-US', 'en-GB', 'en-IN', 'hi-IN'})


class SpeechUnavailable(RuntimeError):
    pass


class SpeechBusy(RuntimeError):
    pass


class SpeechInputError(ValueError):
    pass


def validate_audio(raw):
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= MAX_AUDIO_BYTES:
        raise SpeechInputError('Audio size limit')
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE' or struct.unpack_from('<I', raw, 4)[0] + 8 != len(raw):
        raise SpeechInputError('Invalid WAV container')
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise SpeechInputError('Expected mono 16 kHz 16-bit PCM')
            frames = audio.getnframes()
            if not 1600 <= frames <= 320000:
                raise SpeechInputError('Record between 0.1 and 20 seconds')
            samples = audio.readframes(frames + 1)
            if len(samples) != frames * 2:
                raise SpeechInputError('Truncated PCM samples')
    except (wave.Error, EOFError, struct.error) as exc:
        raise SpeechInputError('Invalid WAV audio') from exc
    values = array('h', samples)
    if sys.byteorder != 'little':
        values.byteswap()
    if sum(value * value for value in values) < 16 * 16 * len(values):
        raise SpeechInputError('Recording is silent or below the supported audio level')


def powershell_path():
    if os.name != 'nt':
        raise SpeechUnavailable('Windows local dictation is unavailable')
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise SpeechUnavailable('System runtime path unavailable')
    path = Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe'
    if not path.is_file():
        raise SpeechUnavailable('Windows speech runtime unavailable')
    return path


def run_worker(request, cancelled, timeout):
    encoded = base64.b64encode(POWERSHELL.encode('utf-16-le')).decode('ascii')
    command = [str(powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    payload = json.dumps(request, ensure_ascii=True).encode('ascii')
    output = run_process(command, payload, cancelled, timeout)
    try:
        result = json.loads(output.decode('utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise SpeechUnavailable('Invalid local speech response') from exc
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise SpeechUnavailable('Local recognizer failed')
    return result


def run_process(command, payload, cancelled, timeout, *, cwd=None, env=None, memory_limit=None):
    """Pipe transport for fixed, locally verified recognizer commands only."""
    if cancelled.is_set():
        raise SpeechUnavailable('Cancelled before startup')
    options = {}
    if cwd is not None:
        options['cwd'] = str(cwd)
    if env is not None:
        options['env'] = env
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=0x08000000, **options)
    deadline = time.monotonic() + timeout
    completed = threading.Event()
    response = []
    failures = []

    def exchange():
        try:
            response.append(process.communicate(input=payload))
        except Exception as exc:
            failures.append(exc)
        finally:
            completed.set()

    # On Windows communicate(timeout=...) still writes stdin synchronously.
    # A child stuck before reading a full audio request would otherwise prevent
    # both its deadline and cancellation from being observed. Keep all pipe I/O
    # on one owned thread while this worker can terminate the exact child.
    exchange_thread = threading.Thread(target=exchange, name='BEL-speech-pipes', daemon=True)
    job = None
    try:
        if memory_limit is not None:
            from .speech_resources import ProcessBudget
            job = ProcessBudget(process, memory_limit)
        exchange_thread.start()
        while not completed.wait(.05):
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise SpeechUnavailable('Dictation cancelled or deadline exceeded')
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise SpeechUnavailable('Dictation cancelled or deadline exceeded')
        if failures or not response:
            raise SpeechUnavailable('Local speech transport failed')
        output, errors = response[0]
        if process.returncode or len(output) > 50000 or len(errors) > 20000:
            raise SpeechUnavailable('Local recognizer failed')
        return output
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        # Never release the serialization lock while the previous worker or
        # its input/output thread is alive. Termination unblocks stdin writes.
        if exchange_thread.ident is not None:
            exchange_thread.join()
        else:
            process.communicate()
        for name in ('stdin', 'stdout', 'stderr'):
            stream = getattr(process, name, None)
            if stream is not None and not stream.closed:
                stream.close()
        if job is not None:
            job.close()


class LocalSpeech:
    def __init__(self, enabled=False):
        if type(enabled) is not bool:
            raise ValueError('Speech configuration must be boolean')
        self.enabled = enabled
        self._busy = threading.Lock()
        self._cached_status = None
        self._status_until = 0

    async def _request(self, value, timeout, runner=None):
        if not self._busy.acquire(blocking=False):
            raise SpeechBusy('A local recognition worker is running')
        cancelled = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(runner or run_worker, value, cancelled, timeout))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            # Preserve serialization until the exact owned process has exited,
            # even when shutdown or repeated client cancellations interrupt us.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            raise
        except OSError as exc:
            raise SpeechUnavailable('Windows speech worker unavailable') from exc
        finally:
            cancelled.set()
            self._busy.release()

    async def status(self):
        if not self.enabled:
            return {'available': False, 'locales': [], 'reason': 'Local dictation is off. Launch BEL with --local-dictation to offer it. Wake detection remains unavailable.'}
        if self._cached_status is not None and time.monotonic() < self._status_until:
            return dict(self._cached_status)
        try:
            result = await self._request({'operation': 'status'}, 10)
            locales = result.get('locales')
            if not isinstance(locales, list) or any(not isinstance(x, str) or x not in LOCALES for x in locales):
                raise SpeechUnavailable('Invalid language list')
            status = {'available': bool(locales), 'locales': sorted(set(locales)),
                      'reason': 'Local Windows dictation requires session consent and hold-to-talk. Review its transcript before sending.' if locales else 'No supported English or Hindi Windows recognizer is installed.'}
        except SpeechBusy:
            return dict(self._cached_status) if self._cached_status is not None else {'available': False, 'locales': [], 'reason': 'Local speech is busy. Try again after the current request.'}
        except SpeechUnavailable:
            status = {'available': False, 'locales': [], 'reason': 'The local Windows speech runtime is unavailable.'}
        self._cached_status = status
        self._status_until = time.monotonic() + 30
        return dict(status)

    async def transcribe(self, raw, locale='en-US'):
        if not self.enabled:
            raise SpeechUnavailable('Local dictation is disabled')
        validate_audio(raw)
        if locale not in LOCALES:
            raise SpeechInputError('Unsupported language')
        result = await self._request({'operation': 'transcribe', 'audio': base64.b64encode(raw).decode('ascii'), 'locale': locale}, 25)
        text, confidence = result.get('text'), result.get('confidence')
        if (not isinstance(text, str) or len(text) > 8000 or '\x00' in text
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1 or result.get('locale') != locale):
            raise SpeechUnavailable('Invalid recognition result')
        if not text.strip():
            raise SpeechInputError('No speech recognized')
        return {'text': text.strip(), 'confidence': confidence, 'locale': locale,
                'engine': 'Windows System.Speech', 'review_required': True}
