import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from dcc_mcp_speedtree.production_preview import generate_diagnostic_views


@pytest.fixture
def preview_input(tmp_path, monkeypatch):
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"test stand-in; never executed")
    monkeypatch.setenv("DCC_MCP_BLENDER_EXECUTABLE", str(blender))
    obj = tmp_path / "tree.obj"
    obj.write_text("v 0 0 0\n", encoding="utf-8")
    return obj, tmp_path / "out", {"Bark": "wood", "Cards": "card"}


def _fake_renderer(command, **kwargs):
    del kwargs
    config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
    out = Path(config["output"])
    images = [
        f"{kind}_{view}{suffix}.png"
        for kind in ("bare", "full")
        for view in ("front", "back", "left", "right")
        for suffix in ("", "_mask")
    ]
    for name in images + ["card_closeup.png"]:
        Image.new("RGBA", (128, 128), (70, 120, 35, 255)).save(out / name)
    (out / "preview-manifest.json").write_text(json.dumps({"source": config["source_sha256"]}))
    return SimpleNamespace(returncode=0, stderr="", stdout="")


def test_new_output_includes_all_views_masks_closeup_and_hashes(preview_input, monkeypatch):
    monkeypatch.setattr("dcc_mcp_speedtree.production_preview.subprocess.run", _fake_renderer)
    obj, output, mapping = preview_input
    before = obj.read_bytes()
    result = generate_diagnostic_views(obj, output, mapping, 128)
    assert result["status"] == "diagnostic_previews_created"
    assert len(result["images"]) == 20
    assert (output / "bare_front_mask.png").exists()
    assert (output / "full_right.png").exists()
    assert (output / "card_closeup.png").exists()
    assert len(json.loads((output / "preview-manifest.json").read_text())["images"]) == 20
    assert Image.open(output / "full_contact_sheet.png").size == (256, 312)
    assert not (output / "request.json").exists()
    assert obj.read_bytes() == before
    with pytest.raises(ValueError, match="new directory"):
        generate_diagnostic_views(obj, output, mapping, 128)


@pytest.mark.parametrize("mapping", [{}, {"Bark": "wood"}, {"Bark": "trunk", "Cards": "card"}])
def test_rejects_incomplete_or_invalid_mapping(preview_input, mapping):
    obj, output, _ = preview_input
    with pytest.raises(ValueError):
        generate_diagnostic_views(obj, output, mapping, 128)
    assert not output.exists()


def test_failed_worker_leaves_no_candidate_directory(preview_input, monkeypatch):
    monkeypatch.setattr(
        "dcc_mcp_speedtree.production_preview.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="failed", stdout=""),
    )
    obj, output, mapping = preview_input
    with pytest.raises(RuntimeError, match="failed"):
        generate_diagnostic_views(obj, output, mapping, 128)
    assert not output.exists()


def test_change_to_source_during_render_is_rejected(preview_input, monkeypatch):
    obj, output, mapping = preview_input

    def changing_renderer(command, **kwargs):
        result = _fake_renderer(command, **kwargs)
        obj.write_text("changed", encoding="utf-8")
        return result

    monkeypatch.setattr("dcc_mcp_speedtree.production_preview.subprocess.run", changing_renderer)
    with pytest.raises(ValueError, match="changed"):
        generate_diagnostic_views(obj, output, mapping, 128)
    assert not output.exists()


def test_blender_respects_mtl_card_opacity_when_available(tmp_path, monkeypatch):
    """Optional integration test; Blender and Pillow are not package dependencies."""
    blender = os.environ.get("DCC_MCP_TEST_BLENDER")
    if not blender:
        pytest.skip("Set DCC_MCP_TEST_BLENDER to exercise actual headless rendering")
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("DCC_MCP_BLENDER_EXECUTABLE", blender)
    root = tmp_path
    mask = Image.new("L", (8, 8), 0)
    for x in range(4, 8):
        for y in range(8):
            mask.putpixel((x, y), 255)
    mask.save(root / "alpha.png")
    Image.new("RGB", (8, 8), (40, 150, 40)).save(root / "green.png")
    (root / "tree.mtl").write_text(
        "newmtl Bark\nKd 0.4 0.2 0.1\nnewmtl Cards\nmap_Kd green.png\nmap_d alpha.png\n",
        encoding="utf-8",
    )
    obj = root / "tree.obj"
    obj.write_text(
        "mtllib tree.mtl\nv -1 0 0\nv 1 0 0\nv 0 0 1\n"
        "v -1 0 1\nv 1 0 1\nv 1 0 3\nv -1 0 3\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl Bark\nf 1 2 3\nusemtl Cards\nf 4/1 5/2 6/3 7/4\n",
        encoding="utf-8",
    )
    generate_diagnostic_views(obj, root / "preview", {"Bark": "wood", "Cards": "card"}, 128)
    image = Image.open(root / "preview" / "card_closeup.png").convert("RGBA")
    # Both halves lie inside the projected plane. One is transparent because
    # map_d is connected to alpha, the other contains visible card pixels.
    assert image.getpixel((40, 64))[3] < 10
    assert image.getpixel((88, 64))[3] > 200
