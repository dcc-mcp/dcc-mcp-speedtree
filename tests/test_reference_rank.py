import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dcc_mcp_speedtree.reference_match import VIEWS
from dcc_mcp_speedtree.reference_rank import _publish_no_replace, rank_reference_candidates


@pytest.fixture
def masks(tmp_path):
    rectangle = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(rectangle).rectangle((9, 8, 30, 31), fill=255)
    rect_path = tmp_path / "rectangle.png"
    rectangle.save(rect_path)
    ellipse = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(ellipse).ellipse((9, 8, 30, 31), fill=255)
    ellipse_path = tmp_path / "ellipse.png"
    ellipse.save(ellipse_path)
    refs = {v: {"path": str(rect_path), "mode": "light"} for v in VIEWS}
    good = {v: {"path": str(rect_path), "mode": "light"} for v in VIEWS}
    other = {v: {"path": str(ellipse_path), "mode": "light"} for v in VIEWS}
    return refs, good, other


def test_rank_outputs_comparisons_overlays_and_auditable_manifest(tmp_path, masks):
    refs, good, other = masks
    output = tmp_path / "ranked"
    result = rank_reference_candidates(refs, {"second": other, "first": good}, output, 128)
    assert result["status"] == "diagnostic_only"
    assert [item["candidate"] for item in result["candidates"]] == ["first", "second"]
    assert [item["rank"] for item in result["candidates"]] == [1, 2]
    assert result["candidates"][0]["mean_iou"] == 1.0
    assert 0 < result["candidates"][1]["mean_iou"] < 1
    report = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert report["reference_sha256_by_view"].keys() == set(VIEWS)
    for candidate in report["candidates"]:
        manifest = output / candidate["comparison_manifest"]
        assert manifest.is_file()
        assert json.loads(manifest.read_text(encoding="utf-8"))["mean_iou"] == candidate["mean_iou"]
        assert all((output / relative).is_file() for relative in candidate["overlays"].values())


def test_ties_are_sorted_by_case_insensitive_key(tmp_path, masks):
    refs, good, _ = masks
    result = rank_reference_candidates(refs, {"zulu": good, "Alpha": good}, tmp_path / "ranked")
    assert [item["candidate"] for item in result["candidates"]] == ["Alpha", "zulu"]
    assert result["candidates"][0]["mean_iou"] == result["candidates"][1]["mean_iou"]


def test_missing_or_invalid_candidate_aborts_without_partial_output(tmp_path, masks):
    refs, good, other = masks
    broken = dict(other)
    broken["front"] = {"path": str(tmp_path / "missing.png"), "mode": "light"}
    output = tmp_path / "ranked"
    with pytest.raises(FileNotFoundError):
        rank_reference_candidates(refs, {"a_good": good, "z_bad": broken}, output)
    assert not output.exists()
    broken = dict(other)
    del broken["back"]
    with pytest.raises(ValueError, match="front, back"):
        rank_reference_candidates(refs, {"good": good, "bad": broken}, output)
    assert not output.exists()


@pytest.mark.parametrize("key", ["../outside", "a/b", "a\\b", ".", "..", "C:", "NUL", "COM1", ""])
def test_path_traversal_and_reserved_names_rejected(tmp_path, masks, key):
    refs, good, _ = masks
    with pytest.raises(ValueError):
        rank_reference_candidates(refs, {key: good}, tmp_path / "ranked")
    assert not (tmp_path / "ranked").exists()


def test_case_collisions_and_existing_output_rejected(tmp_path, masks):
    refs, good, _ = masks
    output = tmp_path / "ranked"
    with pytest.raises(ValueError, match="distinct"):
        rank_reference_candidates(refs, {"TREE": good, "tree": good}, output)
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("untouched")
    with pytest.raises(ValueError, match="new directory"):
        rank_reference_candidates(refs, {"tree": good}, output)
    assert sentinel.read_text() == "untouched"


def test_publication_cannot_replace_existing_empty_directory(tmp_path):
    staged = tmp_path / "staged"
    output = tmp_path / "output"
    staged.mkdir()
    output.mkdir()
    (staged / "data").write_text("candidate")
    with pytest.raises(OSError):
        _publish_no_replace(staged, output)
    assert staged.is_dir()
    assert list(output.iterdir()) == []


def test_dangling_output_symlink_is_not_followed(tmp_path, masks):
    refs, good, _ = masks
    output = tmp_path / "ranked"
    target = tmp_path / "does-not-exist"
    try:
        output.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation unavailable")
    with pytest.raises(ValueError, match="new directory"):
        rank_reference_candidates(refs, {"tree": good}, output)
    assert output.is_symlink()
    assert not target.exists()
