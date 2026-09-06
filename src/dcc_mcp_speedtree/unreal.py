"""Unreal project/plugin preflight helpers."""
from __future__ import annotations
import json
from pathlib import Path

def inspect_unreal_project(project_file: str | Path) -> dict[str, object]:
    path = Path(project_file).expanduser().resolve(strict=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = {item.get("Name"): bool(item.get("Enabled")) for item in data.get("Plugins", []) if isinstance(item, dict)}
    return {"project": str(path), "engine_association": data.get("EngineAssociation"), "dcc_mcp_unreal_enabled": plugins.get("DccMcpUnreal", False), "speedtree_importer_enabled": plugins.get("SpeedTreeImporter", False), "plugins": plugins}
