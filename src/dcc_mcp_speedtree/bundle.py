"""Inspect exported material references without leaking source-machine paths."""

import xml.etree.ElementTree as ET
from pathlib import Path


def material_dependencies(folder, bundle_root):
    """Validate explicit STMAT File references; Source is provenance, not a dependency.

    Binary format internals still require the target importer. A sidecar is
    optional; its absence never means there are no texture dependencies.
    """
    folder, bundle_root = Path(folder), Path(bundle_root)
    materials = []
    for sidecar in sorted(folder.glob("*.stmat")):
        if sidecar.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Material sidecar exceeds the inspection limit")
        try:
            root = ET.parse(sidecar).getroot()
        except ET.ParseError as error:
            raise ValueError("Malformed material sidecar") from error
        for material in root.findall("Material"):
            maps = []
            for entry in material.findall("Map"):
                name = entry.get("File")
                if not name:
                    continue
                target = (folder / name).resolve()
                if not target.is_relative_to(bundle_root.resolve()):
                    raise ValueError("Material dependency escapes bundle")
                if not target.is_file() or not target.stat().st_size:
                    raise ValueError("Missing material dependency")
                maps.append(
                    {
                        "semantic": entry.get("Name"),
                        "path": target.relative_to(bundle_root).as_posix(),
                    }
                )
            materials.append(
                {
                    "name": material.get("Name"),
                    "two_sided": material.get("TwoSided") == "1",
                    "maps": maps,
                }
            )
    return {
        "status": "sidecar_verified" if materials else "requires_target_importer",
        "materials": materials,
        "binary_references_verified": False,
    }


def validate_mesh_header(path):
    """Reject empty/wrong-format files before handing them to a DCC importer."""
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(256)
    signatures = {
        ".st9": (b"SpeedTree9",),
        ".st": (b"SpeedTree",),
        ".fbx": (b"Kaydara FBX Binary", b"; FBX"),
        ".abc": (b"Ogawa", b"\x89HDF\r\n\x1a\n"),
        ".usd": (b"PXR-USDC", b"#usda"),
        ".obj": (b"# Wavefront", b"v ", b"#"),
    }
    if path.suffix not in signatures or not header.startswith(signatures[path.suffix]):
        raise ValueError("Unexpected exported mesh format")
