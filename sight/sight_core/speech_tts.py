"""Local Windows speech synthesis engine (TTS).

Generates standard WAV audio locally without cloud dependencies, network calls,
or telemetry. Uses WinRT Windows.Media.SpeechSynthesis or SAPI fallback in an
isolated child worker.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import base64
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from .local_speech import powershell_path

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4000
DEFAULT_TIMEOUT = 20.0
MAX_TTS_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MiB limit for base64 audio response


def run_tts_process(command, payload, cancelled, timeout, *, memory_limit=None):
    """Pipe transport for fixed, locally verified TTS worker commands."""
    if cancelled.is_set():
        raise TTSUnavailable("Cancelled before startup")
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )
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

    exchange_thread = threading.Thread(target=exchange, name="BEL-tts-pipes", daemon=True)
    job = None
    try:
        if memory_limit is not None:
            try:
                from .speech_resources import ProcessBudget
                job = ProcessBudget(process, memory_limit)
            except Exception:
                pass
        exchange_thread.start()
        while not completed.wait(0.05):
            if cancelled.is_set() or time.monotonic() >= deadline:
                raise TTSUnavailable("TTS cancelled or deadline exceeded")
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise TTSUnavailable("TTS cancelled or deadline exceeded")
        if failures or not response:
            raise TTSUnavailable("Local TTS speech transport failed")
        output, errors = response[0]
        if process.returncode or len(output) > MAX_TTS_OUTPUT_BYTES or len(errors) > 20000:
            err_msg = errors.decode("utf-8", errors="replace").strip() if errors else f"code {process.returncode}"
            raise TTSUnavailable(f"Local TTS worker failed: {err_msg}")
        return output
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()

WINRT_TTS_WORKER = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

try {
    $rawInput = [Console]::In.ReadToEnd()
    if (-not $rawInput) { throw 'Empty input payload' }
    $req = $rawInput | ConvertFrom-Json

    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.SpeechSynthesis.SpeechSynthesisStream, Windows.Media, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

    $synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    $allVoices = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices

    if ($req.operation -eq 'voices' -or $req.operation -eq 'status') {
        $voiceList = @()
        foreach ($v in $allVoices) {
            $voiceList += @{
                id = $v.Id
                name = $v.DisplayName
                language = $v.Language
                gender = $v.Gender.ToString()
            }
        }
        $resp = @{
            ok = $true
            available = $true
            voices = $voiceList
            default_voice = $synth.Voice.DisplayName
            count = $voiceList.Count
        }
        $resp | ConvertTo-Json -Compress
        exit 0
    }

    if ($req.operation -eq 'synthesize') {
        $text = [string]$req.text
        if (-not $text) { throw 'Text is required for synthesis' }
        if ($text.Length -gt 4000) { throw 'Text exceeds maximum length of 4000 characters' }

        if ($req.voice) {
            $matched = $allVoices | Where-Object {
                $_.DisplayName -like "*$($req.voice)*" -or $_.Id -eq $req.voice
            } | Select-Object -First 1
            if ($matched) {
                $synth.Voice = $matched
            }
        }

        if ($null -ne $req.rate) {
            $rateVal = [double]$req.rate
            if ($rateVal -ge 0.5 -and $rateVal -le 3.0) {
                $synth.Options.SpeakingRate = $rateVal
            }
        }

        if ($null -ne $req.pitch) {
            $pitchVal = [double]$req.pitch
            if ($pitchVal -ge 0.5 -and $pitchVal -le 2.0) {
                $synth.Options.AudioPitch = $pitchVal
            }
        }

        if ($null -ne $req.volume) {
            $volVal = [double]$req.volume
            if ($volVal -ge 0.0 -and $volVal -le 1.0) {
                $synth.Options.AudioVolume = $volVal
            }
        }

        $streamOp = $synth.SynthesizeTextToStreamAsync($text)
        $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        }[0]
        $asTask = $asTaskGeneric.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
        $task = $asTask.Invoke($null, @($streamOp))
        $task.Wait(15000) | Out-Null
        $stream = $task.Result

        $size = [uint32]$stream.Size
        $reader = New-Object Windows.Storage.Streams.DataReader($stream)
        $loadOp = $reader.LoadAsync($size)
        $asTaskUint = $asTaskGeneric.MakeGenericMethod([uint32])
        $loadTask = $asTaskUint.Invoke($null, @($loadOp))
        $loadTask.Wait(15000) | Out-Null

        $bytes = New-Object byte[] $size
        $reader.ReadBytes($bytes)
        $b64 = [Convert]::ToBase64String($bytes)

        @{
            ok = $true
            audio = $b64
            format = 'audio/wav'
            size = $bytes.Length
            voice = $synth.Voice.DisplayName
        } | ConvertTo-Json -Compress
        exit 0
    }

    throw "Unknown operation: $($req.operation)"
} catch {
    @{
        ok = $false
        error = $_.Exception.Message
    } | ConvertTo-Json -Compress
    exit 1
}
'''


class TTSUnavailable(RuntimeError):
    pass


class TTSBusy(RuntimeError):
    pass


class TTSInputError(ValueError):
    pass


class LocalTTS:
    """Manages local speech synthesis without network access or cloud dependencies."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._cached_status: dict | None = None
        self._cached_voices: list[dict] | None = None
        self._status_expires: float = 0.0

    def _execute_worker(self, request: dict, timeout: float = DEFAULT_TIMEOUT) -> dict:
        if os.name != "nt":
            raise TTSUnavailable("Local TTS requires Windows host environment")
        
        try:
            ps_bin = powershell_path()
        except Exception as exc:
            raise TTSUnavailable("Windows PowerShell runtime unavailable") from exc

        encoded = base64.b64encode(WINRT_TTS_WORKER.encode("utf-16-le")).decode("ascii")
        command = [str(ps_bin), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
        payload = json.dumps(request, ensure_ascii=True).encode("utf-8")
        cancelled = threading.Event()

        try:
            output = run_tts_process(command, payload, cancelled, timeout, memory_limit=512 * 1024 * 1024)
        except Exception as exc:
            raise TTSUnavailable(f"TTS worker failed: {exc}") from exc

        try:
            result = json.loads(output.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise TTSUnavailable("Invalid response from TTS worker") from exc

        if not isinstance(result, dict) or not result.get("ok"):
            error_msg = result.get("error", "Unknown worker error") if isinstance(result, dict) else "Corrupted response"
            raise TTSUnavailable(f"TTS worker failed: {error_msg}")

        return result

    async def status(self) -> dict:
        if not self.enabled or os.name != "nt":
            return {
                "available": False,
                "enabled": self.enabled,
                "voices": [],
                "reason": "Local TTS is disabled or unavailable on this host" if not self.enabled else "Windows environment required",
                "default_voice": None,
            }

        now = time.monotonic()
        if self._cached_status and now < self._status_expires:
            return dict(self._cached_status)

        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, self._execute_worker, {"operation": "status"}, 10.0)
            status_data = {
                "available": True,
                "enabled": True,
                "voices": res.get("voices", []),
                "default_voice": res.get("default_voice"),
                "reason": "Windows native offline speech synthesis operational",
            }
            self._cached_status = status_data
            self._cached_voices = res.get("voices", [])
            self._status_expires = now + 60.0
            return dict(status_data)
        except Exception as exc:
            logger.warning("TTS status check failed: %s", exc)
            return {
                "available": False,
                "enabled": self.enabled,
                "voices": [],
                "reason": f"Offline TTS probe failed: {exc}",
                "default_voice": None,
            }

    async def list_voices(self) -> list[dict]:
        status_info = await self.status()
        if not status_info.get("available"):
            raise TTSUnavailable(status_info.get("reason", "TTS unavailable"))
        return list(self._cached_voices or [])

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        rate: float | None = 1.0,
        pitch: float | None = 1.0,
        volume: float | None = 1.0,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        if not self.enabled:
            raise TTSUnavailable("Local TTS is disabled")
        if not isinstance(text, str) or not text.strip():
            raise TTSInputError("Text must be a non-empty string")
        clean_text = text.strip()
        if len(clean_text) > MAX_TEXT_LENGTH:
            raise TTSInputError(f"Text exceeds maximum supported length ({MAX_TEXT_LENGTH} characters)")
        if any(ord(c) < 32 and c not in "\r\n\t" for c in clean_text):
            raise TTSInputError("Text contains unsupported control characters")

        if not self._lock.acquire(blocking=False):
            raise TTSBusy("Another local speech synthesis request is currently running")

        try:
            req = {
                "operation": "synthesize",
                "text": clean_text,
                "voice": voice,
                "rate": rate,
                "pitch": pitch,
                "volume": volume,
            }
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, self._execute_worker, req, timeout)
            audio_b64 = res.get("audio")
            if not audio_b64:
                raise TTSUnavailable("TTS worker returned empty audio payload")
            audio_bytes = base64.b64decode(audio_b64)
            if len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF":
                raise TTSUnavailable("TTS worker returned invalid WAV container")
            return audio_bytes
        finally:
            self._lock.release()
