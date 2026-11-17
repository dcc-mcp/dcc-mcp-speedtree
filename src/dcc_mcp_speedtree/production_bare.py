"""Prepare a SpeedTree project without card generators for paired exports."""

import hashlib
import os
import tempfile
from pathlib import Path

from .graph import GraphError, SpeedTreeGraph

CARD_TYPES = {"Leaf", "Leaf Mesh", "Frond"}


def make_bare_copy(full_project, bare_project):
    """Remove card generators from a new sibling project, preserving wood.

    The output must be a sibling so existing relative asset references retain
    their location. Removal alone does not prove the exported mesh, dimensions,
    dependencies, rendering, or artistic quality; the caller must export and
    check both projects independently.
    """
    full = Path(full_project).expanduser().resolve(strict=True)
    bare_requested = Path(bare_project).expanduser()
    if bare_requested.is_symlink():
        raise ValueError("Output must not be a symbolic link")
    bare = bare_requested.parent.resolve(strict=True) / bare_requested.name
    if bare.parent != full.parent:
        raise ValueError("The bare project must be a sibling of the full project")
    if bare == full:
        raise ValueError("The bare project must differ from the full project")
    if bare.suffix.lower() != full.suffix.lower():
        raise ValueError("The bare project must preserve the document type")
    graph = SpeedTreeGraph.load(full)
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
    with tempfile.TemporaryDirectory(prefix=".speedtree-bare-", dir=bare.parent) as temp:
        staged = Path(temp) / full.name
        graph.save(staged)
        after = SpeedTreeGraph.load(staged).inspect()
        remaining = {node["id"] for node in after["generators"]}
        if remaining != set(nodes) - cards:
            raise GraphError("Unexpected generator changes while removing cards")
        if hashlib.sha256(full.read_bytes()).hexdigest() != before["source_sha256"]:
            raise GraphError("Source changed during bare project preparation")
        # link() atomically fails if the destination exists, including a
        # dangling symlink or a concurrently created file. The staging folder
        # shares the same filesystem. Unsupported filesystems fail closed.
        os.link(staged, bare)
    return {
        "status": "bare_project_prepared",
        "full_project": str(full),
        "bare_project": str(bare),
        "removed_ids": sorted(cards),
        "full_sha256": before["source_sha256"],
        "bare_sha256": after["source_sha256"],
        "method": "remove_card_generators_only",
        "limitations": [
            "Dependencies and Modeler exports must be verified independently.",
            "Geometry counts, dimensions, units, and visual quality are not verified.",
        ],
    }
