"""Audit stored generator hierarchy against explicit branch-order constraints."""

from __future__ import annotations

from .graph import SpeedTreeGraph


def validate_branch_structure(source_path, trunk_id, max_branch_order=2, max_secondary=None):
    """Check graph ancestry; stored generators are not a Modeler geometry audit.

    A primary Branch is order 1 below the designated trunk, a secondary Branch
    is order 2. Graph paths that pass through non-Branch generators still count
    Branch ancestors. Multiple parents use the greatest reachable branch order.
    """
    if not isinstance(trunk_id, str) or not trunk_id:
        raise ValueError("trunk_id is required")
    if type(max_branch_order) is not int or max_branch_order < 0:
        raise ValueError("max_branch_order must be a nonnegative integer")
    if max_secondary is not None and (type(max_secondary) is not int or max_secondary < 0):
        raise ValueError("max_secondary must be a nonnegative integer or None")
    snapshot = SpeedTreeGraph.load(source_path).inspect()
    nodes = {node["id"]: node for node in snapshot["generators"]}
    if trunk_id not in nodes or nodes[trunk_id]["type"] != "Branch":
        raise ValueError("trunk_id must identify a Branch generator")
    children = {node: [] for node in nodes}
    parents = {node: [] for node in nodes}
    indegree = dict.fromkeys(nodes, 0)
    for edge in snapshot["links"]:
        children[edge["source_id"]].append(edge["target_id"])
        parents[edge["target_id"]].append(edge["source_id"])
        indegree[edge["target_id"]] += 1
    queue = sorted(node for node in nodes if indegree[node] == 0)
    order = {trunk_id: 0}
    while queue:
        node = queue.pop(0)
        for child in children[node]:
            if node in order:
                value = order[node] + (nodes[child]["type"] == "Branch")
                order[child] = max(order.get(child, -1), value)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    branches = [
        node for node in nodes.values() if node["type"] == "Branch" and node["id"] != trunk_id
    ]
    disconnected = [node["id"] for node in branches if node["id"] not in order]
    too_deep = [
        {"id": node["id"], "name": node["name"], "order": order[node["id"]]}
        for node in branches
        if node["id"] in order and order[node["id"]] > max_branch_order
    ]
    secondary_count = sum(order.get(node["id"]) == 2 for node in branches)
    primary_count = sum(order.get(node["id"]) == 1 for node in branches)
    errors = []
    ancestors = set()
    pending = list(parents[trunk_id])
    while pending:
        node = pending.pop()
        if node not in ancestors:
            ancestors.add(node)
            pending.extend(parents[node])
    if not any(nodes[node]["type"] == "Tree" for node in ancestors):
        errors.append("The designated trunk is not connected below the Tree generator")
    if any(nodes[node]["type"] == "Branch" for node in ancestors):
        errors.append("The designated trunk has another Branch ancestor")
    if primary_count == 0:
        errors.append("No primary Branch generator found below the trunk")
    if disconnected:
        errors.append("Branch generators are not descendants of the designated trunk")
    if too_deep:
        errors.append("Branch generators exceed the maximum order")
    if max_secondary is not None and secondary_count > max_secondary:
        errors.append("Secondary Branch generator count exceeds the requested limit")
    return {
        "status": "failed" if errors else "passed",
        "trunk_id": trunk_id,
        "source_sha256": snapshot["source_sha256"],
        "max_branch_order": max_branch_order,
        "max_secondary": max_secondary,
        "primary_generators": primary_count,
        "secondary_generators": secondary_count,
        "deeper_branches": too_deep,
        "disconnected_branches": disconnected,
        "failures": errors,
        "limitations": [
            "Checks stored generator graph only, not number or appearance of generated branches.",
            "Leaf card generation, geometry budgets and visual acceptance require separate checks.",
        ],
    }
