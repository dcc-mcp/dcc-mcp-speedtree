import gzip
import runpy
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dcc_mcp_speedtree.graph import SpeedTreeGraph
from dcc_mcp_speedtree.reference_fit_modeler import make_bare_copy


def fixture(path, card_parent_of_wood=False):
    def node(name, kind):
        return f'<Generator Type="{kind}"><GUID>{name}</GUID><Name>{name}</Name></Generator>'

    def link(a, b):
        return f"<Link><GUID>{a}-{b}</GUID><SourceGUID>{a}</SourceGUID><TargetGUID>{b}</TargetGUID></Link>"

    nodes = node("root", "Tree") + node("trunk", "Branch") + node("leaf", "Leaf Mesh")
    nodes += node("twig", "Frond")
    links = link("root", "trunk") + link("trunk", "leaf") + link("leaf", "twig")
    if card_parent_of_wood:
        nodes += node("wood", "Branch")
        links += link("twig", "wood")
    path.write_bytes(
        gzip.compress(
            f'<SpeedTree Version="8"><Generators>{nodes}</Generators><Links>{links}</Links></SpeedTree>'.encode()
        )
    )
    return path


def test_removes_only_card_generators_preserving_source(tmp_path):
    source = fixture(tmp_path / "tree.spm")
    before = source.read_bytes()
    target = tmp_path / "bare.spm"
    receipt = make_bare_copy(source, target)
    assert receipt["removed_ids"] == ["leaf", "twig"]
    assert source.read_bytes() == before
    assert {n["id"] for n in SpeedTreeGraph.load(target).inspect()["generators"]} == {
        "root",
        "trunk",
    }
    with pytest.raises(FileExistsError):
        make_bare_copy(source, target)


def test_rejects_wood_descendant_without_writing(tmp_path):
    source = fixture(tmp_path / "tree.spm", card_parent_of_wood=True)
    target = tmp_path / "bare.spm"
    with pytest.raises(ValueError, match="non-card child"):
        make_bare_copy(source, target)
    assert not target.exists()


def test_mcp_entry_returns_error_when_structure_fails_before_modeler(tmp_path):
    source = tmp_path / "tree.spm"
    source.write_text(
        '<SpeedTree Version="8"><Generators>'
        '<Generator Type="Tree"><GUID>root</GUID><Name>root</Name><Properties/></Generator>'
        '<Generator Type="Branch"><GUID>trunk</GUID><Name>trunk</Name><Properties>'
        "<Property><Name>Length</Name><Value>2</Value></Property></Properties></Generator>"
        "</Generators><Links><Link><GUID>link</GUID><SourceGUID>root</SourceGUID>"
        "<TargetGUID>trunk</TargetGUID></Link></Links></SpeedTree>",
        encoding="utf-8",
    )
    mask = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(mask).rectangle((20, 10, 40, 50), fill=255)
    mask_path = tmp_path / "mask.png"
    mask.save(mask_path)
    references = {
        view: {"path": str(mask_path), "mode": "light"}
        for view in ("front", "back", "left", "right")
    }
    preset = tmp_path / "preset.ini"
    preset.write_text("[General]\nType=VFX\n", encoding="utf-8")
    script = (
        Path(__file__).resolve().parents[1]
        / "src/dcc_mcp_speedtree/skills/speedtree-production/scripts/fit_reference_modeler.py"
    )
    entry = runpy.run_path(str(script))["main"]
    result = entry(
        source_path=str(source),
        output_dir=str(tmp_path / "output"),
        parameters=[{"node_id": "trunk", "name": "Length", "initial": 2, "values": [2]}],
        references=references,
        preset_path=str(preset),
        material_categories={"bark": "wood", "leaf": "card"},
        brief={},
        trunk_id="trunk",
        max_evaluations=1,
    )
    assert not result["success"]
    assert result["context"]["status"] == "no_eligible_candidate"
    assert result["context"]["result"]["trials"][0]["status"] == "structure_failed"
