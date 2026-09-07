"""SpeedTree DCC-MCP adapter."""

from .capabilities import capability_status, inspect_asset, inspect_preset, plan_export
from .content import discover_official_content, select_samples
from .unreal import inspect_unreal_project


def __getattr__(name):
    if name == "SpeedTreeMcpServer":
        from .server import SpeedTreeMcpServer

        return SpeedTreeMcpServer
    raise AttributeError(name)


__all__ = [
    "SpeedTreeMcpServer",
    "capability_status",
    "discover_official_content",
    "inspect_asset",
    "inspect_preset",
    "inspect_unreal_project",
    "plan_export",
    "select_samples",
]
