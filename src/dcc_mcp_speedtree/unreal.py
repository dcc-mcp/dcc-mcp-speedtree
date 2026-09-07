"""Descriptor-only preflight; runtime plugin checks belong to the UE adapter."""

from __future__ import annotations

import json
from pathlib import Path


def inspect_unreal_project(project_file: str | Path) -> dict[str, object]:
    path = Path(project_file).expanduser().resolve(strict=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = {
        item.get("Name"): item.get("Enabled")
        for item in data.get("Plugins", [])
        if isinstance(item, dict)
    }
    return {
        "project": str(path),
        "engine_association": data.get("EngineAssociation"),
        "dcc_mcp_unreal_enabled": plugins.get("DccMcpUnreal"),
        "speedtree_importer_enabled": plugins.get("SpeedTreeImporter"),
        "plugins": plugins,
        "scope": "project_descriptor",
        "runtime_verified": False,
        "guidance": "Absent entries inherit engine defaults. Inspect installed plugin descriptors and loaded modules through dcc-mcp-unreal before configuring plugins.",
    }
