"""Independent triangle-budget readback for exported Wavefront OBJ geometry.

Material-to-category mappings are supplied by the caller. This module cannot
prove that a material maps to the intended generator, that the OBJ is the
latest Modeler export, or that the tree is visually acceptable.
"""

import hashlib
import math
from pathlib import Path


def _nonnegative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def validate_obj_budget(obj_path, material_categories, total_max_triangles, category_limits):
    """Count triangles in an OBJ using an explicit material/category mapping.

    ``category_limits`` maps a category to a min and/or max triangle count.
    Polygon counts use n-2 triangles per face, including quads. An unknown
    material leaves categorised budgets unverified, even when the total fits.
    ``passed`` applies only to geometry counts, not production or visual QA.
    """
    total_max_triangles = _nonnegative_integer(total_max_triangles, "total_max_triangles")
    if not isinstance(material_categories, dict) or not all(
        isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
        for k, v in material_categories.items()
    ):
        raise ValueError("material_categories must map non-empty material names to categories")
    if not isinstance(category_limits, dict):
        raise ValueError("category_limits must be a dictionary")
    for name, limits in category_limits.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(limits, dict):
            raise ValueError("Invalid category limit")
        if not limits or set(limits) - {"min", "max"}:
            raise ValueError("Category limits must contain min and/or max")
        for kind, value in limits.items():
            _nonnegative_integer(value, f"{name}.{kind}")
        if limits.get("min", 0) > limits.get("max", math.inf):
            raise ValueError(f"{name} minimum exceeds maximum")

    path = Path(obj_path).resolve(strict=True)
    if path.suffix.lower() != ".obj" or not path.is_file():
        raise ValueError("Geometry readback requires an OBJ file")

    vertices = 0
    face_count = 0
    total = 0
    materials = {}
    current_material = None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for line_number, raw in enumerate(source, 1):
            digest.update(raw)
            try:
                line = raw.decode("utf-8-sig").split("#", 1)[0].strip()
            except UnicodeDecodeError as exc:
                raise ValueError(f"OBJ is not UTF-8 at line {line_number}") from exc
            if not line:
                continue
            fields = line.split()
            if fields[0] == "v":
                if len(fields) < 4:
                    raise ValueError(f"Invalid vertex at line {line_number}")
                try:
                    coordinates = [float(x) for x in fields[1:4]]
                except ValueError as exc:
                    raise ValueError(f"Invalid vertex at line {line_number}") from exc
                if not all(math.isfinite(v) for v in coordinates):
                    raise ValueError(f"Non-finite vertex at line {line_number}")
                vertices += 1
            elif fields[0] == "usemtl":
                if len(fields) < 2:
                    raise ValueError(f"Empty material at line {line_number}")
                current_material = " ".join(fields[1:])
            elif fields[0] == "f":
                if len(fields) < 4:
                    raise ValueError(f"Face has fewer than three vertices at line {line_number}")
                indices = []
                for element in fields[1:]:
                    try:
                        index = int(element.split("/", 1)[0])
                    except ValueError as exc:
                        raise ValueError(f"Invalid face at line {line_number}") from exc
                    resolved = index if index > 0 else vertices + index + 1
                    if index == 0 or resolved < 1 or resolved > vertices:
                        raise ValueError(f"Invalid vertex index at line {line_number}")
                    indices.append(resolved)
                if len(set(indices)) != len(indices):
                    raise ValueError(f"Repeated vertex in face at line {line_number}")
                triangles = len(indices) - 2
                face_count += 1
                total += triangles
                materials[current_material] = materials.get(current_material, 0) + triangles
    if face_count == 0:
        raise ValueError("OBJ contains no faces")

    categories = {}
    unknown = []
    for material, count in materials.items():
        category = material_categories.get(material)
        if category is None:
            unknown.append({"material": material, "triangles": count})
        else:
            categories[category] = categories.get(category, 0) + count
    failures = []
    if total > total_max_triangles:
        failures.append(f"total triangles {total} exceed maximum {total_max_triangles}")
    # Known counts are lower bounds if any material is unclassified.
    for name, limits in category_limits.items():
        count = categories.get(name, 0)
        if "max" in limits and count > limits["max"]:
            failures.append(f"{name} triangles {count} exceed maximum {limits['max']}")
        if not unknown and "min" in limits and count < limits["min"]:
            failures.append(f"{name} triangles {count} are below minimum {limits['min']}")
    status = "failed" if failures else "unverified" if unknown else "passed"
    return {
        "status": status,
        "source": {"path": str(path), "sha256": digest.hexdigest(), "format": "obj"},
        "face_count": face_count,
        "total_triangles": total,
        "total_max_triangles": total_max_triangles,
        "category_triangles": categories,
        "category_limits": category_limits,
        "unmapped_materials": unknown,
        "failures": failures,
        "category_mapping_basis": "caller_supplied_material_names",
        "limitations": [
            "Material mappings do not independently prove generator categories.",
            "Export provenance, units, dependencies, and appearance require separate validation.",
            "Polygon triangulation count assumes n-2 triangles per face.",
        ],
        "visual_acceptance": "pending_artist_review",
    }
