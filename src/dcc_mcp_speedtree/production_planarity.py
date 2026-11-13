"""Diagnose whether mapped card components are planar, single-quad meshes."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _length(v):
    return math.sqrt(_dot(v, v))


def validate_card_planes(full_obj, material_categories, tolerance=0.001):
    """Check each vertex-connected card component is two triangles of one quad.

    Planarity is the fourth vertex's point-to-plane distance divided by the
    longest intervertex distance. Material categories are caller assertions;
    provenance, LOD, UVs, opacity, and visual acceptance are not established.
    """
    if (
        not isinstance(material_categories, dict)
        or not material_categories
        or not all(
            isinstance(k, str) and k.strip() and isinstance(v, str) and v in {"wood", "card"}
            for k, v in material_categories.items()
        )
    ):
        raise ValueError("material_categories must map material names to wood or card")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or not 0 <= tolerance <= 1
    ):
        raise ValueError("tolerance must be a finite number between 0 and 1")
    path = Path(full_obj).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".obj":
        raise ValueError("Expected an OBJ mesh")
    vertices = []
    card_faces = []
    unknown = {}
    materials_used = set()
    current_material = None
    digest = hashlib.sha256()
    face_count = 0
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
                    point = tuple(float(v) for v in fields[1:4])
                except ValueError as exc:
                    raise ValueError(f"Invalid vertex at line {line_number}") from exc
                if not all(math.isfinite(v) for v in point):
                    raise ValueError(f"Non-finite vertex at line {line_number}")
                vertices.append(point)
            elif fields[0] == "usemtl":
                if len(fields) < 2:
                    raise ValueError(f"Empty material at line {line_number}")
                current_material = " ".join(fields[1:])
            elif fields[0] == "f":
                if len(fields) < 4:
                    raise ValueError(f"Face has fewer than three vertices at line {line_number}")
                indices = []
                for part in fields[1:]:
                    try:
                        index = int(part.split("/", 1)[0])
                    except ValueError as exc:
                        raise ValueError(f"Invalid face index at line {line_number}") from exc
                    resolved = index - 1 if index > 0 else len(vertices) + index
                    if index == 0 or resolved < 0 or resolved >= len(vertices):
                        raise ValueError(f"Face vertex index out of range at line {line_number}")
                    indices.append(resolved)
                if len(set(indices)) != len(indices):
                    raise ValueError(f"Repeated vertex in face at line {line_number}")
                face_count += 1
                category = material_categories.get(current_material)
                if category is None:
                    unknown[current_material] = unknown.get(current_material, 0) + len(indices) - 2
                elif category == "card":
                    materials_used.add(current_material)
                    card_faces.append((tuple(indices), current_material, line_number))
    if not face_count:
        raise ValueError("OBJ contains no faces")
    vertex_faces = {}
    for index, (face, _, _) in enumerate(card_faces):
        for vertex in face:
            vertex_faces.setdefault(vertex, []).append(index)
    pending = set(range(len(card_faces)))
    components = []
    while pending:
        todo, connected = [min(pending)], []
        while todo:
            face_id = todo.pop()
            if face_id not in pending:
                continue
            pending.remove(face_id)
            connected.append(face_id)
            for vertex in card_faces[face_id][0]:
                todo.extend(vertex_faces[vertex])
        components.append(sorted(connected))
    issues = []
    if unknown:
        issues.append("OBJ contains faces with unmapped materials")
    if not card_faces:
        issues.append("OBJ has no mapped card faces")
    reports = []
    ratios = []
    for component_id, face_ids in enumerate(components, 1):
        faces = [card_faces[index] for index in face_ids]
        indices = sorted({vertex for face, _, _ in faces for vertex in face})
        errors = []
        ratio = None
        if len(faces) != 2 or len(indices) != 4 or any(len(face) != 3 for face, _, _ in faces):
            errors.append(
                "Component must be exactly two triangular faces with four distinct vertices"
            )
        else:
            shared = set(faces[0][0]) & set(faces[1][0])
            if len(shared) != 2:
                errors.append("Triangles must share exactly one edge")
            else:
                p = [vertices[index] for index in indices]
                diagonal = max(_length(_sub(a, b)) for a in p for b in p)
                a, b, c = (vertices[index] for index in faces[0][0])
                normal = _cross(_sub(b, a), _sub(c, a))
                normal_length = _length(normal)
                if not math.isfinite(diagonal) or not math.isfinite(normal_length):
                    errors.append("Card coordinates exceed stable numeric range")
                elif diagonal <= 0 or normal_length <= diagonal * diagonal * 1e-12:
                    errors.append("Degenerate card triangle")
                else:
                    fourth = next(index for index in indices if index not in faces[0][0])
                    ratio = abs(_dot(_sub(vertices[fourth], a), normal)) / (
                        normal_length * diagonal
                    )
                    if not math.isfinite(ratio):
                        errors.append("Card coordinates exceed stable numeric range")
                        ratio = None
                    else:
                        ratios.append(ratio)
                    if ratio is not None and ratio > tolerance:
                        errors.append("Card vertices exceed planarity tolerance")
                    edge_a, edge_b = sorted(shared)
                    opposite_a = next(index for index in faces[0][0] if index not in shared)
                    opposite_b = next(index for index in faces[1][0] if index not in shared)
                    edge = _sub(vertices[edge_b], vertices[edge_a])
                    left = _cross(edge, _sub(vertices[opposite_a], vertices[edge_a]))
                    right = _cross(edge, _sub(vertices[opposite_b], vertices[edge_a]))
                    if _length(right) <= diagonal * diagonal * 1e-12:
                        errors.append("Degenerate card triangle")
                    elif _dot(left, right) >= 0:
                        errors.append("Triangles overlap or do not form a single quad")
        report = {
            "component": component_id,
            "faces": len(faces),
            "vertices": len(indices),
            "materials": sorted({material for _, material, _ in faces}),
            "line_numbers": [line for _, _, line in faces],
            "planarity_ratio": ratio,
            "failures": errors,
        }
        if errors:
            issues.append(f"Card component {component_id} failed")
        reports.append(report)
    return {
        "status": "failed" if issues else "passed",
        "scope": "mapped_card_geometry_only",
        "source": {"path": str(path), "sha256": digest.hexdigest()},
        "material_categories": dict(material_categories),
        "tolerance": tolerance,
        "card_components": len(components),
        "card_triangles": sum(len(face) - 2 for face, _, _ in card_faces),
        "max_planarity_ratio": max(ratios) if ratios else None,
        "unmapped_materials": [
            {"material": key, "triangles": value}
            for key, value in sorted(unknown.items(), key=lambda x: str(x[0]))
        ],
        "failures": issues,
        "components": reports,
        "limitations": [
            "Material mapping and source/export provenance are caller supplied.",
            "LOD, UV layout, texture opacity, normals and artistic acceptance are not verified.",
        ],
    }
