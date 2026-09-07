"""Exact SpeedTree process and window binding."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


class SpeedTreeRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBinding:
    pid: int
    window_handle: int
    executable: str
    version: str
    title: str = "SpeedTree"

    def as_dict(self):
        return asdict(self)


def process_path(pid: int) -> Path:
    if pid <= 0:
        raise SpeedTreeRuntimeError("SpeedTree PID must be positive")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            raise SpeedTreeRuntimeError("SpeedTree PID is not live or cannot be inspected")
        try:
            n = wintypes.DWORD(32768)
            b = ctypes.create_unicode_buffer(n.value)
            if not k.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n)):
                raise SpeedTreeRuntimeError("SpeedTree executable identity could not be read")
            return Path(b.value).resolve()
        finally:
            k.CloseHandle(h)
    try:
        return (Path("/proc") / str(pid) / "exe").resolve(strict=True)
    except OSError as e:
        raise SpeedTreeRuntimeError("SpeedTree PID is not live") from e


def bind_runtime(
    pid: int,
    window_handle: int,
    executable: str | None = None,
    version: str | None = None,
    title: str | None = None,
    inspector=None,
) -> RuntimeBinding:
    actual = inspector.process_path(pid) if inspector else process_path(pid)
    if executable and os.path.normcase(
        str(Path(executable).expanduser().resolve(strict=True))
    ) != os.path.normcase(str(actual)):
        raise SpeedTreeRuntimeError("SpeedTree PID executable does not match requested path")
    if actual.name.casefold() not in {
        "speedtree_modeler.exe",
        "speedtree.exe",
        "speedtreemodeler.exe",
        "speedtreecinema.exe",
    }:
        raise SpeedTreeRuntimeError("Bound process is not a supported SpeedTree executable")
    if window_handle <= 0:
        raise SpeedTreeRuntimeError("SpeedTree native window handle must be positive")
    if inspector:
        inspector.validate_window(pid, window_handle)
    else:
        validate_window(pid, window_handle)
    selected = (version or os.environ.get("DCC_MCP_SPEEDTREE_VERSION", "")).strip()
    if not selected:
        m = re.search(r"(?i)[\\/]speedtree[\\/](\d+\.\d+(?:\.\d+)?)[\\/].*", str(actual))
        selected = m.group(1) if m else "unknown"
    return RuntimeBinding(
        int(pid), int(window_handle), str(actual), selected, (title or "SpeedTree")
    )


def runtime_from_env():
    try:
        return bind_runtime(
            int(os.environ["DCC_MCP_SPEEDTREE_PID"]),
            int(os.environ["DCC_MCP_SPEEDTREE_WINDOW_HANDLE"]),
            os.environ.get("DCC_MCP_SPEEDTREE_EXECUTABLE"),
            os.environ.get("DCC_MCP_SPEEDTREE_VERSION"),
        )
    except (KeyError, ValueError) as e:
        raise SpeedTreeRuntimeError(
            "DCC_MCP_SPEEDTREE_PID and DCC_MCP_SPEEDTREE_WINDOW_HANDLE are required"
        ) from e


def main():
    print(runtime_from_env().as_dict())


def validate_window(pid: int, window_handle: int) -> None:
    if os.name != "nt":
        raise SpeedTreeRuntimeError("GUI binding is supported only on Windows")
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.IsWindow.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    owner = wintypes.DWORD()
    if not user.IsWindow(window_handle):
        raise SpeedTreeRuntimeError("HWND is not live")
    user.GetWindowThreadProcessId(window_handle, ctypes.byref(owner))
    if owner.value != pid:
        raise SpeedTreeRuntimeError("HWND belongs to a different process")
