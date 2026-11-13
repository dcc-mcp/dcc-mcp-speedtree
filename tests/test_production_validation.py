import pytest

from dcc_mcp_speedtree.production_validation import validate_obj_budget


def obj(tmp_path, faces):
    path = tmp_path / "tree.obj"
    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 1 1\n" + faces,
        encoding="utf-8",
    )
    return path


def test_budget_counts_triangulated_faces_and_exact_card_budget(tmp_path):
    source = obj(
        tmp_path,
        "usemtl bark\nf 1 2 3 4\nusemtl leaves\nf -5/-1 -4/-2 -1/-3\n",
    )
    result = validate_obj_budget(
        source, {"bark": "wood", "leaves": "cards"}, 3, {"cards": {"min": 1, "max": 1}}
    )
    assert result["status"] == "passed"
    assert result["face_count"] == 2
    assert result["total_triangles"] == 3
    assert result["category_triangles"] == {"wood": 2, "cards": 1}
    assert result["visual_acceptance"] == "pending_artist_review"
    assert result["source"]["sha256"]


def test_unknown_material_never_passes_budget(tmp_path):
    source = obj(tmp_path, "usemtl leaf\nf 1 2 3\nusemtl mystery\nf 1 2 3 4\n")
    result = validate_obj_budget(source, {"leaf": "cards"}, 3, {"cards": {"min": 2, "max": 2}})
    assert result["status"] == "unverified"
    assert result["unmapped_materials"] == [{"material": "mystery", "triangles": 2}]
    assert result["failures"] == []


def test_budget_failure_detected_even_with_unknown_material(tmp_path):
    source = obj(tmp_path, "usemtl leaf\nf 1 2 3 4\nusemtl unknown\nf 1 2 3\n")
    result = validate_obj_budget(source, {"leaf": "cards"}, 2, {"cards": {"max": 1}})
    assert result["status"] == "failed"
    assert len(result["failures"]) == 2


def test_missing_material_and_minimum_shortfall(tmp_path):
    source = obj(tmp_path, "f 1 2 3\n")
    assert validate_obj_budget(source, {}, 10, {"cards": {"min": 1}})["status"] == "unverified"
    source = obj(tmp_path, "usemtl bark\nf 1 2 3\n")
    assert (
        validate_obj_budget(source, {"bark": "wood"}, 10, {"cards": {"min": 1}})["status"]
        == "failed"
    )


@pytest.mark.parametrize("face", ["f 1 2 9", "f 0 1 2", "f 1 2", "f 1 1 3", "f 1 2 nope"])
def test_rejects_bad_geometry(tmp_path, face):
    source = obj(tmp_path, face + "\n")
    with pytest.raises(ValueError):
        validate_obj_budget(source, {}, 20, {})


@pytest.mark.parametrize(
    "limits", [{"cards": {"min": 4, "max": 3}}, {"cards": {"max": True}}, {"cards": {}}]
)
def test_rejects_invalid_limits(tmp_path, limits):
    source = obj(tmp_path, "f 1 2 3\n")
    with pytest.raises(ValueError):
        validate_obj_budget(source, {}, 20, limits)
