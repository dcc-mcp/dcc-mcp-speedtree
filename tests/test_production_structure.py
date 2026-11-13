import gzip

import pytest

from dcc_mcp_speedtree.production_structure import validate_branch_structure


def fixture(path, *, deep=False, detached=False):
    def node(name, kind):
        return f'<Generator Type="{kind}"><GUID>{name}</GUID><Name>{name}</Name></Generator>'

    def link(a, b):
        return f"<Link><GUID>{a}-{b}</GUID><SourceGUID>{a}</SourceGUID><TargetGUID>{b}</TargetGUID></Link>"

    nodes = node("root", "Tree") + node("trunk", "Branch") + node("primary", "Branch")
    nodes += node("secondary", "Branch") + node("leaf", "Leaf Mesh")
    edges = link("root", "trunk") + link("trunk", "primary")
    edges += link("primary", "secondary") + link("secondary", "leaf")
    if deep:
        nodes += node("deep", "Branch")
        edges += link("secondary", "deep")
    if detached:
        nodes += node("orphan", "Branch")
    path.write_bytes(
        gzip.compress(
            f'<SpeedTree Version="8"><Generators>{nodes}</Generators><Links>{edges}</Links></SpeedTree>'.encode()
        )
    )
    return path


def test_production_structure_detects_deep_and_detached(tmp_path):
    source = fixture(tmp_path / "source.spm", deep=True, detached=True)
    report = validate_branch_structure(source, "trunk", 2, 1)
    assert report["status"] == "failed"
    assert report["primary_generators"] == report["secondary_generators"] == 1
    assert report["deeper_branches"][0]["id"] == "deep"
    assert report["disconnected_branches"] == ["orphan"]


def test_branch_limits_and_types(tmp_path):
    source = fixture(tmp_path / "source.spm")
    assert validate_branch_structure(source, "trunk")["status"] == "passed"
    assert validate_branch_structure(source, "trunk", max_secondary=0)["status"] == "failed"
    with pytest.raises(ValueError):
        validate_branch_structure(source, "leaf")
    with pytest.raises(ValueError):
        validate_branch_structure(source, "trunk", max_branch_order=True)


def test_disconnected_designated_trunk_never_passes(tmp_path):
    path = tmp_path / "tree.spm"
    xml = '<SpeedTree Version="8"><Generators><Generator Type="Tree"><GUID>root</GUID></Generator><Generator Type="Branch"><GUID>trunk</GUID></Generator></Generators></SpeedTree>'
    path.write_bytes(gzip.compress(xml.encode()))
    report = validate_branch_structure(path, "trunk")
    assert report["status"] == "failed"
    assert any("not connected" in error for error in report["failures"])
