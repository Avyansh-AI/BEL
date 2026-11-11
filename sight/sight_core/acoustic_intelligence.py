"""Acoustic Scene Intelligence and Meeting Summarizer for BEL (Stage 8).

Performs spectral feature extraction (RMS energy, Zero-Crossing Rate,
spectral centroid approximation), acoustic scene classification,
and meeting notes synthesis with action item extraction.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct
import wave
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field


class AcousticFeatures(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rms_energy: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid_hz: float = 0.0
    silence_ratio: float = 0.0
    duration_sec: float = 0.0
    sample_rate: int = 16000


class AcousticSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene_type: str  # speech, music, ambient_noise, silence, alarm
    confidence: float = 0.90
    features: AcousticFeatures
    description: str = ""


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    owner: str = "Unassigned"
    task: str
    priority: str = "medium"  # high, medium, low


class MeetingSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = "Meeting Debrief"
    summary: str
    topics: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


class AcousticIntelligence:
    """Provides audio scene analysis and meeting notes synthesis."""

    def extract_features(self, pcm_bytes: bytes, sample_rate: int = 16000) -> AcousticFeatures:
        """Compute RMS energy, Zero-Crossing Rate, and spectral features on 16-bit mono PCM."""
        if len(pcm_bytes) < 2:
            return AcousticFeatures(sample_rate=sample_rate)

        # Unpack 16-bit signed PCM
        num_samples = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_bytes[: num_samples * 2])
        except Exception:
            return AcousticFeatures(sample_rate=sample_rate)

        if not samples:
            return AcousticFeatures(sample_rate=sample_rate)

        duration = num_samples / sample_rate

        # 1. RMS Energy
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / num_samples)

        # 2. Zero-Crossing Rate
        crossings = 0
        for i in range(1, num_samples):
            if (samples[i] >= 0 and samples[i - 1] < 0) or (samples[i] < 0 and samples[i - 1] >= 0):
                crossings += 1
        zcr = crossings / max(1, num_samples - 1)

        # 3. Silence ratio (samples below threshold)
        silence_thresh = 300.0
        silent_samples = sum(1 for s in samples if abs(s) < silence_thresh)
        silence_ratio = silent_samples / num_samples

        # 4. Spectral Centroid approximation (weighted frequency based on derivative / slope)
        diff_energy = 0.0
        for i in range(1, num_samples):
            diff = samples[i] - samples[i - 1]
            diff_energy += diff * diff

        # Normalize spectral centroid estimate
        slope_factor = math.sqrt(diff_energy / max(1, num_samples - 1)) / max(1.0, rms)
        approx_centroid = min(sample_rate / 2.0, slope_factor * (sample_rate / (2 * math.pi)))

        return AcousticFeatures(
            rms_energy=round(rms, 2),
            zero_crossing_rate=round(zcr, 4),
            spectral_centroid_hz=round(approx_centroid, 1),
            silence_ratio=round(silence_ratio, 3),
            duration_sec=round(duration, 3),
            sample_rate=sample_rate,
        )

    def classify_scene(self, pcm_bytes: bytes, sample_rate: int = 16000) -> AcousticSceneResult:
        """Classify acoustic environment into speech, silence, alarm, music, or ambient noise."""
        feat = self.extract_features(pcm_bytes, sample_rate)

        if feat.rms_energy < 150.0:
            return AcousticSceneResult(
                scene_type="silence",
                confidence=0.95,
                features=feat,
                description="Quiet environment / silence detected.",
            )

        if feat.spectral_centroid_hz > 3500.0 and feat.rms_energy > 2000.0:
            return AcousticSceneResult(
                scene_type="alarm",
                confidence=0.92,
                features=feat,
                description="High-frequency alarm or siren detected.",
            )

        # Speech characteristics: high dynamic variation, balanced ZCR, silence between words
        if 0.05 <= feat.zero_crossing_rate <= 0.45 and feat.silence_ratio > 0.15:
            return AcousticSceneResult(
                scene_type="speech",
                confidence=0.90,
                features=feat,
                description="Human conversational speech detected.",
            )

        if feat.silence_ratio < 0.10 and feat.rms_energy > 500.0:
            return AcousticSceneResult(
                scene_type="music",
                confidence=0.85,
                features=feat,
                description="Continuous acoustic music or media playback detected.",
            )

        return AcousticSceneResult(
            scene_type="ambient_noise",
            confidence=0.80,
            features=feat,
            description="Ambient background noise detected.",
        )

    def summarize_meeting(self, transcript: str) -> MeetingSummary:
        """Analyze meeting transcript text to extract structured topics, decisions, and action items."""
        lines = [l.strip() for l in transcript.splitlines() if l.strip()]
        full_text = " ".join(lines)

        topics: list[str] = []
        decisions: list[str] = []
        action_items: list[ActionItem] = []

        # Extract topics
        topic_pattern = re.compile(r"(?:topic|agenda|discuss(?:ed|ing)?)\s*:\s*([^.\n]+)", re.IGNORECASE)
        for m in topic_pattern.finditer(full_text):
            topics.append(m.group(1).strip())

        # Extract decisions
        dec_pattern = re.compile(r"(?:agreed|decided|resolution|approved)\s*(?:that|to)?\s*([^.\n]+)", re.IGNORECASE)
        for m in dec_pattern.finditer(full_text):
            decisions.append(m.group(1).strip())

        # Extract action items
        # Pattern: [Name] will [Task] / Action: [Task] / TODO: [Task]
        action_pattern = re.compile(
            r"(?:action(?:\s+item)?|todo)\s*:\s*([^.\n]+)|([A-Z][a-z]+)\s+will\s+([^.\n]+)",
            re.IGNORECASE,
        )
        for m in action_pattern.finditer(full_text):
            if m.group(1):
                action_items.append(ActionItem(owner="Team", task=m.group(1).strip(), priority="medium"))
            elif m.group(2) and m.group(3):
                action_items.append(ActionItem(owner=m.group(2).strip(), task=m.group(3).strip(), priority="high"))

        if not topics:
            topics = ["Project Progression", "Executive Status Sync"]
        if not decisions:
            decisions = ["Proceed with staged roadmap milestones."]

        # Brief summary paragraph
        summary_text = (
            f"Meeting transcript summarized across {len(lines)} dialogue segments. "
            f"Key focus centered on {topics[0]}. {len(action_items)} action items recorded."
        )

        return MeetingSummary(
            title="Executive Meeting Notes",
            summary=summary_text,
            topics=topics,
            decisions=decisions,
            action_items=action_items,
        )
