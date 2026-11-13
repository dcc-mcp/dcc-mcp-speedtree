import pytest

from dcc_mcp_speedtree.production_mapping import validate_material_bare

VERTICES = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 2 0 0\nv 3 0 0\nv 2 1 0\n"


def write_obj(path, lines):
    path.write_text(VERTICES + lines, encoding="utf-8")
    return path


def test_wood_material_geometry_matches_bare_with_independent_card_faces(tmp_path):
    full = write_obj(tmp_path / "full.obj", "usemtl bark\nf 1 2 3\nusemtl leaf\nf 4 5 6\n")
    bare = write_obj(tmp_path / "bare.obj", "usemtl shared_atlas\nf 1 2 3\n")
    result = validate_material_bare(full, bare, {"bark": "wood", "leaf": "card"})
    assert result["status"] == "passed"
    assert result["wood_triangles"] == result["bare_triangles"] == 1
    assert result["card_triangles"] == 1
    assert len(result["full"]["sha256"]) == len(result["bare"]["sha256"]) == 64


@pytest.mark.parametrize("assigned", ["wood", "card"])
def test_shared_atlas_cannot_be_misclassified_as_a_valid_bare_view(tmp_path, assigned):
    full = write_obj(tmp_path / "full.obj", "usemtl shared\nf 1 2 3\nf 4 5 6\n")
    bare = write_obj(tmp_path / "bare.obj", "usemtl shared\nf 1 2 3\n")
    result = validate_material_bare(full, bare, {"shared": assigned})
    assert result["status"] == "failed"
    assert result["bare_missing_from_wood"] or result["wood_missing_from_bare"]


def test_unmapped_or_missing_material_must_fail(tmp_path):
    full = write_obj(tmp_path / "full.obj", "f 1 2 3\nusemtl leaf\nf 4 5 6\n")
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 3\n")
    result = validate_material_bare(full, bare, {"leaf": "card"})
    assert result["status"] == "failed"
    assert result["unmapped_materials"] == [{"material": None, "triangles": 1}]


def test_identical_coordinates_across_categories_are_ambiguous(tmp_path):
    full = write_obj(tmp_path / "full.obj", "usemtl bark\nf 1 2 3\nusemtl leaf\nf 1 2 3\n")
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 3\n")
    result = validate_material_bare(full, bare, {"bark": "wood", "leaf": "card"})
    assert result["status"] == "failed"
    assert result["ambiguous_overlapping_triangles"] == 1


def test_multiplicity_and_fan_triangulation_are_checked(tmp_path):
    full = write_obj(tmp_path / "full.obj", "usemtl bark\nf 1 2 3\nf 1 2 3\n")
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 3\n")
    result = validate_material_bare(full, bare, {"bark": "wood"})
    assert result["status"] == "failed"
    assert result["wood_missing_from_bare"] == 1


@pytest.mark.parametrize("invalid", [None, {}, {"x": []}, {"x": "unknown"}, {"": "wood"}])
def test_invalid_mapping_rejected(tmp_path, invalid):
    full = write_obj(tmp_path / "full.obj", "f 1 2 3\n")
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 3\n")
    with pytest.raises(ValueError):
        validate_material_bare(full, bare, invalid)


@pytest.mark.parametrize("face", ["f 0 1 2", "f 1 2 9", "f 1 2", "f 1 1 2"])
def test_invalid_full_mesh_rejected(tmp_path, face):
    full = write_obj(tmp_path / "full.obj", "usemtl bark\n" + face + "\n")
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 3\n")
    with pytest.raises(ValueError):
        validate_material_bare(full, bare, {"bark": "wood"})


def test_same_path_is_not_an_independent_bare_mesh(tmp_path):
    full = write_obj(tmp_path / "full.obj", "usemtl bark\nf 1 2 3\n")
    assert validate_material_bare(full, full, {"bark": "wood"})["status"] == "failed"
