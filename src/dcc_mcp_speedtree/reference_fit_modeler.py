"""Connect bounded reference fitting to official Modeler exports and evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path

from dcc_mcp_core.cancellation import check_cancelled

from .export import export_batch, fingerprint, verify_export
from .graph import GraphError, SpeedTreeGraph
from .production import generate_project
from .production_mapping import validate_material_bare
from .production_planarity import validate_card_planes
from .production_preview import generate_diagnostic_views
from .production_structure import validate_branch_structure
from .reference_match import VIEWS, compare_reference_views

CARD_TYPES = {"Leaf", "Leaf Mesh", "Frond"}


def make_bare_copy(full_project, bare_project):
    """Remove only all identified card generators, rejecting other descendants."""
    graph = SpeedTreeGraph.load(full_project)
    before = graph.inspect()
    nodes = {node["id"]: node for node in before["generators"]}
    cards = {node["id"] for node in nodes.values() if node["type"] in CARD_TYPES}
    if not cards:
        raise ValueError("No Leaf/Leaf Mesh/Frond generators found for independent card count")
    edges = [(edge["source_id"], edge["target_id"]) for edge in before["links"]]
    if any(parent in cards and child not in cards for parent, child in edges):
        raise ValueError(
            "Card generator has a non-card child; cannot isolate without changing wood"
        )
    pending = set(cards)
    removal = []
    while pending:
        leaves = sorted(
            node for node in pending if not any(a == node and b in pending for a, b in edges)
        )
        if not leaves:
            raise GraphError("Card subgraph could not be ordered")
        removal.extend({"op": "remove", "node_id": node} for node in leaves)
        pending.difference_update(leaves)
    graph.apply(removal)
    graph.save(bare_project)
    after = SpeedTreeGraph.load(bare_project).inspect()
    remaining = {node["id"] for node in after["generators"]}
    if remaining != set(nodes) - cards:
        raise GraphError("Unexpected generator changes while removing cards")
    return {
        "removed_ids": sorted(cards),
        "full_sha256": before["source_sha256"],
        "bare_sha256": after["source_sha256"],
        "method": "remove_card_generators_only",
    }


def fit_reference_modeler(
    source_path,
    output_dir,
    parameters,
    references,
    preset_path,
    material_categories,
    brief,
    trunk_id,
    *,
    base_operations=None,
    total_max_triangles=2000,
    card_triangles=800,
    max_branch_order=2,
    max_secondary=None,
    plane_tolerance=0.001,
    max_evaluations=6,
    max_rounds=1,
    resolution=512,
    candidate_view_map=None,
):
    """Run bounded discrete fitting with exported geometry and graph checks.

    This uses only explicit parameters and explicitly segmented reference masks;
    it does not infer reference views, edit per-instance branches, verify units,
    or confer artistic/production acceptance.
    """
    from .reference_fit import fit_reference_parameters

    source = Path(source_path).expanduser().resolve(strict=True)
    preset = Path(preset_path).expanduser().resolve(strict=True)
    output = Path(output_dir).expanduser().resolve()
    if (
        output.exists()
        or not output.parent.is_dir()
        or output == source.parent
        or output in source.parents
    ):
        raise ValueError("Output must be a new directory that does not contain the source")
    if not isinstance(brief, dict):
        raise ValueError("brief must be an object")
    if (
        isinstance(plane_tolerance, bool)
        or not isinstance(plane_tolerance, (int, float))
        or not math.isfinite(plane_tolerance)
        or not 0 <= plane_tolerance <= 1
    ):
        raise ValueError("plane_tolerance must be finite and between 0 and 1")
    if not isinstance(references, dict) or set(references) != set(VIEWS):
        raise ValueError("Four explicit segmented reference views are required")
    view_map = {view: view for view in VIEWS} if candidate_view_map is None else candidate_view_map
    if (
        not isinstance(view_map, dict)
        or set(view_map) != set(VIEWS)
        or set(view_map.values()) != set(VIEWS)
    ):
        raise ValueError("candidate_view_map must be a permutation of four view names")
    reference_fingerprints = {
        view: fingerprint(Path(spec["path"]).expanduser().resolve(strict=True))
        for view, spec in references.items()
    }
    source_identity = fingerprint(source)
    preset_identity = fingerprint(preset)
    output.mkdir()
    trials = output / "trials"
    trials.mkdir()
    inputs_changed = False

    def evaluate(trial_id, operations):
        nonlocal inputs_changed
        check_cancelled()
        if fingerprint(source) != source_identity or fingerprint(preset) != preset_identity:
            inputs_changed = True
            raise ValueError("Source or preset changed during fitting")
        for view, spec in references.items():
            if (
                fingerprint(Path(spec["path"]).expanduser().resolve(strict=True))
                != reference_fingerprints[view]
            ):
                inputs_changed = True
                raise ValueError("Reference image changed during fitting")
        trial = trials / trial_id
        trial.mkdir(exist_ok=False)
        candidate = generate_project(source, trial / "candidate", operations, brief)
        full = Path(candidate["project_path"])
        structure = validate_branch_structure(full, trunk_id, max_branch_order, max_secondary)
        if structure["status"] != "passed":
            return {"structure": structure}
        bare = full.with_name("_fit_bare.spm")
        removal = make_bare_copy(full, bare)
        result = export_batch([str(full), str(bare)], str(preset), trial / "export", "obj", 600)
        check_cancelled()
        if result["status"] != "exported" or not verify_export(result["manifest_path"])["verified"]:
            raise ValueError("Official Modeler exports could not be verified")
        if [item["source"]["sha256"] for item in result["items"]] != [
            removal["full_sha256"],
            removal["bare_sha256"],
        ]:
            raise ValueError("Export source identity does not match the generated candidates")
        full_obj, bare_obj = [
            str(Path(result["manifest_path"]).parent / item["mesh"]) for item in result["items"]
        ]
        mapping_audit = validate_material_bare(full_obj, bare_obj, material_categories)
        if mapping_audit["status"] != "passed":
            raise ValueError("Material mapping does not match independently exported bare geometry")
        plane_audit = validate_card_planes(full_obj, material_categories, plane_tolerance)
        provenance = {
            "verified": True,
            "card_removal": removal,
            "export_manifest": result["manifest_path"],
            "candidate_project": str(full),
            "candidate_manifest": candidate["manifest_path"],
            "material_mapping_check": mapping_audit,
        }
        if plane_audit["status"] != "passed":
            receipt = {
                "full_obj_path": full_obj,
                "bare_obj_path": bare_obj,
                "structure": structure,
                "provenance": provenance,
            }
            (trial / "evaluation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            return receipt
        preview = generate_diagnostic_views(
            full_obj, trial / "preview", material_categories, resolution
        )
        candidate_masks = {
            view: {
                "path": str(Path(preview["output_dir"]) / f"bare_{view_map[view]}_mask.png"),
                "mode": "light",
                "threshold": 128,
            }
            for view in VIEWS
        }
        comparison = compare_reference_views(references, candidate_masks, trial / "comparison")
        check_cancelled()
        provenance["preview_manifest"] = preview["manifest_path"]
        receipt = {
            "full_obj_path": full_obj,
            "bare_obj_path": bare_obj,
            "comparison": comparison,
            "structure": structure,
            "provenance": provenance,
        }
        (trial / "evaluation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return receipt

    report = fit_reference_parameters(
        str(source),
        parameters,
        evaluate,
        base_operations=base_operations,
        total_max_triangles=total_max_triangles,
        card_triangles=card_triangles,
        max_evaluations=max_evaluations,
        max_rounds=max_rounds,
        require_structure=True,
        card_plane_categories=material_categories,
        plane_tolerance=plane_tolerance,
    )
    try:
        inputs_changed = (
            inputs_changed
            or fingerprint(source) != source_identity
            or fingerprint(preset) != preset_identity
        )
        inputs_changed = inputs_changed or any(
            fingerprint(Path(spec["path"]).expanduser().resolve(strict=True))
            != reference_fingerprints[view]
            for view, spec in references.items()
        )
    except OSError:
        inputs_changed = True
    if inputs_changed:
        report["status"] = "inputs_changed"
        report["winner"] = None
    report["reference_views"] = references
    report["candidate_view_map"] = view_map
    report["reference_fingerprints"] = reference_fingerprints
    report["preset"] = {"path": str(preset), **preset_identity}
    report["visual_acceptance"] = "pending_artist_review"
    report["limitations"] = [
        "Fitting uses segmented silhouette overlap and does not prove visual or material quality.",
        "The graph audit checks Branch generator ancestry, not generated branch count or appearance.",
        "Planarity uses a configured tolerance and does not verify UVs or textures.",
        "Modeler export LOD, effective units and absolute dimensions require independent verification.",
    ]
    manifest = output / "fit-report.json"
    manifest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {"status": report["status"], "manifest_path": str(manifest), "result": report}
