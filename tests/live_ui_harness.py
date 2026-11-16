"""Scripted dcc-cua transport for the ``speedtree-live`` production route.

No dcc-cua binary is launched, no Modeler is started and no native input is
delivered. Only ``OwnedCuaMcpTransport`` is replaced, with a transport that
answers the public MCP tool shapes; Core's own ``PixelsMcpHostClient`` code --
start-task validation, the native pixel fence, the action-result fence and
``OwnedPixelsTaskCleanup`` -- runs for real. These tests therefore exercise the
production route instead of a stand-in for it.
"""

from __future__ import annotations

import base64
import struct
import zlib
from typing import Any

from dcc_mcp_core.host.cua_mcp_client import PixelsMcpHostClient
from dcc_mcp_core.host.cua_mcp_errors import OwnedCuaMcpError
from dcc_mcp_core.host.ui_control_options import UiControlRuntimeOptions
from dcc_mcp_core.server import HostExecutionBridge

from dcc_mcp_speedtree import live
from dcc_mcp_speedtree.trusted_session import BoundedLiveSession, TrustedLiveExecutionBridge

PROVIDER = "dcc-cua"
RUNTIME_VERSION = "1.19.0"
TASK_ID = "mcp-task-1"
NATIVE_SESSION = "native-session-1"
BACKEND = "scripted-pixels"
PID = 4242
HWND = 9090
WIDTH = 4
HEIGHT = 2
TITLE = "tree.spm - SpeedTree Modeler"

NATIVE_INSTANCE = {
    "process_creation_time_100ns": 133000000000000000,
    "window_thread_id": 7712,
    "window_class_hash": 991,
    "owner_window_handle": HWND,
}

SAVE_ROUTE = {"action": "keyboard_shortcut", "keys": "ctrl+s"}
REVERT_ROUTE = {"action": "keyboard_shortcut", "keys": "ctrl+r"}
MENU_ROUTES = {"save": SAVE_ROUTE, "revert": REVERT_ROUTE}


def png_bytes(width: int = WIDTH, height: int = HEIGHT) -> bytes:

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x40\x40\x40" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def write_tree(path, value="2"):
    """Write a real gzipped SpeedTree document with one editable property."""
    import gzip

    xml = (
        '<SpeedTree Version="8"><Generators><Generator Type="Tree"><GUID>root</GUID>'
        "<Name>root</Name><Level>0</Level><Hidden>false</Hidden><Properties><SplineProperty>"
        f"<Name>Spine:Length:Absolute</Name><Value>{value}</Value></SplineProperty>"
        "</Properties></Generator></Generators></SpeedTree>"
    )
    path.write_bytes(gzip.compress(xml.encode()))
    return path


def length(path):
    """Read the editable property back through the real graph reader."""
    from dcc_mcp_speedtree.graph import SpeedTreeGraph

    props = SpeedTreeGraph.load(path).properties("root")
    return next(p for p in props if p["name"] == "Spine:Length:Absolute")["components"]["Value"]


def runtime(*, allowed_actions=("keyboard_shortcut",), window_operations=(), **overrides):
    """A real ``UiControlRuntimeOptions`` with an operator-shaped absolute path."""
    values: dict[str, Any] = {
        "binary": "C:/dcc-cua/dcc-cua.exe",
        "sha256": "0" * 64,
        "runtime_version": RUNTIME_VERSION,
        "allowed_actions": tuple(allowed_actions),
        "window_operations": tuple(window_operations),
    }
    values.update(overrides)
    return UiControlRuntimeOptions(**values)


class ScriptedTransport:
    """Speaks the owned public-MCP tool shapes; records every call."""

    def __init__(self, options: Any = None, title: str = TITLE):
        self.options = options
        self.title = title
        self.calls: list[tuple[str, dict]] = []
        self.closed = 0
        self.observation = 0
        self.stop_status = "stopped"
        self.fail_stop = False
        self.fail_action_matching: dict | None = None
        self.fail_snapshot_from: int | None = None
        self.delivery_success = True
        # Per-action delivery outcome, keyed by the declared keys/text:
        # "confirmed" (all true), "not_dispatched" (never sent),
        # "post_invalidated" (dispatched, post-dispatch validation failed),
        # "transport_error" (raised during dispatch, dispatch state unknown).
        self.action_outcomes: dict[str, str] = {}

    def _context(self) -> dict:
        return {
            "provider": PROVIDER,
            "runtime_version": RUNTIME_VERSION,
            "task_id": TASK_ID,
            "target": self._target(),
        }

    def _target(self) -> dict:
        return {"process_id": PID, "window_handle": HWND, "window_title": self.title}

    def tool(self, name: str, arguments: dict, *, cleanup: bool = False) -> dict:
        self.calls.append((name, arguments))
        if name == "start_task":
            return {
                "structuredContent": {
                    "ok": True,
                    "status": "started",
                    "provider": PROVIDER,
                    "runtime_version": RUNTIME_VERSION,
                    "task_id": TASK_ID,
                    "target": self._target(),
                    "task_context": self._context(),
                }
            }
        if name == "stop_task":
            if self.fail_stop:
                raise OwnedCuaMcpError("cleanup_failed", "scripted cleanup failure", {})
            return {
                "structuredContent": {
                    "ok": True,
                    "status": self.stop_status,
                    "provider": PROVIDER,
                    "runtime_version": RUNTIME_VERSION,
                    "task_id": TASK_ID,
                    "target": self._target(),
                    "task_context": self._context(),
                    "cleanup": {
                        "type": "session_stopped",
                        "session_id": "mcp-" + TASK_ID,
                        "success": self.stop_status == "stopped",
                        "active": False,
                        "cleanup_pending": False,
                    },
                }
            }
        method = arguments.get("method")
        if name != "dcc_cua_task_call":
            raise AssertionError(f"unexpected tool {name}")
        structured = self._method(method, arguments.get("params", {}))
        content = structured.pop("content", None)
        result: dict[str, Any] = {"structuredContent": structured}
        if content is not None:
            result["content"] = content
        return result

    def _method(self, method: str, params: dict) -> dict:
        base = {"task_context": self._context(), "target": self._target()}
        if method == "get_window_state":
            return {
                **base,
                "type": "window_state",
                "session_id": "mcp-" + TASK_ID,
                "observation_id": None,
                "accessibility_state_id": None,
                "state": {
                    "exists": True,
                    "backend": "windows-exact-native-state",
                    "dpi": 96,
                    "bounds": [0, 0, 800, 600],
                    "visible_bounds": [0, 0, 800, 600],
                    "visible": True,
                    "minimized": False,
                    "foreground": True,
                    "native_instance": dict(NATIVE_INSTANCE),
                    "process_id": PID,
                    "window_handle": HWND,
                    "window_title": TITLE,
                },
            }
        if method == "snapshot":
            self.observation += 1
            if self.fail_snapshot_from is not None and self.observation >= self.fail_snapshot_from:
                raise OwnedCuaMcpError("capture_failed", "scripted capture failure", {})
            observation_id = f"observation-{self.observation}"
            pixels = png_bytes()
            return {
                **base,
                "type": "snapshot",
                "observation_mode": "pixels_only",
                "accessibility_state_id": None,
                "observation_id": observation_id,
                "image": {"length": len(pixels)},
                "content": [
                    {
                        "type": "image",
                        "mimeType": "image/png",
                        "data": base64.b64encode(pixels).decode("ascii"),
                    }
                ],
                "observation": {
                    "observation_id": observation_id,
                    "session_id": NATIVE_SESSION,
                    "capture_provenance": self._provenance(),
                    "width": WIDTH,
                    "height": HEIGHT,
                    "source_rect": [0, 0, WIDTH, HEIGHT],
                    "capture_backend": BACKEND,
                    "process_id": PID,
                    "window_handle": HWND,
                    "window_title": TITLE,
                },
            }
        if method == "execute_action":
            action = params.get("action", {})
            for key, value in (self.fail_action_matching or {}).items():
                if action.get(key) == value:
                    raise OwnedCuaMcpError("scripted_rejection", f"scripted {value} failure", {})
            outcome = self.action_outcomes.get(
                action.get("keys") or action.get("text"),
                "confirmed" if self.delivery_success else "not_dispatched",
            )
            if outcome == "transport_error":
                raise OwnedCuaMcpError(
                    "scripted_transport_error", "scripted transport error during dispatch", {}
                )
            success = outcome == "confirmed"
            delivered = outcome in ("confirmed", "post_invalidated")
            post = outcome == "confirmed"
            return {
                **base,
                "type": "action_completed",
                "success": success,
                "result": {
                    "success": success,
                    "route": "windows_exact_pixel_final_input",
                    "native_instance": dict(NATIVE_INSTANCE),
                    "effect": "unverifiable",
                    "verification_required": True,
                    "fresh_observation_required": True,
                    "target": self._target(),
                    "delivery": {"delivery_completed": delivered, "post_dispatch_validated": post},
                },
            }
        raise AssertionError(f"unexpected method {method}")

    @staticmethod
    def _provenance() -> dict:
        return {
            "observation_mode": "pixels_only",
            "pixels_captured": True,
            "whole_desktop_capture": False,
            "accessibility_available": False,
            "backend": BACKEND,
            "window_dpi": 96,
            "capture_generation": 1,
            "native_window_bounds": [0, 0, 800, 600],
            "native_instance": dict(NATIVE_INSTANCE),
            "process_id": PID,
            "window_handle": HWND,
        }

    def close(self, *, grace_seconds: float | None = None) -> None:
        self.closed += 1

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def methods(self) -> list[str]:
        return [
            arguments.get("method") for name, arguments in self.calls if name == "dcc_cua_task_call"
        ]

    def action_keys(self) -> list[str]:
        keys = []
        for name, arguments in self.calls:
            if name != "dcc_cua_task_call" or arguments.get("method") != "execute_action":
                continue
            action = arguments.get("params", {}).get("action", {})
            keys.append(action.get("keys", action.get("text")))
        return keys


class Harness:
    """Builds a real client + real bounded session over a scripted transport."""

    def __init__(
        self,
        monkeypatch,
        *,
        allowed_actions=("keyboard_shortcut",),
        menu_routes=None,
        transport=None,
        title=TITLE,
    ):
        self.transport = transport or ScriptedTransport(title=title)
        monkeypatch.setattr(
            "dcc_mcp_core.host.cua_mcp_client.OwnedCuaMcpTransport",
            lambda options: self.transport,
        )
        self.options = runtime(allowed_actions=allowed_actions)
        self.client = PixelsMcpHostClient(
            session_id="speedtree-live-test",
            dcc_type="speedtree",
            process_id=PID,
            window_handle=HWND,
            allow_raw_input=bool(allowed_actions),
            options=self.options,
            window_title=title,
        )
        self.session = BoundedLiveSession(
            self.client,
            runtime=self.options,
            target={"process_id": PID, "window_handle": HWND},
            menu_routes=MENU_ROUTES if menu_routes is None else menu_routes,
        )


def bridge_with_session(session: Any) -> TrustedLiveExecutionBridge:
    """A real ``HostExecutionBridge`` wrapped by the adapter's trusted bridge."""
    return TrustedLiveExecutionBridge(dispatcher=None, session_provider=lambda: session)


def published_live_entry(name: str) -> str:
    """Absolute path of a published ``speedtree-live`` entry script."""
    from dcc_mcp_speedtree.trusted_session import _LIVE_SKILL_DIR

    return str(_LIVE_SKILL_DIR / "scripts" / name)


def core_executor_calls(monkeypatch, bridge, script_path, *, action_name="", params=None):
    """Run the bridge's executor while capturing what Core's parent received.

    The patch is applied BEFORE ``as_inprocess_executor()`` is called, so the
    adapter's wrapper always composes the same substituted Core executor and no
    real script is executed.
    """
    seen: dict[str, Any] = {}

    def core(_script_path, _params, **_metadata):
        seen["script_path"] = _script_path
        seen["params"] = dict(_params)
        seen["metadata"] = dict(_metadata)
        return {"ok": True}

    monkeypatch.setattr(HostExecutionBridge, "as_inprocess_executor", lambda self: core)
    bridge.as_inprocess_executor()(
        script_path, dict(params or {}), skill_name="speedtree-live", action_name=action_name
    )
    return seen


def live_error_of(fn, *args, **kwargs):
    """Call ``fn`` and return the ``LiveError`` payload it raised."""
    try:
        fn(*args, **kwargs)
    except live.LiveError as exc:
        return exc.payload
    raise AssertionError("expected a LiveError")
