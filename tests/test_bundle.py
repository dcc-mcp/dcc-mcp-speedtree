from pathlib import Path

import pytest

from dcc_mcp_speedtree.bundle import material_dependencies


def test_material_map_keeps_semantics_without_source_paths(tmp_path):
    (tmp_path / "leaf.png").write_bytes(b"texture")
    (tmp_path / "Tree.stmat").write_text(
        '<Materials><Material Name="Leaf" TwoSided="1"><Map Name="Opacity" File="leaf.png" Source="private/source.png"/></Material></Materials>'
    )
    result = material_dependencies(tmp_path, tmp_path)
    assert result["status"] == "sidecar_verified"
    assert result["materials"][0]["two_sided"] is True
    assert result["materials"][0]["maps"] == [{"semantic": "Opacity", "path": "leaf.png"}]
    assert "private" not in str(result)


@pytest.mark.parametrize("name", ["missing.png", "../outside.png"])
def test_missing_or_escaping_dependencies_fail(tmp_path: Path, name):
    (tmp_path / "Tree.stmat").write_text(
        f'<Materials><Material><Map Name="Color" File="{name}"/></Material></Materials>'
    )
    with pytest.raises(ValueError):
        material_dependencies(tmp_path, tmp_path)
