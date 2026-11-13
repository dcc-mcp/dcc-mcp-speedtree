import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dcc_mcp_speedtree.reference_match import VIEWS, compare_reference_views


def fixture_views(tmp_path):
    reference = tmp_path / "four_views.png"
    candidate = tmp_path / "mask.png"
    chart = Image.new("RGB", (80, 80), (220, 220, 220))
    draw = ImageDraw.Draw(chart)
    for x, y in [(0, 0), (40, 0), (0, 40), (40, 40)]:
        draw.rectangle((x + 10, y + 8, x + 29, y + 30), fill=(0, 0, 0))
    chart.save(reference)
    mask = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(mask).rectangle((10, 8, 29, 30), fill=255)
    mask.save(candidate)
    crops = [[0, 0, 40, 40], [40, 0, 80, 40], [0, 40, 40, 80], [40, 40, 80, 80]]
    refs = {
        v: {"path": str(reference), "mode": "dark", "threshold": 128, "crop": crop}
        for v, crop in zip(VIEWS, crops)
    }
    candidates = {v: {"path": str(candidate), "mode": "light", "threshold": 128} for v in VIEWS}
    return refs, candidates


def test_four_views_crop_compare_and_overlay(tmp_path):
    refs, candidates = fixture_views(tmp_path)
    result = compare_reference_views(refs, candidates, tmp_path / "compare", canvas_size=128)
    assert result["status"] == "diagnostic_only"
    assert result["mean_iou"] == 1.0
    report = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert report["views"]["right"]["reference"]["crop"] == [40, 40, 80, 80]
    assert len(report["views"]["left"]["reference"]["sha256"]) == 64
    assert (tmp_path / "compare" / "front_overlay.png").is_file()
    with pytest.raises(ValueError, match="new directory"):
        compare_reference_views(refs, candidates, tmp_path / "compare")


def test_nonidentical_shapes_and_alpha(tmp_path):
    refs, candidates = fixture_views(tmp_path)
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 8, 29, 30), fill=(8, 200, 4, 255))
    path = tmp_path / "candidate_alpha.png"
    image.save(path)
    candidates["front"] = {"path": str(path), "mode": "alpha"}
    result = compare_reference_views(refs, candidates, tmp_path / "compare")
    assert 0 < result["views"]["front"]["iou"] < 1
    assert result["mean_iou"] < 1


def test_missing_direction_bad_crop_and_empty_mask_fail_without_output(tmp_path):
    refs, candidates = fixture_views(tmp_path)
    bad = refs.copy()
    del bad["right"]
    with pytest.raises(ValueError, match="front"):
        compare_reference_views(bad, candidates, tmp_path / "missing")
    bad = dict(refs)
    bad["front"] = {**refs["front"], "crop": [0, 0, 200, 200]}
    with pytest.raises(ValueError, match="Crop"):
        compare_reference_views(bad, candidates, tmp_path / "bad-crop")
    bad["front"] = {**refs["front"], "threshold": 1, "crop": [0, 0, 5, 5]}
    with pytest.raises(ValueError, match="No foreground"):
        compare_reference_views(bad, candidates, tmp_path / "empty")
    assert not (tmp_path / "empty").exists()
