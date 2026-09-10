"""Read-only, agent-facing SpeedTree capability inspection."""

from __future__ import annotations

import configparser
import hashlib
from pathlib import Path
from typing import Any

SUPPORTED_ASSET_SUFFIXES = frozenset(
    {
        ".spm",
        ".st9",
        ".st",
        ".srt",
        ".swa",
        ".ini",
        ".obj",
        ".fbx",
        ".abc",
        ".usd",
        ".usda",
        ".usdc",
        ".gltf",
        ".glb",
    }
)

_MODEL_SUFFIXES = frozenset({".spm", ".st", ".st9", ".srt"})
_SCENE_SUFFIXES = frozenset({".swa"})
_PRESET_SUFFIXES = frozenset({".ini"})
_TEXT_SUFFIXES = frozenset({".swa", ".ini", ".usda"})


def _files(root: Path, pattern: str) -> list[str]:
    return sorted(str(path.resolve()) for path in root.rglob(pattern) if path.is_file())


def discover_official_content(speedtree_root: str | Path) -> dict[str, Any]:
    """Discover installed samples and game export presets without host access."""

    root = Path(speedtree_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"SpeedTree root is not a directory: {root}")
    samples = _files(root / "samples", "*.spm") if (root / "samples").is_dir() else []
    presets_root = root / "export_presets" / "Games"
    presets = _files(presets_root, "*.ini") if presets_root.is_dir() else []
    vfx_presets = _files(root / "export_presets" / "VFX", "*.ini")
    return {
        "root": str(root),
        "samples": samples,
        "game_export_presets": presets,
        "vfx_export_presets": vfx_presets,
        "counts": {
            "samples": len(samples),
            "game_export_presets": len(presets),
            "vfx_export_presets": len(vfx_presets),
        },
    }


def _asset_kind(suffix: str) -> str:
    if suffix in _MODEL_SUFFIXES:
        return "model"
    if suffix in _SCENE_SUFFIXES:
        return "world_building"
    if suffix in _PRESET_SUFFIXES:
        return "export_preset"
    return "exported_asset"


def inspect_asset(asset_path: str | Path, *, preview_bytes: int = 512) -> dict[str, Any]:
    """Return a safe descriptor and SHA-256 fingerprint for one asset."""

    path = Path(asset_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(f"SpeedTree asset is not a file: {path}")
    suffix = path.suffix.casefold()
    if suffix not in SUPPORTED_ASSET_SUFFIXES:
        raise ValueError(f"unsupported SpeedTree asset suffix: {path.suffix or '<none>'}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    text_preview: str | None = None
    if suffix in _TEXT_SUFFIXES:
        with path.open("rb") as stream:
            text_preview = stream.read(max(0, min(preview_bytes, 4096))).decode(
                "utf-8", errors="replace"
            )
    return {
        "path": str(path),
        "name": path.name,
        "suffix": suffix,
        "kind": _asset_kind(suffix),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "text_preview": text_preview,
    }


def inspect_preset(preset_path: str | Path) -> dict[str, Any]:
    """Read an INI export preset's sections and options without applying it."""

    path = Path(preset_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(f"SpeedTree preset is not a file: {path}")
    if path.suffix.casefold() != ".ini":
        raise ValueError(f"SpeedTree export preset must be an .ini file: {path}")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        parser.read_file(stream)
    sections = {
        section: {key: value for key, value in parser.items(section)}
        for section in parser.sections()
    }
    return {
        "path": str(path),
        "name": path.name,
        "sections": sections,
        "section_names": list(sections),
        "option_count": sum(len(options) for options in sections.values()),
        "mutated": False,
    }


def plan_export(
    source_path: str | Path,
    preset_path: str | Path,
    output_dir: str | Path,
    *,
    format: str | None = None,
) -> dict[str, Any]:
    """Validate an export request and return a non-mutating execution plan."""

    from .export import FORMATS

    source = Path(source_path).expanduser().resolve()
    preset = Path(preset_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    selected = (format or "st9").casefold()
    issues = []
    if selected not in FORMATS:
        issues.append("unsupported_format")
    if not source.is_file():
        issues.append("source")
    elif source.suffix.casefold() != ".spm":
        issues.append("source_must_be_spm")
    if not preset.is_file():
        issues.append("preset")
    elif preset.suffix.casefold() != ".ini":
        issues.append("preset_must_be_ini")
    else:
        mode = inspect_preset(preset)["sections"].get("General", {}).get("Type")
        if mode not in {"Game", "VFX"} or (selected in {"st", "st9"} and mode != "Game"):
            issues.append("incompatible_preset")
    if output.exists():
        issues.append("output_already_exists")
    if any(output in item.parents for item in [source, preset]):
        issues.append("output_contains_input")
    return {
        "ready": not issues,
        "requires_operator_action": bool(issues),
        "missing": issues,
        "source": str(source),
        "preset": str(preset),
        "output_dir": str(output),
        "format": selected,
        "steps": [
            "review source and preset",
            "export_batch",
            "verify_export",
            "target adapter import and readback",
        ],
        "mutated": False,
    }


def capability_status() -> dict[str, Any]:
    """Describe implementation coverage, without implying a live host probe."""

    integration = "unavailable"
    return {
        "schema": "speedtree.capabilities.v1",
        "scope": "file_authoring_export_and_handoff",
        "full_modeler_coverage": False,
        "live_probe_performed": False,
        "read_only_research": "available",
        "content_discovery": "available",
        "asset_inspection": "available",
        "export_planning": "available",
        "live_in_process": "integration_unavailable",
        "live_integration": integration,
        "mutating_operations": "official_cli_export_and_copy_on_write_graph_edit",
        "batch_export": "available_with_configured_modeler",
        "authoritative_live_completion": "integration_unavailable",
        "features": {
            "batch_export": {
                "implementation": "supported",
                "route": "speedtree_export__export_batch",
                "formats": ["st9", "st", "fbx", "obj", "abc", "usd"],
                "requires": "configured licensed Modeler, existing SPM and preset, new output",
            },
            "progress": {
                "implementation": "supported",
                "route": "speedtree_export__export_status",
                "limit": "per-tree progress, not vendor internal percentage",
            },
            "cancellation": {
                "implementation": "supported_via_core",
                "route": "DELETE /v1/jobs/{id} on the owning service",
                "limit": "active owned child only; no reconstruction after service restart",
            },
            "materials": {
                "implementation": "export_and_sidecar_inspection_only",
                "route": "speedtree_export__export_batch",
                "limit": "no Modeler material editing or target shader reconstruction",
            },
            "lod": {
                "implementation": "preset_driven_export_only",
                "route": "speedtree_discovery__inspect_preset",
                "limit": "no generator or LOD editing; target must read back actual LODs",
            },
            "wind": {
                "implementation": "preset_driven_request_only",
                "route": "speedtree_export__export_batch",
                "limit": "wind preset requests and serialized generator edits are not proof of animated output; no Fan editing",
            },
            "collision": {
                "implementation": "not_implemented",
                "limit": "no collision authoring or post-conversion collision validation",
            },
            "modeling": {
                "implementation": "experimental_file_graph_authoring",
                "route": "speedtree_nodes__edit_graph",
                "official_interface": "not_documented_in_reviewed_modeler_cli",
                "operations": [
                    "add",
                    "duplicate",
                    "remove",
                    "connect",
                    "disconnect",
                    "rename",
                    "set_hidden",
                    "set_property",
                ],
                "limit": (
                    "SPM/STT file graph edits require Modeler reload and regeneration; "
                    "the observed XML format is not a published authoring SDK; "
                    "no live document or individual generated-node editing"
                ),
            },
            "target_import": {
                "implementation": "handoff_only",
                "route": "speedtree_export__plan_import",
                "limit": "destination adapter owns import, plugin consent, and acceptance",
            },
        },
    }
