"""Compatibility helpers for official SpeedTree content discovery."""

from collections.abc import Iterable
from pathlib import Path

from .capabilities import discover_official_content

__all__ = ["discover_official_content", "select_samples"]


def select_samples(
    content: dict[str, list[str]],
    names: Iterable[str] = ("Pine.spm", "Broadleaf_Forest.spm", "Palm.spm"),
) -> list[str]:
    wanted = tuple(names)
    selected = [path for path in content.get("samples", []) if Path(path).name in wanted]
    missing = [name for name in wanted if not any(Path(path).name == name for path in selected)]
    if missing:
        raise FileNotFoundError("official SpeedTree samples missing: " + ", ".join(missing))
    return selected
