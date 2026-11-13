import hashlib

import pytest

from dcc_mcp_speedtree.production_pair import validate_obj_pair

VERTICES = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\n"


def write_obj(path, faces):
    path.write_text(VERTICES + faces, encoding="utf-8")
    return path


def test_subset_counts_cards_and_hashes_with_changed_indices(tmp_path):
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 5\n")
    full = write_obj(tmp_path / "full.obj", "f 5 2 1\nf 1 2 3 4\n")
    result = validate_obj_pair(full, bare, 3, 2)
    assert result["status"] == "passed"
    assert result["scope"] == "exact_geometry_delta_only"
    assert result["full"]["triangles"] == 3
    assert result["bare"]["triangles"] == 1
    assert result["full_minus_bare_triangles"] == 2
    assert result["full"]["sha256"] == hashlib.sha256(full.read_bytes()).hexdigest()
    assert result["visual_acceptance"] == "pending_artist_review"


def test_missing_geometry_and_duplicate_multiplicity_fail_closed(tmp_path):
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 5\nf 1 2 5\n")
    full = write_obj(tmp_path / "full.obj", "f 1 2 5\nf 1 2 3\n")
    result = validate_obj_pair(full, bare, 4, 1)
    assert result["status"] == "failed"
    assert result["bare_triangles_missing_from_full"] == 1
    assert result["full_minus_bare_triangles"] is None


@pytest.mark.parametrize("maximum,cards", [(1, 1), (2, 2)])
def test_limits_fail(tmp_path, maximum, cards):
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 5\n")
    full = write_obj(tmp_path / "full.obj", "f 1 2 5\nf 1 2 3\n")
    assert validate_obj_pair(full, bare, maximum, cards)["status"] == "failed"


def test_negative_indices_resolve_at_face_and_subset(tmp_path):
    bare = write_obj(tmp_path / "bare.obj", "f -5 -4 -1\n")
    full = write_obj(tmp_path / "full.obj", "f 1 2 5\nf 1 2 3\n")
    assert validate_obj_pair(full, bare, 2, 1)["status"] == "passed"


@pytest.mark.parametrize("face", ["f 0 2 3", "f 1 2 99", "f 1 1 3", "f a 2 3", "f 1 2"])
def test_bad_geometry_rejected(tmp_path, face):
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 5\n")
    full = write_obj(tmp_path / "full.obj", face + "\n")
    with pytest.raises(ValueError):
        validate_obj_pair(full, bare, 2, 1)


def test_reject_nonfinite_vertices_and_invalid_budgets(tmp_path):
    bare = write_obj(tmp_path / "bare.obj", "f 1 2 5\n")
    full = tmp_path / "full.obj"
    full.write_text("v nan 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    with pytest.raises(ValueError, match="Non-finite"):
        validate_obj_pair(full, bare, 2, 1)
    with pytest.raises(ValueError, match="non-negative"):
        validate_obj_pair(bare, bare, True, 0)
