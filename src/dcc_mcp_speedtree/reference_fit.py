"""Bounded reference-silhouette parameter search with geometry budget gates.

The evaluator must create separate candidate files and supply independent OBJ
exports and four-view comparisons. This module re-reads both OBJ meshes for
every candidate; callback-reported triangle counts are never accepted alone.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from dcc_mcp_core.cancellation import DccMcpCancelledError, check_cancelled

from .graph import SpeedTreeGraph
from .production_pair import validate_obj_pair
from .production_planarity import validate_card_planes
from .reference_match import VIEWS

MAX_PARAMETERS = 32
MAX_VALUES_PER_PARAMETER = 16
MAX_EVALUATIONS = 256
MAX_ROUNDS = 8


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return value


def _parameters(source, parameters, base_operations):
    if not isinstance(parameters, list) or not 1 <= len(parameters) <= MAX_PARAMETERS:
        raise ValueError("parameters must contain 1..32 entries")
    if not isinstance(base_operations, list) or len(base_operations) + len(parameters) > 256:
        raise ValueError("base_operations plus parameter edits cannot exceed 256")
    if not all(isinstance(op, dict) for op in base_operations):
        raise ValueError("base_operations must contain operation objects")
    json.dumps(base_operations, allow_nan=False)
    graph = SpeedTreeGraph.load(source)
    result, keys = [], set()
    for item in parameters:
        if not isinstance(item, dict) or set(item) - {
            "node_id",
            "name",
            "component",
            "initial",
            "values",
        }:
            raise ValueError("Invalid parameter descriptor")
        node, name, component = (
            item.get("node_id"),
            item.get("name"),
            item.get("component", "Value"),
        )
        if any(not isinstance(value, str) or not value for value in (node, name, component)):
            raise ValueError("Parameters require node_id, name and component strings")
        key = (node, name, component)
        if key in keys:
            raise ValueError("Duplicate parameter descriptor")
        keys.add(key)
        initial = _number(item.get("initial"), "initial")
        try:
            actual = float(graph.get_property(node, name, component))
        except (TypeError, ValueError) as exc:
            raise ValueError("Initial property is not numeric or is unavailable") from exc
        if not math.isfinite(actual) or not math.isclose(
            actual, initial, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError(f"Initial value differs from the reference project: {name}")
        values = item.get("values")
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_VALUES_PER_PARAMETER:
            raise ValueError("Each parameter needs 1..16 candidate values")
        normalized = []
        for value in [initial, *values]:
            value = _number(value, "candidate value")
            if value not in normalized:
                normalized.append(value)
        result.append(
            {
                "node_id": node,
                "name": name,
                "component": component,
                "initial": initial,
                "values": normalized,
            }
        )
    return graph, result


def _comparison(comparison):
    if not isinstance(comparison, dict) or comparison.get("status") != "diagnostic_only":
        raise ValueError("Expected a completed diagnostic four-view comparison")
    views = comparison.get("views")
    if not isinstance(views, dict) or set(views) != set(VIEWS):
        raise ValueError("Comparison requires all four named views")
    scores, references = {}, {}
    for view in VIEWS:
        data = views[view]
        if not isinstance(data, dict) or not isinstance(data.get("reference"), dict):
            raise ValueError("Comparison has incomplete reference metadata")
        score = _number(data.get("iou"), "view IoU")
        if not 0 <= score <= 1:
            raise ValueError("View IoU must be in [0, 1]")
        reference = data["reference"]
        digest = reference.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("Comparison reference SHA-256 missing or invalid")
        transform = data.get("reference_transform")
        if not isinstance(transform, dict) or not all(
            key in transform for key in ("size", "offset", "scale")
        ):
            raise ValueError("Comparison requires a reference normalization transform")
        references[view] = {
            key: reference.get(key)
            for key in ("sha256", "mode", "threshold", "crop", "foreground_bbox", "crop_size")
        }
        references[view]["reference_transform"] = transform
        scores[view] = score
    mean = sum(scores.values()) / len(VIEWS)
    reported = _number(comparison.get("mean_iou"), "mean IoU")
    if not math.isclose(mean, reported, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("Mean IoU does not match the four view scores")
    return mean, scores, references


def fit_reference_parameters(
    source_path,
    parameters,
    evaluate,
    *,
    base_operations=None,
    total_max_triangles=2000,
    card_triangles=800,
    max_evaluations=32,
    max_rounds=2,
    require_structure=True,
    card_plane_categories=None,
    plane_tolerance=0.001,
):
    """Search a finite, caller-defined parameter grid by coordinate descent.

    ``evaluate(trial_id, operations)`` must return ``full_obj_path``,
    ``bare_obj_path``, a ``comparison`` from ``compare_reference_views``, a
    ``provenance`` object whose ``verified`` is True, and, when required, a
    ``structure`` object whose ``status`` is ``passed``. The callback must
    independently verify the two native export manifests and confirm the bare
    source differs by removing only the intended card generators. Parameter
    bounds, allowed properties and structural requirements are caller supplied.
    The original source hash is monitored but this function cannot prevent an
    unsafe callback from writing to it; a changed source invalidates the run.
    """
    if not callable(evaluate):
        raise ValueError("evaluate must be callable")
    for field, value, upper in (
        ("max_evaluations", max_evaluations, MAX_EVALUATIONS),
        ("max_rounds", max_rounds, MAX_ROUNDS),
    ):
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError(f"{field} must be an integer in 1..{upper}")
    for field, value in (
        ("total_max_triangles", total_max_triangles),
        ("card_triangles", card_triangles),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if type(require_structure) is not bool:
        raise ValueError("require_structure must be boolean")
    source = Path(source_path).expanduser().resolve(strict=True)
    if source.suffix.lower() != ".spm":
        raise ValueError("A reference SPM project is required")
    if base_operations is None:
        base_operations = []
    graph, params = _parameters(source, parameters, base_operations)
    source_hash = graph.source_hash
    initial = tuple(item["initial"] for item in params)
    base = copy.deepcopy(base_operations)
    tested = {}
    trials = []
    best = None
    reference_identity = None
    invalid_reference = False
    source_changed = False
    budget_exhausted = False
    stop_reason = "round_limit"

    def test(values):
        nonlocal best, reference_identity, invalid_reference, source_changed, budget_exhausted
        check_cancelled()
        if values in tested:
            return
        if len(trials) >= max_evaluations:
            budget_exhausted = True
            return
        trial_id = f"trial_{len(trials):04d}"
        operations = copy.deepcopy(base)
        for param, value in zip(params, values):
            operations.append(
                {
                    "op": "set_property",
                    "node_id": param["node_id"],
                    "name": param["name"],
                    "component": param["component"],
                    "value": value,
                }
            )
        record = {"trial_id": trial_id, "values": list(values), "operations": operations}
        trials.append(record)
        tested[values] = record
        try:
            unchanged = _file_hash(source) == source_hash
        except OSError:
            unchanged = False
        if not unchanged:
            source_changed = True
            record["status"] = "source_changed"
            return
        try:
            evaluated = evaluate(trial_id, copy.deepcopy(operations))
            check_cancelled()
            if not isinstance(evaluated, dict):
                raise ValueError("Evaluator must return an object")
            structure = evaluated.get("structure")
            if require_structure and (
                not isinstance(structure, dict) or structure.get("status") != "passed"
            ):
                record.update(status="structure_failed", structure=structure)
                return
            provenance = evaluated.get("provenance")
            if not isinstance(provenance, dict) or provenance.get("verified") is not True:
                raise ValueError("Native export and card-removal provenance must be verified")
            json.dumps(provenance, allow_nan=False)
            geometry = validate_obj_pair(
                evaluated["full_obj_path"],
                evaluated["bare_obj_path"],
                total_max_triangles,
                card_triangles,
            )
            check_cancelled()
            record["geometry"] = geometry
            record["provenance"] = provenance
            record["structure"] = structure if require_structure else {"status": "not_required"}
            if geometry["status"] != "passed":
                record["status"] = "budget_failed"
                return
            if card_plane_categories is not None:
                planes = validate_card_planes(
                    evaluated["full_obj_path"], card_plane_categories, plane_tolerance
                )
                record["card_planes"] = planes
                if planes["status"] != "passed":
                    record["status"] = "card_planes_failed"
                    return
            mean, scores, references = _comparison(evaluated.get("comparison"))
            if reference_identity is not None and references != reference_identity:
                invalid_reference = True
                record["status"] = "reference_changed"
                return
            reference_identity = references
            record.update(
                status="eligible",
                mean_iou=mean,
                view_iou=scores,
                comparison_manifest=evaluated["comparison"].get("manifest_path"),
            )
            if best is None or mean > best["mean_iou"]:
                best = record
        except DccMcpCancelledError:
            raise
        except Exception as exc:
            record.update(
                status="evaluation_failed", error_type=type(exc).__name__, error=str(exc)[:1000]
            )
        finally:
            try:
                unchanged = _file_hash(source) == source_hash
            except OSError:
                unchanged = False
            if not unchanged:
                source_changed = True
                record["status"] = "source_changed"

    test(initial)
    for _round in range(max_rounds):
        if source_changed or invalid_reference or budget_exhausted:
            break
        before = best["mean_iou"] if best else None
        for index, param in enumerate(params):
            for value in param["values"]:
                if source_changed or invalid_reference or budget_exhausted:
                    break
                center = tuple(best["values"]) if best else initial
                proposed = list(center)
                proposed[index] = value
                test(tuple(proposed))
        if before == (best["mean_iou"] if best else None):
            stop_reason = "no_improvement"
            break
    if source_changed:
        status, winner = "source_changed", None
        stop_reason = "source_changed"
    elif invalid_reference:
        status, winner = "reference_changed", None
        stop_reason = "reference_changed"
    elif best is None:
        status, winner = "no_eligible_candidate", None
    else:
        status, winner = "candidate_selected", copy.deepcopy(best)
    if budget_exhausted and not (source_changed or invalid_reference):
        stop_reason = "evaluation_limit"
    return {
        "schema": "speedtree.reference-fit.v1",
        "status": status,
        "source": {"path": str(source), "sha256": source_hash},
        "method": "deterministic_coordinate_descent",
        "parameters": params,
        "winner": winner,
        "trials": trials,
        "evaluation_count": len(trials),
        "max_evaluations": max_evaluations,
        "stop_reason": stop_reason,
        "candidate_space_size": math.prod(len(p["values"]) for p in params),
        "candidate_space_exhausted": len(tested) == math.prod(len(p["values"]) for p in params),
        "visual_acceptance": "pending_artist_review",
        "limitations": [
            "Coordinate descent searches only caller-supplied values and may miss better combinations.",
            "Silhouette IoU requires correct masks, view mapping and camera correspondence.",
            "Paired-export provenance and structural validation are evaluator attestations.",
            "Geometry budget alone does not verify LOD, scale, textures or artistic quality.",
        ],
    }
