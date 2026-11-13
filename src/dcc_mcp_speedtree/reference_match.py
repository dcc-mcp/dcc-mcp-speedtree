"""Reproducible silhouette comparison; this is not artistic acceptance."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

VIEWS = ("front", "back", "left", "right")
MAX_IMAGE_PIXELS = 40_000_000


def _read_mask(spec):
    if not isinstance(spec, dict) or set(spec) - {"path", "mode", "threshold", "crop"}:
        raise ValueError("Each view requires a path, mode, optional threshold and crop")
    path = Path(spec["path"]).expanduser().resolve(strict=True)
    mode = spec.get("mode")
    threshold = spec.get("threshold", 128)
    if mode not in {"alpha", "dark", "light"}:
        raise ValueError("Mask mode must explicitly be alpha, dark, or light")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 255:
        raise ValueError("Mask threshold must be an integer between 1 and 255")
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("Image file exceeds size limit")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    with Image.open(io.BytesIO(content)) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("Image exceeds pixel limit")
        image.load()
        crop = spec.get("crop")
        if crop is not None:
            if (
                not isinstance(crop, list)
                or len(crop) != 4
                or any(isinstance(v, bool) or not isinstance(v, int) for v in crop)
                or not (0 <= crop[0] < crop[2] <= image.width)
                or not (0 <= crop[1] < crop[3] <= image.height)
            ):
                raise ValueError("Crop must be [left, top, right, bottom] inside the image")
            image = image.crop(tuple(crop))
        if mode == "alpha":
            if "A" not in image.getbands() and "transparency" not in image.info:
                raise ValueError("Alpha mode requires an image with transparency")
            channel = image.convert("RGBA").getchannel("A")
            mask = channel.point(lambda n: 255 if n >= threshold else 0)
        else:
            channel = image.convert("L")
            if mode == "dark":
                mask = channel.point(lambda n: 255 if n < threshold else 0)
            else:
                mask = channel.point(lambda n: 255 if n >= threshold else 0)
    box = mask.getbbox()
    if not box:
        raise ValueError(f"No foreground pixels in {path}")
    if box == (0, 0, mask.width, mask.height) and mask.histogram()[255] == mask.width * mask.height:
        raise ValueError(f"Mask contains only foreground pixels in {path}")
    return mask, {
        "path": str(path),
        "sha256": digest,
        "mode": mode,
        "threshold": threshold,
        "crop": crop,
        "foreground_bbox": list(box),
        "crop_size": list(mask.size),
    }


def _normalize(mask, size):
    box = mask.getbbox()
    foreground = mask.crop(box)
    limit = int(size * 0.9)
    scale = min(limit / foreground.width, limit / foreground.height)
    scaled_size = (
        max(1, round(foreground.width * scale)),
        max(1, round(foreground.height * scale)),
    )
    scaled = foreground.resize(scaled_size, resample=Image.Resampling.NEAREST)
    canvas = Image.new("L", (size, size), 0)
    offset = ((size - scaled.width) // 2, size - int(size * 0.05) - scaled.height)
    canvas.paste(scaled, offset)
    return canvas, {"size": list(scaled_size), "offset": list(offset), "scale": scale}


def compare_reference_views(references, candidates, output_dir, canvas_size=512):
    """Compare four explicitly oriented silhouette masks on normalized canvases.

    Independently normalizing bounding boxes removes absolute dimensions and
    position. IoU is diagnostic, not a fitted tree or a visual quality score.
    """
    if not isinstance(references, dict) or set(references) != set(VIEWS):
        raise ValueError("references must contain front, back, left and right")
    if not isinstance(candidates, dict) or set(candidates) != set(VIEWS):
        raise ValueError("candidates must contain front, back, left and right")
    if (
        isinstance(canvas_size, bool)
        or not isinstance(canvas_size, int)
        or not 64 <= canvas_size <= 2048
    ):
        raise ValueError("canvas_size must be an integer in 64..2048")
    output = Path(output_dir).expanduser().resolve()
    if output.exists() or not output.parent.is_dir():
        raise ValueError("Output must be a new directory whose parent exists")
    processed = {}
    for view in VIEWS:
        ref, ref_info = _read_mask(references[view])
        candidate, candidate_info = _read_mask(candidates[view])
        ref, ref_transform = _normalize(ref, canvas_size)
        candidate, candidate_transform = _normalize(candidate, canvas_size)
        intersection = ImageChops.darker(ref, candidate).histogram()[255]
        union = ImageChops.lighter(ref, candidate).histogram()[255]
        ref_area = ref.histogram()[255]
        candidate_area = candidate.histogram()[255]
        processed[view] = {
            "reference": ref_info,
            "candidate": candidate_info,
            "reference_transform": ref_transform,
            "candidate_transform": candidate_transform,
            "intersection_pixels": intersection,
            "union_pixels": union,
            "reference_pixels": ref_area,
            "candidate_pixels": candidate_area,
            "iou": intersection / union,
            "dice": 2 * intersection / (ref_area + candidate_area),
            "_ref": ref,
            "_candidate": candidate,
        }
    with tempfile.TemporaryDirectory(prefix=".speedtree-compare-", dir=output.parent) as temp:
        stage = Path(temp) / "comparison"
        stage.mkdir()
        for view, data in processed.items():
            ref, candidate = data.pop("_ref"), data.pop("_candidate")
            # Red = reference-only, blue = candidate-only, white = overlap.
            overlap = ImageChops.darker(ref, candidate)
            overlay = Image.merge("RGB", (ref, overlap, candidate))
            overlay.save(stage / f"{view}_overlay.png")
            data["overlay"] = f"{view}_overlay.png"
        report = {
            "schema": "speedtree.reference-silhouette-comparison.v1",
            "status": "diagnostic_only",
            "canvas_size": canvas_size,
            "mean_iou": sum(item["iou"] for item in processed.values()) / len(VIEWS),
            "views": processed,
            "limitations": [
                "View names, segmentation, crop and camera correspondence are supplied by the user.",
                "Independent per-view normalization removes absolute size and position.",
                "Silhouette IoU does not measure branch topology, materials or leaf-card quality.",
                "No parameters were fitted and no artistic acceptance was performed.",
            ],
        }
        (stage / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        stage.rename(output)
    return {
        "status": "diagnostic_only",
        "mean_iou": report["mean_iou"],
        "manifest_path": str(output / "comparison.json"),
        "views": report["views"],
    }
