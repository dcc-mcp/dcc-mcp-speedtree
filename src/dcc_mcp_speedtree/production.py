"""Prepare an editable candidate; geometry and artistic acceptance are separate.

This module edits the observed file format, not a supported live Modeler API.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path, PureWindowsPath

from .graph import GraphError, SpeedTreeGraph


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Dependency path must be a nonempty relative path")
    win = PureWindowsPath(value)
    if win.is_absolute() or win.drive or any(part in ("..", ".") for part in win.parts):
        raise ValueError(f"Dependency path must stay inside the reference directory: {value}")
    return Path(*win.parts)


def _roles(graph, roles):
    if not isinstance(roles, dict):
        raise ValueError("roles must be a mapping from roles to generator IDs")
    snapshot = graph.inspect()
    nodes = {g["id"]: g for g in snapshot["generators"]}
    expected = {
        "trunk": {"Branch"},
        "primary_branches": {"Branch"},
        "secondary_branches": {"Branch"},
        "leaf_cards": {"Leaf", "Leaf Mesh", "Frond"},
    }
    seen = set()
    for role, ids in roles.items():
        if role not in expected or not isinstance(ids, list) or not ids:
            raise ValueError(f"Unsupported role or empty generator list: {role}")
        for node in ids:
            if not isinstance(node, str) or node in seen or node not in nodes:
                raise ValueError(f"Unknown or duplicate role generator: {node}")
            if nodes[node]["type"] not in expected[role]:
                raise ValueError(f"Generator type does not match role: {role}: {node}")
            seen.add(node)
    parents = {}
    for link in snapshot["links"]:
        parents.setdefault(link["target_id"], set()).add(link["source_id"])

    def descends(node, ancestors):
        queue = list(parents.get(node, ()))
        visited = set()
        while queue:
            parent = queue.pop()
            if parent in ancestors:
                return True
            if parent not in visited:
                visited.add(parent)
                queue.extend(parents.get(parent, ()))
        return False

    for child_role, parent_role in (
        ("primary_branches", "trunk"),
        ("secondary_branches", "primary_branches"),
    ):
        if child_role in roles and parent_role in roles:
            for node in roles[child_role]:
                if not descends(node, set(roles[parent_role])):
                    raise ValueError(f"{child_role} generator is not connected below {parent_role}")
    branch_ids = set(
        roles.get("trunk", [])
        + roles.get("primary_branches", [])
        + roles.get("secondary_branches", [])
    )
    if branch_ids:
        for node in roles.get("leaf_cards", []):
            if not descends(node, branch_ids):
                raise ValueError("leaf_cards generator is not connected below a mapped branch")
    return snapshot


def generate_project(source_path, output_dir, operations, brief):
    """Create a new directory containing a candidate project and an audit manifest.

    Source and dependencies are never overwritten. Only TexFilename references
    and caller-declared dependencies are inspected; other asset kinds remain
    unverified. A fixed seed in the brief is metadata, not a Modeler operation.
    """
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")
    json.dumps({"brief": brief, "operations": operations}, allow_nan=False)
    source = Path(source_path).expanduser().resolve(strict=True)
    output = Path(output_dir).expanduser().resolve()
    if source.suffix.lower() != ".spm":
        raise ValueError("A reference SPM project is required")
    if output.exists() or output == source.parent or output in source.parents:
        raise ValueError("Output must be a new directory and must not contain the source")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory must exist")
    graph = SpeedTreeGraph.load(source)
    original = graph.inspect()
    receipts = graph.apply(operations) if operations else []
    _roles(graph, brief.get("roles", {}))
    declared = brief.get("dependencies", [])
    if not isinstance(declared, list):
        raise ValueError("dependencies must be an array of relative paths")
    assets = graph.root.find("Assets")
    found = (
        []
        if assets is None
        else [e.text.strip() for e in assets.iter("TexFilename") if e.text and e.text.strip()]
    )
    dependencies = []
    seen = set()
    for value in declared + found:
        rel = _relative(value)
        item = (source.parent / rel).resolve(strict=True)
        if source.parent not in item.parents or not item.is_file():
            raise ValueError(f"Dependency escapes source directory or is not a file: {value}")
        key = str(rel).casefold()
        if key not in seen:
            seen.add(key)
            dependencies.append((rel, item, _hash(item)))
    if any(
        str(rel).casefold() in {source.name.casefold(), "manifest.json"}
        for rel, _, _ in dependencies
    ):
        raise ValueError("Dependency conflicts with the project or manifest")
    with tempfile.TemporaryDirectory(prefix=".speedtree-production-", dir=output.parent) as temp:
        stage = Path(temp) / "candidate"
        stage.mkdir()
        project = stage / source.name
        graph.save(project)
        for rel, item, expected_hash in dependencies:
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
            if _hash(target) != expected_hash or _hash(item) != expected_hash:
                raise ValueError(f"Dependency changed during copy: {rel}")
        readback = SpeedTreeGraph.load(project).inspect()
        manifest = {
            "schema": "speedtree.production-candidate.v1",
            "source": {"path": str(source), "sha256": original["source_sha256"]},
            "project": {"path": source.name, "sha256": _hash(project)},
            "brief": brief,
            "operations": operations,
            "operation_receipts": receipts,
            "source_graph": original,
            "candidate_graph": readback,
            "dependencies": [
                {"path": rel.as_posix(), "sha256": digest} for rel, _, digest in dependencies
            ],
            "validation": {
                "graph_roles": "validated" if brief.get("roles") else "not_requested",
                "dependency_discovery": "partial_texfilename_and_declared_only",
                "modeler_regeneration": "not_run",
                "export_geometry_budget": "not_run",
                "dimensions_units": "not_verified",
                "four_views_and_closeups": "not_run",
                "visual_acceptance": "not_run",
                "seed_effect": "not_verified",
                "determinism": "not_verified",
            },
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        if _hash(source) != original["source_sha256"]:
            raise GraphError("Source changed during preparation")
        stage.rename(output)
    return {
        "project_path": str(output / source.name),
        "manifest_path": str(output / "manifest.json"),
        "status": "candidate_prepared",
        "validation": manifest["validation"],
    }
