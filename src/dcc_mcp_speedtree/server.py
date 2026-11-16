"""Official CLI service with optional exact GUI binding and a trusted UI session.

The standalone CLI stays fail-closed for all live tools. A trusted AgentHost /
plugin / MCP bootstrap may instead pass ``ui_control`` (a Core
``UiControlRuntimeOptions``) and ``ui_control_session`` (one concrete
``PixelsMcpHostClient`` that the startup owner constructed through
``create_owned_pixels_session``). The server then owns that session and gives
the seven live skill entries a bounded, read-only typed view of it. See
``docs/ui-control-bootstrap.md`` for the startup call point and contract.
"""

from __future__ import annotations

import argparse
import os
import signal
import threading
from pathlib import Path
from typing import Any

from dcc_mcp_core import DccServerOptions, MinimalModeConfig
from dcc_mcp_core.server_base import DccServerBase

from .__version__ import __version__
from .live import LiveError
from .runtime import RuntimeBinding, SpeedTreeRuntimeError, bind_runtime, process_path
from .trusted_session import BoundedLiveSession, TrustedLiveExecutionBridge

SERVER_NAME = "dcc-mcp-speedtree"
_BUILTIN = Path(__file__).parent / "skills"
_server = None


class SpeedTreeMcpServer(DccServerBase):
    def __init__(
        self,
        *,
        dcc_pid: int | None = None,
        dcc_window_handle: int | None = None,
        executable: str | None = None,
        dcc_version: str | None = None,
        binding: RuntimeBinding | None = None,
        port: int | None = None,
        ui_control: Any | None = None,
        ui_control_session: Any | None = None,
        ui_control_menu_routes: Any | None = None,
        **kwargs: Any,
    ):
        if (dcc_pid is None) != (dcc_window_handle is None):
            raise ValueError("Provide both PID and HWND or use standalone mode")
        if dcc_pid is not None and dcc_pid <= 0:
            raise ValueError("PID must be positive")
        if binding is not None:
            binding = bind_runtime(
                binding.pid,
                binding.window_handle,
                binding.executable,
                binding.version,
                binding.title,
            )
        self.binding = binding or (
            bind_runtime(dcc_pid, dcc_window_handle, executable, dcc_version) if dcc_pid else None
        )

        # Owned by this server. The trusted bootstrap may replace it with ONE
        # BoundedLiveSession below; skill scripts only ever see that bounded
        # view, never the concrete client. Initialised before super().__init__
        # so the bridge's session_provider closure is always safe to call.
        self._speedtree_bounded_session = None
        bridge = TrustedLiveExecutionBridge(
            dispatcher=None,
            session_provider=lambda: self._speedtree_bounded_session,
        )
        # Only pass ui_control when supplied, so older Core releases keep the
        # pre-existing fail-closed behaviour instead of breaking from_env.
        extra = {"ui_control": ui_control} if ui_control is not None else {}

        if self.binding is None:
            if executable:
                os.environ["DCC_MCP_SPEEDTREE_EXECUTABLE"] = executable
            from .export import modeler_executable

            modeler_executable()
            options = DccServerOptions.from_env(
                "speedtree",
                _BUILTIN,
                port=port,
                server_name=SERVER_NAME,
                server_version=__version__,
                adapter_version=__version__,
                dcc_version=dcc_version or "unknown",
                instance_type="standalone",
                execution_bridge=bridge,
                **extra,
                **kwargs,
            )
        else:
            os.environ.update(
                {
                    "DCC_MCP_SPEEDTREE_PID": str(self.binding.pid),
                    "DCC_MCP_SPEEDTREE_WINDOW_HANDLE": str(self.binding.window_handle),
                    "DCC_MCP_SPEEDTREE_EXECUTABLE": self.binding.executable,
                    "DCC_MCP_SPEEDTREE_VERSION": self.binding.version,
                    "DCC_MCP_UI_CONTROL_PROCESS_ID": str(self.binding.pid),
                    "DCC_MCP_UI_CONTROL_WINDOW_HANDLE": str(self.binding.window_handle),
                    "DCC_MCP_UI_CONTROL_UIA_PROCESS_ID": str(self.binding.pid),
                    "DCC_MCP_UI_CONTROL_UIA_WINDOW_HANDLE": str(self.binding.window_handle),
                }
            )
            options = DccServerOptions.from_env(
                "speedtree",
                _BUILTIN,
                port=port,
                server_name=SERVER_NAME,
                server_version=__version__,
                adapter_version=__version__,
                dcc_version=self.binding.version,
                instance_type="gui",
                dcc_pid=self.binding.pid,
                dcc_window_handle=self.binding.window_handle,
                dcc_window_title=self.binding.title,
                execution_bridge=bridge,
                **extra,
                **kwargs,
            )
        super().__init__(options=options)
        self._setup_live_session(ui_control, ui_control_session, ui_control_menu_routes)

    def _setup_live_session(
        self,
        ui_control: Any | None,
        ui_control_session: Any | None,
        ui_control_menu_routes: Any | None = None,
    ) -> None:
        """Validate the trusted bootstrap pair; otherwise stay fail-closed.

        A session is never accepted without an exact GUI PID/HWND binding, a
        real ``PixelsMcpHostClient`` and the SAME ``UiControlRuntimeOptions``
        the client was built from. Any mismatch raises here at startup rather
        than being silently downgraded to a usable live route.
        """
        if ui_control is None and ui_control_session is None:
            return
        if self.binding is None:
            raise LiveError(
                {
                    "error": "no_authorized_ui_route",
                    "message": "A trusted live session requires an exact GUI PID/HWND binding.",
                }
            )
        self._speedtree_bounded_session = BoundedLiveSession(
            ui_control_session,
            runtime=ui_control,
            target={
                "process_id": self.binding.pid,
                "window_handle": self.binding.window_handle,
            },
            menu_routes=ui_control_menu_routes,
        )

    def stop(self, *args, **kwargs):
        """Stop the server while retaining any failed owned cleanup for readback."""
        session = getattr(self, "_speedtree_bounded_session", None)
        try:
            if session is not None:
                session.close()
        finally:
            result = super().stop(*args, **kwargs)
        # Core re-raises its cached cleanup failure on subsequent stop calls.
        self._speedtree_bounded_session = None
        return result

    def register_builtin_actions(self, **kwargs):
        kwargs.setdefault(
            "minimal_mode",
            MinimalModeConfig(
                skills=(
                    "speedtree-discovery",
                    "speedtree-export",
                    "speedtree-nodes",
                    "speedtree-live",
                ),
                env_var_minimal="DCC_MCP_SPEEDTREE_MINIMAL",
                env_var_default_tools="DCC_MCP_SPEEDTREE_DEFAULT_TOOLS",
            ),
        )
        return super().register_builtin_actions(**kwargs)


def start_server(**kwargs):
    global _server
    if _server is None:
        _server = SpeedTreeMcpServer(**kwargs)
        _server.register_builtin_actions()
        _server.start()
    return _server


def stop_server():
    global _server
    if _server:
        _server.stop()
        _server = None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int)
    p.add_argument("--window-handle", type=int)
    p.add_argument("--executable")
    p.add_argument("--version")
    p.add_argument("--port", type=int)
    a = p.parse_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    s = start_server(
        dcc_pid=a.pid,
        dcc_window_handle=a.window_handle,
        executable=a.executable,
        dcc_version=a.version,
        port=a.port,
    )
    try:
        while not stop.wait(1):
            try:
                if s.binding:
                    process_path(s.binding.pid)
            except SpeedTreeRuntimeError:
                break
    finally:
        stop_server()


if __name__ == "__main__":
    main()
