import gzip
import runpy
from pathlib import Path

import pytest

import dcc_mcp_speedtree.production_bare as bare_module
from dcc_mcp_speedtree.graph import GraphError, SpeedTreeGraph
from dcc_mcp_speedtree.production_bare import make_bare_copy


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


def test_rejects_nonsibling_to_preserve_relative_assets(tmp_path):
    source = fixture(tmp_path / "tree.spm")
    other = tmp_path / "other"
    other.mkdir()
    target = other / "bare.spm"
    with pytest.raises(ValueError, match="sibling"):
        make_bare_copy(source, target)
    assert not target.exists()


def test_rejects_dangling_output_symlink(tmp_path):
    source = fixture(tmp_path / "tree.spm")
    target = tmp_path / "bare.spm"
    try:
        target.symlink_to(tmp_path / "missing.spm")
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this host")
    with pytest.raises(ValueError, match="symbolic link"):
        make_bare_copy(source, target)
    assert target.is_symlink()
    assert not (tmp_path / "missing.spm").exists()


def test_preserves_existing_output_created_during_publication(tmp_path, monkeypatch):
    source = fixture(tmp_path / "tree.spm")
    target = tmp_path / "bare.spm"
    real_link = bare_module.os.link

    def raced_link(stage, destination):
        target.write_bytes(b"other writer")
        real_link(stage, destination)

    monkeypatch.setattr(bare_module.os, "link", raced_link)
    with pytest.raises(FileExistsError):
        make_bare_copy(source, target)
    assert target.read_bytes() == b"other writer"


def test_detects_source_changed_after_staging_before_publication(tmp_path, monkeypatch):
    source = fixture(tmp_path / "tree.spm")
    target = tmp_path / "bare.spm"
    real_save = SpeedTreeGraph.save

    def modified_save(graph, destination):
        saved = real_save(graph, destination)
        source.write_bytes(b"externally modified")
        return saved

    monkeypatch.setattr(SpeedTreeGraph, "save", modified_save)
    with pytest.raises(GraphError, match="Source changed during bare project preparation"):
        make_bare_copy(source, target)
    assert not target.exists()


def test_skill_entry_reports_auditable_sibling_candidate(tmp_path):
    source = fixture(tmp_path / "tree.spm")
    target = tmp_path / "bare.spm"
    script = (
        Path(__file__).resolve().parents[1]
        / "src/dcc_mcp_speedtree/skills/speedtree-production/scripts/prepare_bare_project.py"
    )
    result = runpy.run_path(str(script))["main"](source_path=str(source), output_path=str(target))
    assert result["success"]
    assert result["context"]["status"] == "bare_project_prepared"
    assert result["context"]["removed_ids"] == ["leaf", "twig"]
    assert len(result["context"]["full_sha256"]) == 64
    assert len(result["context"]["bare_sha256"]) == 64
