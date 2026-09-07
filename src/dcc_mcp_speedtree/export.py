"""Official Modeler CLI export and verified portable file inventory.

Executable identity is operator configuration, never a tool-supplied shell.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from dcc_mcp_core.cancellation import DccMcpCancelledError, check_cancelled, current_job_id

from .bundle import material_dependencies, validate_mesh_header
from .process import run_modeler

FORMATS = {"st9", "st", "fbx", "obj", "abc", "usd"}


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def modeler_executable():
    value = os.environ.get("DCC_MCP_SPEEDTREE_EXECUTABLE", "")
    if not value:
        raise ValueError("Configure DCC_MCP_SPEEDTREE_EXECUTABLE with the installed Modeler path")
    path = Path(value).resolve(strict=True)
    if not path.is_file() or path.name.casefold() not in {
        "speedtree_modeler.exe",
        "speedtree_modeler",
    }:
        raise ValueError("Expected the official SpeedTree_Modeler executable")
    return path


def export_batch(source_paths, preset_path, output_dir, format="st9", timeout_seconds=300):
    """Export at most 16 distinct SPMs into new per-tree directories.

    Existing output is never overwritten. Each result preserves input identity,
    exit status, file hashes, and next-step import requirements. A zero exit alone
    does not imply a completed export or a usable target asset.
    """
    exe = modeler_executable()
    if format not in FORMATS:
        raise ValueError("Unsupported export format")
    if not isinstance(source_paths, list) or not 1 <= len(source_paths) <= 16:
        raise ValueError("Select between 1 and 16 source paths")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise ValueError("timeout_seconds must be between 1 and 600")
    sources = [Path(p).resolve(strict=True) for p in source_paths]
    if any(not p.is_file() or p.suffix.lower() != ".spm" for p in sources):
        raise ValueError("Export sources must be SPM files")
    if len({str(p).casefold() for p in sources}) != len(sources):
        raise ValueError("Duplicate source paths")
    preset = Path(preset_path).resolve(strict=True)
    if not preset.is_file() or preset.suffix.lower() != ".ini":
        raise ValueError("Export preset must be an INI file")
    from .capabilities import inspect_preset

    settings = inspect_preset(preset)["sections"].get("General", {})
    mode = settings.get("Type")
    if mode not in {"Game", "VFX"}:
        raise ValueError("Preset Type must be Game or VFX")
    if format in {"st9", "st"} and mode != "Game":
        raise ValueError("Native game formats require a Games preset")
    command = "-export_game" if mode == "Game" else "-export"
    output = Path(output_dir).resolve()
    if any(output == p.parent or output in p.parents for p in sources + [preset]):
        raise ValueError("Output must not contain the source or preset")
    source_hashes = [fingerprint(p) for p in sources]
    preset_hash = fingerprint(preset)
    exe_hash = fingerprint(exe)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "speedtree.export-batch.v1",
        "status": "running",
        "format": format,
        "exporter": {"name": exe.name, **exe_hash},
        "mode": mode,
        "preset": {"name": preset.name, **preset_hash},
        "requested_units": settings.get("TransformConvertUnit", "unknown"),
        "requested_transform": {k: v for k, v in settings.items() if k.startswith("Transform")},
        "requested_animation": {k: v for k, v in settings.items() if k.startswith("Animation")},
        "animation_validation": "requires_target_time_samples",
        "effective_units": "unverified",
        "preset_effectiveness": "requires_output_readback",
        "core_job_id": current_job_id(),
        "items": [],
        "target_validation": {"status": "not_run"},
        "requested_count": len(sources),
    }
    report_path = output / "export-manifest.json"

    def save():
        temp = report_path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temp.replace(report_path)

    save()
    for index, (source, identity) in enumerate(zip(sources, source_hashes)):
        folder = output / f"tree_{index + 1:02d}"
        folder.mkdir()
        target = folder / f"Tree_{index + 1:02d}.{format}"
        item = {
            "source": {"name": source.name, **identity},
            "status": "running",
            "mesh": target.relative_to(output).as_posix(),
            "files": [],
        }
        report["items"].append(item)
        save()
        try:
            check_cancelled()
            if (
                fingerprint(source) != identity
                or fingerprint(preset) != preset_hash
                or fingerprint(exe) != exe_hash
            ):
                raise ValueError("Input changed during batch")
            with (folder / "export.log").open("wb") as log:
                result = run_modeler(
                    [
                        str(exe),
                        command,
                        str(target),
                        str(source),
                        "-export_options",
                        str(preset),
                    ],
                    cwd=str(exe.parent),
                    stdout=log,
                    timeout=timeout_seconds,
                )
            item["exit_code"] = result.returncode
            if result.returncode != 0:
                item["status"] = "exporter_failed"
            elif not target.is_file() or not target.stat().st_size:
                item["status"] = "missing_mesh"
            elif fingerprint(source) != identity or fingerprint(preset) != preset_hash:
                item["status"] = "input_changed"
            else:
                validate_mesh_header(target)
                item["dependencies"] = material_dependencies(folder, output)
                item["status"] = "exported"
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and path.suffix != ".log":
                        if path.is_symlink() or not path.resolve().is_relative_to(output):
                            raise ValueError("Export escaped output directory")
                        item["files"].append(
                            {
                                "path": path.relative_to(output).as_posix(),
                                **fingerprint(path),
                            }
                        )
                item["dependency_validation"] = "pending_target_import"
        except subprocess.TimeoutExpired:
            item["status"] = "timeout"
        except DccMcpCancelledError:
            item["status"] = "cancelled"
        except (OSError, ValueError) as error:
            item["status"] = "failed"
            item["error_type"] = type(error).__name__
            item["error"] = (
                str(error)
                if isinstance(error, ValueError)
                else "Exporter I/O failed; inspect local export.log"
            )
        save()
        if item["status"] != "exported":
            break
    report["status"] = (
        "exported"
        if len(report["items"]) == len(sources)
        and all(i["status"] == "exported" for i in report["items"])
        else "failed"
    )
    report["requested_count"] = len(sources)
    if report["items"][-1]["status"] == "cancelled":
        report["status"] = "cancelled"
    save()
    return {**report, "manifest_path": str(report_path)}


def export_status(manifest_path):
    """Read atomic batch progress while the core job is running."""
    path = Path(manifest_path).resolve(strict=True)
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != "speedtree.export-batch.v1":
        raise ValueError("Unsupported export manifest")
    return {
        "status": report["status"],
        "core_job_id": report.get("core_job_id"),
        "requested": report["requested_count"],
        "completed": sum(item["status"] == "exported" for item in report["items"]),
        "items": [{"mesh": item["mesh"], "status": item["status"]} for item in report["items"]],
        "target_validation": {"status": "not_run"},
    }


def verify_export(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema") != "speedtree.export-batch.v1":
        raise ValueError("Unsupported export manifest")
    errors = []
    if not isinstance(report.get("items"), list) or not 1 <= len(report["items"]) <= 16:
        raise ValueError("Manifest must contain between 1 and 16 items")
    for item in report["items"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("files"), list)
            or not isinstance(item.get("mesh"), str)
        ):
            raise ValueError("Malformed manifest item")
        if item["status"] != "exported":
            errors.append(item["status"])
        files = {f["path"]: f for f in item["files"]}
        if len(files) != len(item["files"]):
            errors.append("duplicate_inventory_path")
        if item["mesh"] not in files:
            errors.append("mesh_missing_from_inventory")
        for name, expected in files.items():
            target = (path.parent / name).resolve()
            if not target.is_relative_to(path.parent):
                errors.append("path_escape")
            elif not target.is_file():
                errors.append("missing_file:" + name)
            elif fingerprint(target) != {k: expected[k] for k in ("size_bytes", "sha256")}:
                errors.append("file_changed:" + name)
        mesh = (path.parent / item["mesh"]).resolve()
        if not mesh.is_relative_to(path.parent):
            errors.append("path_escape")
        elif mesh.is_file():
            try:
                validate_mesh_header(mesh)
                material_dependencies(mesh.parent, path.parent)
            except ValueError as error:
                errors.append(str(error))
    if report.get("status") != "exported" or len(report["items"]) != report.get("requested_count"):
        errors.append("incomplete_batch")
    return {
        "verified": not errors,
        "errors": errors,
        "count": len(report["items"]),
        "target_validation": {"status": "not_run"},
        "manifest_path": str(path),
    }
