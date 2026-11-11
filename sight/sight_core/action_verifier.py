"""Visual action verification and UI state diffing engine.

Compares pre-action and post-action display captures to verify whether
a computer actuation produced the intended visual state change.
Generates bounding boxes of changed regions and change metrics.
"""
from __future__ import annotations

import io
import math
from typing import Tuple

from PIL import Image, ImageChops, ImageDraw
from pydantic import Field

from .tools import StrictModel
from .vision import BoundingBox


class VisualDelta(StrictModel):
    has_changed: bool
    changed_pixels: int
    total_pixels: int
    change_percentage: float
    bounding_box: BoundingBox | None = None
    diff_summary: str


class ActionVerifier:
    """Verifies UI state transitions by computing perceptual visual diffs."""

    def __init__(self, tolerance: int = 20, min_change_pixels: int = 50):
        self.tolerance = tolerance
        self.min_change_pixels = min_change_pixels

    def compare_images(
        self,
        pre_image_bytes: bytes,
        post_image_bytes: bytes,
        target_roi: BoundingBox | None = None,
    ) -> VisualDelta:
        """Compares two image byte buffers and returns visual change metrics."""
        if not pre_image_bytes or not post_image_bytes:
            return VisualDelta(
                has_changed=False,
                changed_pixels=0,
                total_pixels=0,
                change_percentage=0.0,
                bounding_box=None,
                diff_summary="Missing image buffers for comparison",
            )

        with Image.open(io.BytesIO(pre_image_bytes)) as img1, Image.open(io.BytesIO(post_image_bytes)) as img2:
            im1 = img1.convert("RGB")
            im2 = img2.convert("RGB")

            # Align dimensions if resolution shifted
            if im1.size != im2.size:
                im2 = im2.resize(im1.size, Image.Resampling.LANCZOS)

            width, height = im1.size
            total_pixels = width * height

            # Crop to Region of Interest if specified
            if target_roi:
                crop_box = (
                    max(0, target_roi.left),
                    max(0, target_roi.top),
                    min(width, target_roi.right),
                    min(height, target_roi.bottom),
                )
                if crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]:
                    im1 = im1.crop(crop_box)
                    im2 = im2.crop(crop_box)
                    width, height = im1.size
                    total_pixels = width * height

            diff = ImageChops.difference(im1, im2)

            # Apply tolerance threshold: set pixels below tolerance to black
            diff_gray = diff.convert("L")
            # Point evaluation: anything below tolerance becomes 0, else 255
            diff_mask = diff_gray.point(lambda p: 255 if p > self.tolerance else 0)

            # Extract bounding box of changed area
            bbox = diff_mask.getbbox()
            changed_pixels = 0
            if bbox:
                # Count non-zero pixels in mask
                hist = diff_mask.histogram()
                changed_pixels = hist[255] if len(hist) > 255 else 0

            has_changed = changed_pixels >= self.min_change_pixels
            change_percentage = round((changed_pixels / total_pixels) * 100.0, 3) if total_pixels > 0 else 0.0

            result_bbox = None
            if bbox and has_changed:
                offset_x = target_roi.left if target_roi else 0
                offset_y = target_roi.top if target_roi else 0
                result_bbox = BoundingBox(
                    left=bbox[0] + offset_x,
                    top=bbox[1] + offset_y,
                    width=max(1, bbox[2] - bbox[0]),
                    height=max(1, bbox[3] - bbox[1]),
                )

            summary = (
                f"Observable UI change detected: {changed_pixels} pixels ({change_percentage}%) modified."
                if has_changed
                else f"No significant UI change detected ({changed_pixels} pixels changed, below threshold {self.min_change_pixels})."
            )

            return VisualDelta(
                has_changed=has_changed,
                changed_pixels=changed_pixels,
                total_pixels=total_pixels,
                change_percentage=change_percentage,
                bounding_box=result_bbox,
                diff_summary=summary,
            )

    def generate_diff_overlay(
        self,
        pre_image_bytes: bytes,
        post_image_bytes: bytes,
    ) -> bytes:
        """Produces a JPEG image highlighting the changed regions with a red contour."""
        with Image.open(io.BytesIO(pre_image_bytes)) as img1, Image.open(io.BytesIO(post_image_bytes)) as img2:
            im1 = img1.convert("RGB")
            im2 = img2.convert("RGB")
            if im1.size != im2.size:
                im2 = im2.resize(im1.size, Image.Resampling.LANCZOS)

            diff = ImageChops.difference(im1, im2)
            diff_mask = diff.convert("L").point(lambda p: 255 if p > self.tolerance else 0)
            bbox = diff_mask.getbbox()

            overlay = im2.copy()
            if bbox:
                draw = ImageDraw.Draw(overlay)
                draw.rectangle(bbox, outline=(239, 68, 68), width=3)
                draw.text((bbox[0] + 5, max(0, bbox[1] - 15)), "[STATE CHANGED]", fill=(239, 68, 68))

            buf = io.BytesIO()
            overlay.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
