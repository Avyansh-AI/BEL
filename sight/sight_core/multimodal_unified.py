"""Stage 5: Unified Multimodal Intelligence for BEL.

Extends BEL's MultimodalVLM, DocumentParser, and AcousticIntelligence with:
- Image comparison (perceptual & pixel-level similarity + delta)
- Video intelligence (frame sequence analysis, scene-change detection, temporal summary)
- Camera intelligence (permission-gated frame ingestion & visual context)
- Privacy-controlled speaker identification (local-only voiceprint matching & purge)
- Unified cross-modal reasoning grounded in observed evidence
"""
from __future__ import annotations

import io
import math
import struct
import time
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageStat
from pydantic import BaseModel, ConfigDict, Field

from .acoustic_intelligence import AcousticIntelligence
from .multimodal_vlm import MultimodalVLM


class ImageComparisonResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    same_dimensions: bool
    similarity_score: float  # 0.0 to 1.0
    mean_diff: float
    changed_significantly: bool


class SceneChangeEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    frame_index: int
    timestamp_sec: float
    diff_score: float
    description: str


class VideoSummaryResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    total_frames: int
    fps: float
    duration_sec: float
    scene_changes: list[SceneChangeEvent] = Field(default_factory=list)
    summary: str


class CameraContextFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")
    timestamp: float
    width: int
    height: int
    mean_brightness: float
    summary: str


class UnifiedReasoningResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    answer: str
    modalities_used: list[str] = Field(default_factory=list)
    observed_evidence: list[dict[str, Any]] = Field(default_factory=list)
    grounded: bool = True


class ImageComparator:
    """Compares two images for visual similarity and structural changes."""

    def compare(self, img_a_bytes: bytes, img_b_bytes: bytes, *, threshold: float = 0.05) -> ImageComparisonResult:
        with Image.open(io.BytesIO(img_a_bytes)) as ia, Image.open(io.BytesIO(img_b_bytes)) as ib:
            a = ia.convert("RGB")
            b = ib.convert("RGB")
            same_dims = a.size == b.size
            if not same_dims:
                b = b.resize(a.size)
            diff = ImageChops.difference(a, b)
            stat = ImageStat.Stat(diff)
            mean_diff = sum(stat.mean) / (len(stat.mean) * 255.0)
            similarity = max(0.0, min(1.0, 1.0 - mean_diff))
            return ImageComparisonResult(
                same_dimensions=same_dims,
                similarity_score=round(similarity, 4),
                mean_diff=round(mean_diff, 4),
                changed_significantly=mean_diff >= threshold,
            )


class VideoAnalyzer:
    """Analyzes video frame sequences for scene changes and temporal events."""

    def __init__(self, comparator: ImageComparator | None = None) -> None:
        self.comparator = comparator or ImageComparator()

    def analyze_frames(
        self,
        frames: Sequence[bytes],
        *,
        fps: float = 1.0,
        scene_threshold: float = 0.12,
    ) -> VideoSummaryResult:
        if not frames:
            return VideoSummaryResult(total_frames=0, fps=fps, duration_sec=0.0, summary="No video frames provided.")

        changes: list[SceneChangeEvent] = []
        for idx in range(1, len(frames)):
            comp = self.comparator.compare(frames[idx - 1], frames[idx], threshold=scene_threshold)
            if comp.changed_significantly:
                ts = round(idx / max(fps, 0.1), 2)
                changes.append(
                    SceneChangeEvent(
                        frame_index=idx,
                        timestamp_sec=ts,
                        diff_score=comp.mean_diff,
                        description=f"Scene transition detected at {ts}s (delta={comp.mean_diff:.3f})",
                    )
                )

        duration = round(len(frames) / max(fps, 0.1), 2)
        summary = (
            f"Analyzed {len(frames)} frames ({duration}s at {fps} fps); "
            f"detected {len(changes)} scene change(s)."
        )
        return VideoSummaryResult(
            total_frames=len(frames),
            fps=fps,
            duration_sec=duration,
            scene_changes=changes,
            summary=summary,
        )


class CameraContextService:
    """Permission-gated camera frame ingestion for computer-use and visual context."""

    def __init__(self, *, consent_granted: bool = False) -> None:
        self.consent_granted = consent_granted
        self._latest_frame: CameraContextFrame | None = None

    def set_consent(self, granted: bool) -> None:
        self.consent_granted = granted
        if not granted:
            self._latest_frame = None

    def ingest_frame(self, image_bytes: bytes) -> CameraContextFrame:
        if not self.consent_granted:
            raise PermissionError("Camera access requires explicit user consent")
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            stat = ImageStat.Stat(rgb)
            brightness = round(sum(stat.mean) / 3.0, 2)
        frame = CameraContextFrame(
            timestamp=time.time(),
            width=w,
            height=h,
            mean_brightness=brightness,
            summary=f"Camera frame {w}x{h} (brightness={brightness})",
        )
        self._latest_frame = frame
        return frame

    def latest_context(self) -> CameraContextFrame | None:
        return self._latest_frame


class SpeakerIdentifier:
    """Local-only speaker identification with explicit opt-in and instant purge controls."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._profiles: dict[str, tuple[float, float]] = {}
        self._acoustic = AcousticIntelligence()

    def _signature(self, pcm_bytes: bytes, sample_rate: int = 16000) -> tuple[float, float]:
        feats = self._acoustic.extract_features(pcm_bytes, sample_rate=sample_rate)
        return (feats.zero_crossing_rate, feats.spectral_centroid_hz)

    def enroll(self, speaker_id: str, pcm_bytes: bytes, sample_rate: int = 16000) -> None:
        if not self.enabled:
            raise PermissionError("Speaker identification is disabled by privacy policy")
        self._profiles[speaker_id] = self._signature(pcm_bytes, sample_rate)

    def identify(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str | None:
        if not self.enabled or not self._profiles:
            return None
        zcr, centroid = self._signature(pcm_bytes, sample_rate)
        best_id: str | None = None
        best_dist = float("inf")
        for sid, (p_zcr, p_cent) in self._profiles.items():
            dist = math.hypot(zcr - p_zcr, (centroid - p_cent) / 1000.0)
            if dist < best_dist:
                best_dist = dist
                best_id = sid
        return best_id if best_dist < 1.5 else None

    def purge(self, speaker_id: str | None = None) -> None:
        if speaker_id is None:
            self._profiles.clear()
        else:
            self._profiles.pop(speaker_id, None)


class UnifiedMultimodalReasoner:
    """Combines text, image, audio, and video context into grounded cross-modal answers."""

    def __init__(
        self,
        *,
        vlm: MultimodalVLM | None = None,
        acoustic: AcousticIntelligence | None = None,
        video: VideoAnalyzer | None = None,
    ) -> None:
        self.vlm = vlm or MultimodalVLM()
        self.acoustic = acoustic or AcousticIntelligence()
        self.video = video or VideoAnalyzer()
        self._history: list[dict[str, Any]] = []

    def reason(
        self,
        query: str,
        *,
        text_context: str | None = None,
        images: Sequence[bytes] | None = None,
        audio_pcm: bytes | None = None,
        video_frames: Sequence[bytes] | None = None,
    ) -> UnifiedReasoningResult:
        modalities: list[str] = ["text"]
        evidence: list[dict[str, Any]] = []

        if text_context:
            evidence.append({"modality": "text", "chars": len(text_context), "snippet": text_context[:160]})

        if images:
            modalities.append("image")
            for idx, img_bytes in enumerate(images):
                props = self.vlm.inspect_image_properties(img_bytes)
                evidence.append({"modality": "image", "index": idx, "properties": props})

        if audio_pcm:
            modalities.append("audio")
            scene = self.acoustic.classify_scene(audio_pcm)
            evidence.append({"modality": "audio", "scene_type": scene.scene_type, "rms": scene.features.rms_energy})

        if video_frames:
            modalities.append("video")
            v_res = self.video.analyze_frames(video_frames)
            evidence.append({"modality": "video", "total_frames": v_res.total_frames, "scene_changes": len(v_res.scene_changes)})

        grounded = len(evidence) > 0
        answer = (
            f"Cross-modal synthesis for '{query}' across {modalities}: "
            f"{len(evidence)} observed evidence item(s) collected."
        )
        self._history.append({"query": query, "modalities": modalities, "evidence_count": len(evidence)})
        return UnifiedReasoningResult(
            answer=answer,
            modalities_used=modalities,
            observed_evidence=evidence,
            grounded=grounded,
        )
