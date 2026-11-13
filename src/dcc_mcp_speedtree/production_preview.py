"""Generate labeled Blender diagnostic previews of an exported OBJ.

The executable is trusted operator configuration, never an MCP argument.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def _sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _blender():
    value = os.environ.get("DCC_MCP_BLENDER_EXECUTABLE", "")
    if not value:
        raise ValueError("Set DCC_MCP_BLENDER_EXECUTABLE to a trusted installed Blender")
    exe = Path(value).expanduser().resolve(strict=True)
    if not exe.is_file() or exe.name.casefold() not in {"blender", "blender.exe"}:
        raise ValueError("Expected the configured Blender executable")
    return exe


def _compose_review_images(folder):
    """Composite transparent diagnostic renders onto a labeled neutral background."""
    background = (238, 239, 237, 255)
    for kind in ("full", "bare"):
        views = ("front", "left", "back", "right")
        tiles = []
        for view in views:
            with Image.open(folder / f"{kind}_{view}.png") as image:
                img = image.convert("RGBA")
            tile = Image.new("RGBA", (img.width, img.height + 28), background)
            tile.alpha_composite(img, (0, 28))
            ImageDraw.Draw(tile).text(
                (10, 7), f"{kind.upper()} - {view.upper()}", fill=(20, 20, 20, 255)
            )
            tiles.append(tile)
        width, height = tiles[0].size
        contact = Image.new("RGBA", (width * 2, height * 2), background)
        for index, tile in enumerate(tiles):
            contact.alpha_composite(tile, ((index % 2) * width, (index // 2) * height))
        contact.convert("RGB").save(folder / f"{kind}_contact_sheet.png")
    with Image.open(folder / "card_closeup.png") as image:
        img = image.convert("RGBA")
    card = Image.new("RGBA", (img.width, img.height + 28), background)
    card.alpha_composite(img, (0, 28))
    ImageDraw.Draw(card).text((10, 7), "CARD CLOSEUP - DIAGNOSTIC", fill=(20, 20, 20, 255))
    card.convert("RGB").save(folder / "card_closeup_view.png")


def generate_diagnostic_views(obj_path, output_dir, material_categories, resolution=768):
    """Render full/bare orthographic views, masks, and one isolated card.

    Maps all OBJ material names to either ``wood`` or ``card``. This mapping
    is an operator assertion, not evidence of generator ownership. The output
    directory must be new. Blender 4+ is required; no source is modified.
    """
    obj = Path(obj_path).expanduser().resolve(strict=True)
    if obj.suffix.casefold() != ".obj" or not obj.is_file():
        raise ValueError("Expected an exported OBJ")
    if not isinstance(material_categories, dict) or not material_categories:
        raise ValueError("A complete explicit material-to-category mapping is required")
    if any(
        not isinstance(k, str) or not k.strip() or v not in {"wood", "card"}
        for k, v in material_categories.items()
    ):
        raise ValueError("Map each material name to wood or card")
    if set(material_categories.values()) != {"wood", "card"}:
        raise ValueError("Both wood and card categories are required")
    if type(resolution) is not int or not 128 <= resolution <= 2048:
        raise ValueError("Resolution must be 128..2048")
    output = Path(output_dir).expanduser().resolve()
    if output.exists() or output == obj.parent or output in obj.parents:
        raise ValueError("Output must be a new directory that does not contain the OBJ")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory must already exist")
    source_sha = _sha256(obj)
    worker = Path(__file__).parent / "skills/speedtree-production/scripts/_preview_worker.py"
    executable = _blender()
    with tempfile.TemporaryDirectory(prefix=".speedtree-preview-", dir=output.parent) as temp:
        stage = Path(temp) / "render"
        stage.mkdir()
        config = stage / "request.json"
        config.write_text(
            json.dumps(
                {
                    "obj": str(obj),
                    "material_categories": material_categories,
                    "resolution": resolution,
                    "source_sha256": source_sha,
                    "output": str(stage),
                }
            ),
            encoding="utf-8",
        )
        run = subprocess.run(
            [
                str(executable),
                "--background",
                "--factory-startup",
                "--disable-autoexec",
                "--python",
                str(worker),
                "--",
                str(config),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if run.returncode != 0 or not (stage / "preview-manifest.json").is_file():
            raise RuntimeError(
                "Blender diagnostic render failed: " + (run.stderr or run.stdout)[-4000:]
            )
        manifest = json.loads((stage / "preview-manifest.json").read_text(encoding="utf-8"))
        expected = {
            f"{kind}_{view}{suffix}.png"
            for kind in ("full", "bare")
            for view in ("front", "back", "left", "right")
            for suffix in ("", "_mask")
        }
        expected.add("card_closeup.png")
        if any(
            not (stage / name).is_file() or not (stage / name).stat().st_size for name in expected
        ):
            raise RuntimeError("Blender did not produce all requested diagnostic images")
        if _sha256(obj) != source_sha:
            raise ValueError("Source OBJ changed during rendering")
        _compose_review_images(stage)
        expected.update(
            {"full_contact_sheet.png", "bare_contact_sheet.png", "card_closeup_view.png"}
        )
        manifest["contact_sheet_presentation"] = (
            "Pillow neutral-background composite of Blender renders"
        )
        manifest["images"] = {name: _sha256(stage / name) for name in sorted(expected)}
        (stage / "preview-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        config.unlink()
        stage.rename(output)
    return {
        "output_dir": str(output),
        "manifest_path": str(output / "preview-manifest.json"),
        "status": "diagnostic_previews_created",
        "images": manifest["images"],
    }
