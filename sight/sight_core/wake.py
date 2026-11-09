"""Disabled, offline wake-engine boundary; no BEL model has been qualified.

This module opens no devices and loads no models. A future detector may consume
bounded PCM frames only after separate persistent-listening consent. Detection
is an event for the owner interface, never a dictation submission or tool call.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

SAMPLE_RATE = 16000
FRAME_BYTES = 2560  # 80 ms, signed 16-bit mono PCM


@dataclass(frozen=True)
class WakeDetection:
    phrase: str
    score: float
    model_sha256: str

    def __post_init__(self):
        if self.phrase != 'BEL':
            raise ValueError('Only the enrolled BEL phrase is supported')
        if type(self.score) not in (int, float) or not math.isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError('A bounded engine score is required')
        if not isinstance(self.model_sha256, str) or len(self.model_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.model_sha256):
            raise ValueError('A pinned model identity is required')


@runtime_checkable
class WakeEngine(Protocol):
    def status(self) -> dict: ...
    def feed(self, pcm: bytes) -> WakeDetection | None: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


class DisabledWakeEngine:
    """Fail-closed placeholder, intentionally incapable of activation."""

    def status(self):
        return {'enabled': False, 'available': False, 'enrolled': False, 'phrase': 'BEL',
                'reason': 'A licensed, trained BEL-specific model and representative hardware validation are required.'}

    def feed(self, pcm):
        if not isinstance(pcm, bytes) or len(pcm) != FRAME_BYTES:
            raise ValueError('Expected one 80 ms mono 16 kHz 16-bit PCM frame')
        return None

    def reset(self):
        pass

    def close(self):
        pass
