"""Behavioral tests for the production project preparation workflow.

The synthetic fixture exercises serialized graph and dependency handling only;
it is not evidence of Modeler rendering, exported geometry, or visual quality.
"""

import gzip
import json
from pathlib import Path

import pytest

from dcc_mcp_speedtree.graph import SpeedTreeGraph
from dcc_mcp_speedtree.production import generate_project


def _generator(node_id, kind):
    return f'''<Generator Type="{kind}"><GUID>{node_id}</GUID><Name>{node_id}</Name>
      <Level>0</Level><Hidden>false</Hidden><Extra/>
      <Properties><SplineProperty><Name>Spine:Length:Absolute</Name>
      <Value>2</Value><Variance>0</Variance></SplineProperty></Properties></Generator>'''


def _link(source, target):
    return f"""<Link><GUID>link-{source}-{target}</GUID><SourceGUID>{source}</SourceGUID>
      <TargetGUID>{target}</TargetGUID><Name>link</Name><Hidden>false</Hidden>
      <Extra/><Properties/></Link>"""


@pytest.fixture
def production_input(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    texture = source_dir / "textures" / "leaf.png"
    texture.parent.mkdir()
    texture.write_bytes(b"synthetic texture dependency")
    source = source_dir / "reference.spm"
    generators = "".join(
        _generator(node_id, kind)
        for node_id, kind in [
            ("root", "Tree"),
            ("trunk", "Branch"),
            ("primary", "Branch"),
            ("leaves", "Leaf Mesh"),
        ]
    )
    links = "".join(
        _link(source_id, target_id)
        for source_id, target_id in [("root", "trunk"), ("trunk", "primary"), ("primary", "leaves")]
    )
    xml = f'<SpeedTree Version="8"><Generators>{generators}</Generators><Links>{links}</Links></SpeedTree>'
    source.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))
    operations = [
        {
            "op": "set_property",
            "node_id": "trunk",
            "name": "Spine:Length:Absolute",
            "value": 7.5,
        }
    ]
    brief = {
        "dependencies": ["textures/leaf.png"],
        "roles": {"trunk": ["trunk"], "primary_branches": ["primary"], "leaf_cards": ["leaves"]},
        "seed": 17,
        "budget": {"total_triangles": 2000, "card_triangles": 800},
    }
    return source, operations, brief


def test_generate_creates_separate_reopenable_project_with_dependencies_and_manifest(
    production_input, tmp_path
):
    source, operations, brief = production_input
    original = source.read_bytes()
    output_dir = tmp_path / "output"

    result = generate_project(source, output_dir, operations, brief)

    project = Path(result["project_path"])
    manifest_path = Path(result["manifest_path"])
    assert project.is_file() and project.is_relative_to(output_dir)
    assert manifest_path.is_file() and manifest_path.is_relative_to(output_dir)
    assert source.read_bytes() == original
    assert (output_dir / "textures" / "leaf.png").read_bytes() == b"synthetic texture dependency"
    graph = SpeedTreeGraph.load(project)
    assert graph.get_property("trunk", "Spine:Length:Absolute") == "7.5"
    assert SpeedTreeGraph.load(source).get_property("trunk", "Spine:Length:Absolute") == "2"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_text = json.dumps(manifest)
    assert (
        '"trunk"' in manifest_text and '"primary"' in manifest_text and '"leaves"' in manifest_text
    )
    assert '"17"' in manifest_text or " 17" in manifest_text
    assert (
        "not_run" in manifest_text
        or "unverified" in manifest_text
        or "not_verified" in manifest_text
    )


def test_missing_declared_dependency_fails_without_partial_output(production_input, tmp_path):
    source, operations, brief = production_input
    before = source.read_bytes()
    brief["dependencies"] = ["textures/missing.png"]
    output = tmp_path / "missing-output"
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert source.read_bytes() == before
    assert not output.exists() or not any(output.iterdir())


def test_texfilename_dependency_is_discovered_and_copied(production_input, tmp_path):
    source, operations, brief = production_input
    xml = gzip.decompress(source.read_bytes()).decode("utf-8")
    xml = xml.replace(
        "</SpeedTree>",
        "<Assets><Material><TexFilename>textures/leaf.png</TexFilename></Material></Assets>"
        "</SpeedTree>",
    )
    source.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))
    brief["dependencies"] = []
    output = tmp_path / "auto-dependency"

    result = generate_project(source, output, operations, brief)

    assert (output / "textures" / "leaf.png").read_bytes() == b"synthetic texture dependency"
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert any(item["path"] == "textures/leaf.png" for item in manifest["dependencies"])
    assert (
        SpeedTreeGraph.load(result["project_path"]).root.findtext("Assets/Material/TexFilename")
        == "textures/leaf.png"
    )


def test_missing_texfilename_fails_without_partial_output(production_input, tmp_path):
    source, operations, brief = production_input
    xml = gzip.decompress(source.read_bytes()).decode("utf-8")
    xml = xml.replace(
        "</SpeedTree>",
        "<Assets><Material><TexFilename>textures/missing.png</TexFilename></Material></Assets>"
        "</SpeedTree>",
    )
    source.write_bytes(gzip.compress(xml.encode("utf-8"), mtime=0))
    original = source.read_bytes()
    brief["dependencies"] = []
    output = tmp_path / "missing-auto-dependency"

    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert source.read_bytes() == original
    assert not output.exists() or not any(output.iterdir())


@pytest.mark.parametrize("dependency", ["../outside.png", "textures/../../outside.png"])
def test_dependency_escape_is_rejected(production_input, tmp_path, dependency):
    source, operations, brief = production_input
    (tmp_path / "outside.png").write_bytes(b"outside")
    brief["dependencies"] = [dependency]
    output = tmp_path / "escape-output"
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert not output.exists() or not any(output.iterdir())


def test_existing_output_is_not_overwritten(production_input, tmp_path):
    source, operations, brief = production_input
    output = tmp_path / "output"
    first = generate_project(source, output, operations, brief)
    project = Path(first["project_path"])
    manifest = Path(first["manifest_path"])
    before = (project.read_bytes(), manifest.read_bytes())
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert (project.read_bytes(), manifest.read_bytes()) == before


def test_unknown_role_generator_is_rejected_before_writing(production_input, tmp_path):
    source, operations, brief = production_input
    brief["roles"]["primary_branches"] = ["absent"]
    output = tmp_path / "invalid-role"
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert not output.exists() or not any(output.iterdir())


@pytest.mark.parametrize(
    "roles",
    [
        {"trunk": ["trunk"], "primary_branches": ["trunk"], "leaf_cards": ["leaves"]},
        {"trunk": ["leaves"], "primary_branches": ["primary"], "leaf_cards": ["trunk"]},
        {"trunk": ["primary"], "primary_branches": ["trunk"], "leaf_cards": ["leaves"]},
    ],
)
def test_duplicate_wrong_type_or_wrong_hierarchy_rejected(production_input, tmp_path, roles):
    source, operations, brief = production_input
    brief["roles"] = roles
    output = tmp_path / "invalid-structure"
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert not output.exists() or not any(output.iterdir())


def test_leaf_cards_must_descend_from_mapped_branches(production_input, tmp_path):
    source, operations, brief = production_input
    operations += [
        {"op": "disconnect", "source_id": "primary", "target_id": "leaves"},
        {"op": "connect", "source_id": "root", "target_id": "leaves"},
    ]
    output = tmp_path / "detached-leaf-cards"
    with pytest.raises((OSError, ValueError)):
        generate_project(source, output, operations, brief)
    assert not output.exists() or not any(output.iterdir())


def test_leaf_cards_directly_attached_to_trunk_are_accepted(production_input, tmp_path):
    source, operations, brief = production_input
    operations += [
        {"op": "disconnect", "source_id": "primary", "target_id": "leaves"},
        {"op": "connect", "source_id": "trunk", "target_id": "leaves"},
    ]
    result = generate_project(source, tmp_path / "trunk-cards", operations, brief)
    assert result["validation"]["graph_roles"] == "validated"


def test_repeated_fixed_operations_preserve_graph_semantics(production_input, tmp_path):
    source, operations, brief = production_input
    first = generate_project(source, tmp_path / "first", operations, brief)
    second = generate_project(source, tmp_path / "second", operations, brief)
    a = SpeedTreeGraph.load(first["project_path"])
    b = SpeedTreeGraph.load(second["project_path"])
    assert a.get_property("trunk", "Spine:Length:Absolute") == b.get_property(
        "trunk", "Spine:Length:Absolute"
    )
    assert [(g["id"], g["type"]) for g in a.inspect()["generators"]] == [
        (g["id"], g["type"]) for g in b.inspect()["generators"]
    ]
    assert {(e["source_id"], e["target_id"]) for e in a.inspect()["links"]} == {
        (e["source_id"], e["target_id"]) for e in b.inspect()["links"]
    }
