"""Check that a full OBJ's material split reproduces independent bare geometry."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path

from .production_pair import _read_triangles


def validate_material_bare(full_path, bare_path, material_categories):
    """Compare exact material-split triangles with a separately exported bare OBJ.

    The supplied material map is validated for this pair of exports only. This
    does not prove export provenance, visibility, texture alpha or card shape.
    """
    if (
        not isinstance(material_categories, dict)
        or not material_categories
        or not all(
            isinstance(name, str)
            and name.strip()
            and isinstance(category, str)
            and category in {"wood", "card"}
            for name, category in material_categories.items()
        )
    ):
        raise ValueError("material_categories must map nonempty material names to wood or card")
    full = Path(full_path).expanduser().resolve(strict=True)
    if full.suffix.lower() != ".obj" or not full.is_file():
        raise ValueError("Expected a full OBJ mesh")
    bare_source, bare_triangles = _read_triangles(bare_path)
    positions = []
    grouped = {"wood": Counter(), "card": Counter()}
    unknown = Counter()
    current_material = None
    digest = hashlib.sha256()
    face_count = 0
    with full.open("rb") as stream:
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
                    point = tuple(float(value) for value in fields[1:4])
                except ValueError as exc:
                    raise ValueError(f"Invalid vertex at line {line_number}") from exc
                if not all(math.isfinite(value) for value in point):
                    raise ValueError(f"Non-finite vertex at line {line_number}")
                positions.append(point)
            elif fields[0] == "usemtl":
                if len(fields) < 2:
                    raise ValueError(f"Empty material at line {line_number}")
                current_material = " ".join(fields[1:])
            elif fields[0] == "f":
                if len(fields) < 4:
                    raise ValueError(f"Face has fewer than three vertices at line {line_number}")
                indices = []
                for token in fields[1:]:
                    try:
                        index = int(token.split("/", 1)[0])
                    except ValueError as exc:
                        raise ValueError(f"Invalid face index at line {line_number}") from exc
                    resolved = index - 1 if index > 0 else len(positions) + index
                    if index == 0 or resolved < 0 or resolved >= len(positions):
                        raise ValueError(f"Face vertex index out of range at line {line_number}")
                    indices.append(resolved)
                if len(set(indices)) != len(indices):
                    raise ValueError(f"Repeated vertex in face at line {line_number}")
                category = material_categories.get(current_material)
                face_count += 1
                for index in range(1, len(indices) - 1):
                    triangle = tuple(
                        sorted(
                            (
                                positions[indices[0]],
                                positions[indices[index]],
                                positions[indices[index + 1]],
                            )
                        )
                    )
                    if len(set(triangle)) != 3:
                        raise ValueError(f"Degenerate triangle at line {line_number}")
                    if category is None:
                        unknown[current_material] += 1
                    else:
                        grouped[category][triangle] += 1
    if not face_count:
        raise ValueError("Full OBJ contains no faces")
    missing = bare_triangles - grouped["wood"]
    extra = grouped["wood"] - bare_triangles
    overlap = grouped["wood"] & grouped["card"]
    failures = []
    if unknown:
        failures.append("Full OBJ has unmapped materials")
    if missing or extra:
        failures.append("Wood material geometry differs from the independent bare OBJ")
    if overlap:
        failures.append("Wood and card material triangles overlap; attribution is ambiguous")
    if full == Path(bare_source["path"]):
        failures.append("Full and bare OBJ paths must differ")
    return {
        "status": "failed" if failures else "passed",
        "scope": "material_geometry_equals_bare_only",
        "full": {"path": str(full), "sha256": digest.hexdigest()},
        "bare": bare_source,
        "wood_triangles": sum(grouped["wood"].values()),
        "card_triangles": sum(grouped["card"].values()),
        "bare_triangles": sum(bare_triangles.values()),
        "bare_missing_from_wood": sum(missing.values()),
        "wood_missing_from_bare": sum(extra.values()),
        "ambiguous_overlapping_triangles": sum(overlap.values()),
        "unmapped_materials": [
            {"material": key, "triangles": count}
            for key, count in sorted(unknown.items(), key=lambda item: str(item[0]))
        ],
        "material_categories": dict(material_categories),
        "failures": failures,
        "limitations": [
            "Does not independently verify source and export provenance or that bare is truly card-free.",
            "Coordinates and deterministic fan triangulation must match exactly; normals and UVs are not compared.",
            "Texture alpha, card geometry and artistic acceptance are not verified.",
        ],
    }
