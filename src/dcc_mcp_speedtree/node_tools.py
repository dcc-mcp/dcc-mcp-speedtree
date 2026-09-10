"""Typed file-authoring entry points shared by the packaged node tools."""

from __future__ import annotations

from pathlib import Path

from .graph import SpeedTreeGraph


def inspect_graph(source_path):
    return SpeedTreeGraph.load(source_path).inspect()


def inspect_properties(source_path, node_id):
    graph = SpeedTreeGraph.load(source_path)
    return {
        "node_id": node_id,
        "source_sha256": graph.source_hash,
        "properties": graph.properties(node_id),
        "live_probe_performed": False,
    }


def edit_graph(source_path, output_path, operations):
    graph = SpeedTreeGraph.load(source_path)
    receipts = graph.apply(operations)
    saved = graph.save(output_path)
    readback = SpeedTreeGraph.load(output_path)
    return {
        "output": saved,
        "operations": receipts,
        "graph": readback.inspect(),
        "source_modified": False,
        "live_probe_performed": False,
    }


def discover_templates(speedtree_root):
    root = Path(speedtree_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Expected the installed SpeedTree content directory")
    result = []
    for folder, suffix in (("templates", ".stt"), ("tree_templates", ".spm")):
        for path in sorted((root / folder).rglob("*")):
            if path.suffix.lower() == suffix and path.is_file():
                result.append(
                    {
                        "path": str(path),
                        "relative_path": path.relative_to(root).as_posix(),
                        "kind": "generator" if suffix == ".stt" else "project",
                    }
                )
    return {"templates": result, "count": len(result), "mutated": False}


def inspect_authoring_catalog(speedtree_root):
    """Report the actual installed generator/property surface, including failures."""
    templates = discover_templates(speedtree_root)["templates"]
    types, failures = {}, []
    inspected = 0
    for item in templates:
        if item["kind"] != "generator":
            continue
        try:
            graph = SpeedTreeGraph.load(item["path"])
            for generator in graph.inspect()["generators"]:
                entry = types.setdefault(generator["type"], {"templates": [], "properties": set()})
                entry["templates"].append(item["relative_path"])
                entry["properties"].update(p["name"] for p in graph.properties(generator["id"]))
            inspected += 1
        except (ValueError, OSError) as exc:
            failures.append({"template": item["relative_path"], "error": str(exc)})
    return {
        "schema": "speedtree.authoring-catalog.v1",
        "inspected_templates": inspected,
        "generator_types": [
            {
                "type": kind,
                "templates": sorted(set(entry["templates"])),
                "property_names": sorted(entry["properties"]),
                "property_count": len(entry["properties"]),
            }
            for kind, entry in sorted(types.items())
        ],
        "failures": failures,
        "coverage": "serialized_generator_properties_only",
        "all_modeler_capabilities_exposed": False,
        "geometry_validation": "per_recipe_required",
        "live_probe_performed": False,
    }
