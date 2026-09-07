"""Target-neutral import handoff with explicit destination validation."""

import json
from pathlib import Path

from .export import fingerprint, verify_export

TARGET_FORMATS = {
    "unreal": {"st9", "st", "fbx", "obj", "abc", "usd"},
    "blender": {"fbx", "obj", "abc", "usd"},
    "maya": {"fbx", "obj", "abc", "usd"},
    "3dsmax": {"fbx", "obj", "abc", "usd"},
    "houdini": {"fbx", "obj", "abc", "usd"},
    "unity": {"st9", "st", "fbx", "obj", "abc", "usd"},
}


def plan_import(manifest_path, target):
    """Produce a handoff, not a claim that a target plugin is installed."""
    if target not in TARGET_FORMATS:
        raise ValueError("Unknown target adapter")
    check = verify_export(manifest_path)
    if not check["verified"]:
        raise ValueError("Bundle verification failed")
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["format"] not in TARGET_FORMATS[target]:
        raise ValueError("No import route for this native format; export an interchange format")
    return {
        "schema": "speedtree.import-plan.v1",
        "target": target,
        "format": manifest["format"],
        "manifest": {"path": str(path), **fingerprint(path)},
        "meshes": [str(path.parent / item["mesh"]) for item in manifest["items"]],
        "bundle_root": str(path.parent),
        "target_status": "requires_capability_discovery",
        "plugin_configuration": "requires_target_plan_and_user_consent",
        "replace_existing": False,
        "required_readback": [
            "geometry",
            "material_maps",
            "opacity",
            "lods",
            "wind_animation",
            "instances",
            "units_axes",
            "missing_dependencies",
        ],
        "mutated": False,
    }
