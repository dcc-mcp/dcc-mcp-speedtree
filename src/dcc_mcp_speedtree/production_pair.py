"""Compare independently exported full and no-card OBJ geometry.

The geometry difference is only evidence of card triangles if the caller has
independently verified how the no-card project was created and exported.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path


def _read_triangles(path):
    path = Path(path).expanduser().resolve(strict=True)
    if path.suffix.lower() != ".obj" or not path.is_file():
        raise ValueError("Expected an OBJ mesh")
    vertices = []
    triangles = Counter()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            digest.update(raw)
            try:
                fields = raw.decode("utf-8-sig").split("#", 1)[0].split()
            except UnicodeDecodeError as exc:
                raise ValueError(f"OBJ is not UTF-8 at line {line_number}") from exc
            if not fields:
                continue
            if fields[0] == "v":
                if len(fields) < 4:
                    raise ValueError(f"Invalid vertex at line {line_number}")
                try:
                    pos = tuple(float(item) for item in fields[1:4])
                except ValueError as exc:
                    raise ValueError(f"Invalid vertex at line {line_number}") from exc
                if not all(math.isfinite(item) for item in pos):
                    raise ValueError(f"Non-finite vertex at line {line_number}")
                vertices.append(pos)
            elif fields[0] == "f":
                if len(fields) < 4:
                    raise ValueError(f"Face has fewer than three vertices at line {line_number}")
                face = []
                for token in fields[1:]:
                    try:
                        index = int(token.split("/", 1)[0])
                    except ValueError as exc:
                        raise ValueError(f"Invalid face index at line {line_number}") from exc
                    resolved = index - 1 if index > 0 else len(vertices) + index
                    if index == 0 or resolved < 0 or resolved >= len(vertices):
                        raise ValueError(f"Face vertex index out of range at line {line_number}")
                    face.append(resolved)
                if len(set(face)) != len(face):
                    raise ValueError(f"Repeated vertex in face at line {line_number}")
                # Deterministic fan triangulation. Comparison is meaningful only
                # when exports use compatible tessellation for matching faces.
                for idx in range(1, len(face) - 1):
                    tri = tuple(
                        sorted((vertices[face[0]], vertices[face[idx]], vertices[face[idx + 1]]))
                    )
                    if len(set(tri)) != 3:
                        raise ValueError(f"Degenerate triangle at line {line_number}")
                    triangles[tri] += 1
    if not triangles:
        raise ValueError("OBJ contains no triangles")
    return {"path": str(path), "sha256": digest.hexdigest()}, triangles


def validate_obj_pair(full_path, bare_path, total_max_triangles, card_triangles):
    """Compare exact coordinate triangles, preserving duplicate multiplicity.

    A passing result means only that the bare mesh is a geometric subset and
    its triangle difference matches the requested count. Coordinates and fan
    tessellation must match exactly; it does not verify project provenance.
    """
    for name, value in (
        ("total_max_triangles", total_max_triangles),
        ("card_triangles", card_triangles),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    full_source, full = _read_triangles(full_path)
    bare_source, bare = _read_triangles(bare_path)
    missing = bare - full
    delta = full - bare
    full_count = sum(full.values())
    bare_count = sum(bare.values())
    missing_count = sum(missing.values())
    delta_count = sum(delta.values())
    failures = []
    if missing_count:
        failures.append("Bare geometry contains triangles absent from the full mesh")
    if full_count > total_max_triangles:
        failures.append("Full mesh exceeds total triangle budget")
    if not missing_count and delta_count != card_triangles:
        failures.append("Full minus bare triangle count differs from requested card budget")
    return {
        "status": "failed" if failures else "passed",
        "scope": "exact_geometry_delta_only",
        "full": {**full_source, "triangles": full_count},
        "bare": {**bare_source, "triangles": bare_count},
        "bare_triangles_missing_from_full": missing_count,
        "full_minus_bare_triangles": delta_count if not missing_count else None,
        "total_max_triangles": total_max_triangles,
        "requested_card_triangles": card_triangles,
        "failures": failures,
        "limitations": [
            "Verify independently that the bare export differs only by removal of the intended card generators.",
            "Export provenance, LOD, units, dimensions, dependencies and visual quality are not verified.",
            "Matching uses exact position coordinates and deterministic fan triangulation; normals and UVs are not compared.",
        ],
        "visual_acceptance": "pending_artist_review",
    }
