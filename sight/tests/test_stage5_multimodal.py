"""Stage 5 Verification Tests: Advanced Multimodal Intelligence."""
import io
import math
import struct
from PIL import Image

from sight_core.multimodal_unified import (
    CameraContextService,
    ImageComparator,
    SpeakerIdentifier,
    UnifiedMultimodalReasoner,
    VideoAnalyzer,
)


def _png_bytes(color: tuple[int, int, int], size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_stage5_image_comparison_and_video_scene_changes():
    f1 = _png_bytes((0, 0, 0))
    f2 = _png_bytes((0, 0, 0))
    f3 = _png_bytes((255, 255, 255))

    comp = ImageComparator()
    same = comp.compare(f1, f2)
    diff = comp.compare(f1, f3)
    assert same.similarity_score == 1.0 and not same.changed_significantly
    assert diff.changed_significantly and diff.similarity_score < 0.1

    vid = VideoAnalyzer(comp).analyze_frames([f1, f2, f3], fps=2.0)
    assert vid.total_frames == 3
    assert len(vid.scene_changes) == 1
    assert vid.scene_changes[0].frame_index == 2


def test_stage5_camera_and_speaker_privacy_controls():
    cam = CameraContextService(consent_granted=False)
    try:
        cam.ingest_frame(_png_bytes((128, 128, 128)))
        assert False, "Should require consent"
    except PermissionError:
        pass

    cam.set_consent(True)
    frame = cam.ingest_frame(_png_bytes((128, 128, 128)))
    assert frame.width == 32 and cam.latest_context() is not None
    cam.set_consent(False)
    assert cam.latest_context() is None

    spk = SpeakerIdentifier(enabled=True)
    pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 300 * i / 16000))) for i in range(1600))
    spk.enroll("owner", pcm)
    assert spk.identify(pcm) == "owner"
    spk.purge("owner")
    assert spk.identify(pcm) is None


def test_stage5_unified_multimodal_reasoning():
    reasoner = UnifiedMultimodalReasoner()
    pcm = b"".join(struct.pack("<h", int(5000 * math.sin(2 * math.pi * 250 * i / 16000))) for i in range(1600))
    res = reasoner.reason(
        "Summarize all inputs",
        text_context="System diagram notes",
        images=[_png_bytes((10, 20, 30))],
        audio_pcm=pcm,
        video_frames=[_png_bytes((0, 0, 0)), _png_bytes((200, 200, 200))],
    )
    assert res.grounded is True
    assert set(res.modalities_used) == {"text", "image", "audio", "video"}
    assert len(res.observed_evidence) == 4
