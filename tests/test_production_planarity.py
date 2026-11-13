import pytest

from dcc_mcp_speedtree.production_planarity import validate_card_planes


def mesh(tmp_path, vertices, faces, mat="card"):
    path = tmp_path / "tree.obj"
    path.write_text(vertices + f"usemtl {mat}\n" + faces, encoding="utf-8")
    return path


SQUARE = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
TRIANGLES = "f 1 2 3\nf 1 3 4\n"


def test_flat_quad_as_two_triangles_passes(tmp_path):
    result = validate_card_planes(mesh(tmp_path, SQUARE, TRIANGLES), {"card": "card"})
    assert result["status"] == "passed"
    assert result["card_components"] == 1
    assert result["card_triangles"] == 2
    assert result["max_planarity_ratio"] == 0
    assert len(result["source"]["sha256"]) == 64


def test_separate_quad_vertex_indices_produce_two_cards(tmp_path):
    second = "v 2 0 0\nv 3 0 0\nv 3 1 0\nv 2 1 0\n"
    path = mesh(tmp_path, SQUARE + second, TRIANGLES + "f -4 -3 -2\nf -4 -2 -1\n")
    result = validate_card_planes(path, {"card": "card"})
    assert result["status"] == "passed"
    assert result["card_components"] == 2
    assert result["card_triangles"] == 4


def test_folded_quad_fails_with_excess_distance(tmp_path):
    vertices = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0.2\n"
    result = validate_card_planes(mesh(tmp_path, vertices, TRIANGLES), {"card": "card"})
    assert result["status"] == "failed"
    assert result["max_planarity_ratio"] > 0.001
    assert "planarity" in result["components"][0]["failures"][0]


def test_quad_polygon_and_single_triangle_fail(tmp_path):
    result = validate_card_planes(mesh(tmp_path, SQUARE, "f 1 2 3 4\n"), {"card": "card"})
    assert result["max_planarity_ratio"] is None
    assert (
        validate_card_planes(mesh(tmp_path, SQUARE, "f 1 2 3 4\n"), {"card": "card"})["status"]
        == "failed"
    )
    assert (
        validate_card_planes(mesh(tmp_path, SQUARE, "f 1 2 3\n"), {"card": "card"})["status"]
        == "failed"
    )


def test_two_triangles_touching_at_one_vertex_form_invalid_component(tmp_path):
    vertices = SQUARE + "v 2 1 0\n"
    result = validate_card_planes(mesh(tmp_path, vertices, "f 1 2 3\nf 3 4 5\n"), {"card": "card"})
    assert result["status"] == "failed"


def test_same_side_triangles_do_not_form_valid_quad(tmp_path):
    vertices = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0.2 0.5 0\n"
    result = validate_card_planes(mesh(tmp_path, vertices, "f 1 2 3\nf 1 2 4\n"), {"card": "card"})
    assert result["status"] == "failed"
    assert any("overlap" in msg for msg in result["components"][0]["failures"])


def test_degenerate_triangle_fails(tmp_path):
    vertices = "v 0 0 0\nv 1 0 0\nv 2 0 0\nv 0 1 0\n"
    result = validate_card_planes(mesh(tmp_path, vertices, TRIANGLES), {"card": "card"})
    assert result["status"] == "failed"
    assert "Degenerate" in result["components"][0]["failures"][0]


def test_unmapped_faces_and_no_cards_fail(tmp_path):
    path = mesh(tmp_path, SQUARE, TRIANGLES, mat="unknown")
    result = validate_card_planes(path, {"card": "card"})
    assert result["status"] == "failed"
    assert result["unmapped_materials"] == [{"material": "unknown", "triangles": 2}]


@pytest.mark.parametrize("face", ["f 1 2 9\n", "f 0 2 3\n", "f 1 1 2\n", "f 1 2\n"])
def test_invalid_indices_fail_closed(tmp_path, face):
    with pytest.raises(ValueError):
        validate_card_planes(mesh(tmp_path, SQUARE, face), {"card": "card"})


@pytest.mark.parametrize("invalid", [None, {}, {"card": []}, {"card": "tree"}])
def test_invalid_mapping_fails_closed(tmp_path, invalid):
    with pytest.raises(ValueError):
        validate_card_planes(mesh(tmp_path, SQUARE, TRIANGLES), invalid)


@pytest.mark.parametrize("invalid", [-1, 2, True, float("nan"), float("inf")])
def test_invalid_tolerance_fails_closed(tmp_path, invalid):
    with pytest.raises(ValueError):
        validate_card_planes(mesh(tmp_path, SQUARE, TRIANGLES), {"card": "card"}, invalid)


def test_nonfinite_vertex_fails_closed(tmp_path):
    vertices = "v 0 0 0\nv 1 0 0\nv nan 1 0\nv 0 1 0\n"
    with pytest.raises(ValueError):
        validate_card_planes(mesh(tmp_path, vertices, TRIANGLES), {"card": "card"})


def test_extreme_finite_vertex_values_do_not_falsely_pass(tmp_path):
    vertices = "v 1e308 0 0\nv -1e308 0 0\nv 0 1e308 0\nv 0 0 1e308\n"
    assert (
        validate_card_planes(mesh(tmp_path, vertices, TRIANGLES), {"card": "card"})["status"]
        == "failed"
    )
