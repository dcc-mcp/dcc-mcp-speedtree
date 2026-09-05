"""Discover official SpeedTree samples and export presets without touching the host."""
from pathlib import Path
from typing import Iterable

def discover_official_content(speedtree_root: str | Path) -> dict[str, list[str]]:
    root = Path(speedtree_root).expanduser().resolve(strict=True)
    return {
        "samples": sorted(str(p) for p in (root / "samples").rglob("*.spm")),
        "game_export_presets": sorted(str(p) for p in (root / "export_presets" / "Games").glob("*.ini")),
    }

def select_samples(content: dict[str, list[str]], names: Iterable[str] = ("Pine.spm", "Broadleaf_Forest.spm", "Palm.spm")) -> list[str]:
    wanted = tuple(names)
    selected = [path for path in content.get("samples", []) if Path(path).name in wanted]
    missing = [name for name in wanted if not any(Path(path).name == name for path in selected)]
    if missing:
        raise FileNotFoundError("official SpeedTree samples missing: " + ", ".join(missing))
    return selected
