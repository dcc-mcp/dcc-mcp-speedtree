"""Trusted, server-owned UI-Control session for the ``speedtree-live`` skill.

This is the adapter-side half of the Core 0.20.44 trusted runtime path. It is
built from public Core APIs, verified against the actually installed
``dcc-mcp-core 0.20.44`` rather than inferred from documentation:

* ``dcc_mcp_core.server.UiControlRuntimeOptions`` and
  ``UiControlCapturePreparationOptions`` -- the trusted startup configuration;
  ``DccServerOptions.from_env(ui_control=...)`` already accepts it.
* ``dcc_mcp_core.host.cua_mcp_client.PixelsMcpHostClient`` -- one concrete
  client owning a single stdio connection (``OwnedCuaMcpTransport``), the
  public ``start_task`` call and the runtime-issued ``task_id``. Core's own
  bundled ``ui-control`` scripts import this class from the same module.
* ``dcc_mcp_core.server.HostExecutionBridge.as_inprocess_executor`` and
  ``ExecutionBridgeBinder`` / ``SkillCatalog.set_in_process_executor`` -- the
  reviewed in-process execution route. Core injects server-owned trusted
  objects there, and ``HostExecutionBridge.execute_script`` strips the
  caller-supplied ``trusted_adapter_scope`` / ``trusted_ui_control_runtime``
  params before re-adding them from trusted metadata. This adapter's bridge
  strips EVERY caller-supplied ``trusted_*`` param before injecting its own
  bounded session.

The trusted AgentHost / plugin / MCP bootstrap builds ONE
``UiControlRuntimeOptions`` and ONE ``PixelsMcpHostClient`` and passes them to
``SpeedTreeMcpServer``. From then on the SERVER owns that client and exposes
ONLY this bounded typed view to the seven in-process skill entries. Reading
(``status`` / ``capture``) is always available; menu operations are delivered as
authorized PHYSICAL INPUT against a fresh native observation, gated by the
runtime's own ``allowed_actions`` ceiling and by an operator-declared menu
route. Core reports every such action's ``effect`` as ``unverifiable``, which is
propagated instead of being claimed as success. Rebind, raw session stop and
cleanup are NOT exposed to skill scripts: ``close()`` is owner-only.

No value is read from tool JSON, ``os.environ`` or a business caller's ad-hoc
environment. The precise missing public extension point in Core 0.20.44 is the
hardcoded gate at
``dcc_mcp_core/_server/execution_bridge.py:67`` (`ExecutionBridgeBinder`
``._with_adapter_context``): it injects ``trusted_ui_control_runtime`` only for
``ui-control`` / ``ui_control__*`` skills. ``TrustedLiveExecutionBridge`` below
composes (never replaces) that reviewed route with an adapter-scoped extension
for ``speedtree-live``. On a Core without these public APIs every live tool
stays fail-closed.

This module is NOT a ``UiRoute`` protocol, a global binder, a generic broker,
a client-reported authorization scheme or a grant/ID exchange. It never reads
private grant fields and never copies an opaque ID between connections.

Four adapter-side boundaries are enforced here: ``live._require_session``
accepts only the exact ``BoundedLiveSession`` type; ``require_target`` refuses
a caller-supplied PID that is not the bound PID; ``close()`` always delegates
to Core's idempotent ``stop()`` and keeps its truthful cached outcome, even
after an admission refusal; and ``TrustedLiveExecutionBridge`` injects the
session only when the catalog identity AND a published physical entry path
both match. None of these requires a Core change.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from dcc_mcp_core.server import HostExecutionBridge

from .live import TRUSTED_SESSION_PARAM, LiveError

_PROVIDER = "dcc-cua"
_SNAPSHOT_MAX_DEPTH = 1
_SNAPSHOT_MAX_NODES = 1
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# The shipped catalog is the authority for which physical scripts belong to
# this adapter's live skill. It is package data, never caller-supplied tool JSON.
_LIVE_SKILL_DIR = Path(__file__).resolve().parent / "skills" / "speedtree-live"
_LIVE_CATALOG = _LIVE_SKILL_DIR / "tools.yaml"
_EXPECTED_LIVE_ENTRIES = 7

# Physical-input payload fields the public pixels protocol accepts for each
# action, mirroring ``PixelsMcpHostClient.execute``'s allow-list.
_ACTION_PAYLOAD_FIELDS = ("intent", "delivery_mode", "x", "y", "keys", "text", "button")
_KEYED_ACTIONS = frozenset({"keypress", "keyboard_shortcut", "type", "type_chars"})
_COORDINATE_ACTIONS = frozenset({"click", "double_click", "right_click", "move", "drag", "toggle"})

# Menu operations the live flow needs, and the physical route the startup owner
# must declare for each. There is no built-in guess: the Modeler exposes no
# scripting API and pixels_only cannot read a menu, so the chord has to come
# from the trusted bootstrap, never from tool JSON or an environment variable.
_REQUIRED_MENU_ROUTES = ("save", "revert")


def _validate_menu_routes(menu_routes: Any) -> dict[str, dict[str, Any]]:
    """Validate operator-declared menu routes without inventing a protocol.

    A route is one physical action with the payload fields the public protocol
    accepts. ``PIXEL_ACTIONS`` is imported from Core, so an unknown action name
    is refused here rather than being forwarded to the runtime.
    """
    from dcc_mcp_core.host.ui_control_options import PIXEL_ACTIONS

    if menu_routes is None:
        menu_routes = {}
    if not isinstance(menu_routes, Mapping):
        raise LiveError({"error": "invalid_menu_routes", "message": "menu_routes must be a mapping."})
    validated: dict[str, dict[str, Any]] = {}
    for name, route in menu_routes.items():
        if not isinstance(name, str) or not isinstance(route, Mapping):
            raise LiveError({"error": "invalid_menu_routes", "message": "Each menu route must be a named mapping."})
        action = route.get("action")
        if action not in PIXEL_ACTIONS:
            raise LiveError(
                {
                    "error": "invalid_menu_routes",
                    "menu": name,
                    "message": f"Menu route '{name}' must use one of the public physical actions.",
                }
            )
        if any(key not in _ACTION_PAYLOAD_FIELDS for key in route if key != "action"):
            raise LiveError(
                {
                    "error": "invalid_menu_routes",
                    "menu": name,
                    "message": "Menu routes may only carry public physical-input payload fields.",
                }
            )
        if action in _KEYED_ACTIONS and not str(route.get("keys", route.get("text", ""))).strip():
            raise LiveError(
                {
                    "error": "invalid_menu_routes",
                    "menu": name,
                    "message": f"Menu route '{name}' needs a non-empty keys/text payload.",
                }
            )
        if action in _COORDINATE_ACTIONS and not (
            isinstance(route.get("x"), int) and isinstance(route.get("y"), int)
        ):
            raise LiveError(
                {
                    "error": "invalid_menu_routes",
                    "menu": name,
                    "message": f"Menu route '{name}' needs integer x/y pixel coordinates.",
                }
            )
        validated[name] = dict(route)
    missing = [name for name in _REQUIRED_MENU_ROUTES if not validated.get(name)]
    if missing:
        raise LiveError(
            {
                "error": "menu_routes_incomplete",
                "missing_routes": missing,
                "message": (
                    "The trusted bootstrap must declare the physical route for "
                    f"{', '.join(missing)}; pixels_only cannot read the Modeler menu."
                ),
            }
        )
    return validated


@lru_cache(maxsize=1)
def _published_live_entry_paths() -> frozenset[Path]:
    """Resolve the seven published physical ``speedtree-live`` entry scripts.

    Only a path that resolves to one of these real files belongs to this skill.
    Resolving the actual path rejects a foreign file with the same basename, a
    relative ``source_file`` that escapes the shipped directory and a symlink
    that points outside it. A missing or malformed catalog fails closed.
    """
    try:
        text = _LIVE_CATALOG.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    names = re.findall(r"^\s*source_file:\s*(\S+)\s*$", text, re.MULTILINE)
    paths = frozenset((_LIVE_SKILL_DIR / name).resolve() for name in names)
    if len(names) != _EXPECTED_LIVE_ENTRIES or len(paths) != _EXPECTED_LIVE_ENTRIES:
        return frozenset()
    return paths


def _is_published_live_entry(script_path: Any) -> bool:
    """Whether an ABSOLUTE script path resolves to a published live entry.

    The real catalog always hands the reviewed route an absolute path. A
    relative path is refused outright: accepting one would make admission
    depend on the process working directory, which is caller-controlled.
    """
    try:
        candidate = Path(script_path)
    except (OSError, TypeError, ValueError):
        return False
    if not candidate.is_absolute():
        return False
    try:
        return candidate.resolve() in _published_live_entry_paths()
    except (OSError, RuntimeError, ValueError):
        return False


def _core_ui_types():
    """Import the public Core types lazily.

    Older Core releases keep the pre-existing fail-closed behaviour instead of
    breaking the whole package at import time.
    """
    try:
        from dcc_mcp_core.host.cua_mcp_client import PixelsMcpHostClient
        from dcc_mcp_core.server import UiControlCapturePreparationOptions, UiControlRuntimeOptions
    except ImportError as exc:  # pragma: no cover - depends on installed Core
        raise LiveError(
            {
                "error": "no_authorized_ui_route",
                "message": (
                    "The installed dcc-mcp-core does not expose the public "
                    "UiControlRuntimeOptions / PixelsMcpHostClient trusted runtime "
                    "path (requires >= 0.20.44); live tools stay fail-closed."
                ),
            }
        ) from exc
    return UiControlRuntimeOptions, UiControlCapturePreparationOptions, PixelsMcpHostClient


def build_ui_control_runtime(
    *,
    binary: str,
    sha256: str,
    runtime_version: str,
    journal_root: Any,
    allowed_actions: tuple = (),
    window_operations: tuple = (),
    ttl_minutes: int = 15,
    timeout_seconds: float = 45.0,
):
    """Trusted startup owner's call point for the startup configuration.

    Every value is an explicit operator-owned argument. This helper reads NO
    environment variable and accepts NO tool JSON. ``binary`` must be the real
    absolute dcc-cua executable path, ``sha256`` its exact digest, and
    ``runtime_version`` the runtime the startup owner actually pinned.

    ``journal_root`` must be chosen and validated by the AgentHost / plugin /
    MCP startup owner: a stable ordinary absolute directory with no reparse or
    symlink ancestors, separate from any recording output root. Core's
    ``UiControlCapturePreparationOptions`` enforces those properties in
    ``__post_init__``; this helper deliberately does not invent a second
    validator or read a caller-controlled env var.
    """
    Runtime, CapturePreparation, _ = _core_ui_types()
    preparation = CapturePreparation(journal_root=journal_root)
    return Runtime(
        binary=binary,
        sha256=sha256,
        runtime_version=runtime_version,
        allowed_actions=tuple(allowed_actions),
        window_operations=tuple(window_operations),
        ttl_minutes=ttl_minutes,
        timeout_seconds=timeout_seconds,
        capture_preparation=preparation,
    )


def create_owned_pixels_session(
    *,
    runtime: Any,
    session_id: str,
    process_id: int,
    window_handle: int,
    window_title: str | None = None,
):
    """Trusted bootstrap only: construct ONE concrete ``PixelsMcpHostClient``.

    This is the supported startup-side call point. It is never called by a
    skill script and never with tool JSON. ``allow_raw_input`` follows the
    runtime's own ``allowed_actions`` ceiling: an empty tuple registers no
    physical input method in the ``start_task`` grant at all, so a read-only
    runtime stays read-only. The client retains the runtime-issued ``task_id``
    on its own stdio connection. This function does not mint a grant and does
    not copy an ID between connections.
    """
    Runtime, _, PixelsClient = _core_ui_types()
    if not isinstance(runtime, Runtime):
        raise LiveError(
            {
                "error": "no_authorized_ui_route",
                "message": "create_owned_pixels_session requires a trusted UiControlRuntimeOptions.",
            }
        )
    if not isinstance(session_id, str) or not session_id:
        raise LiveError({"error": "invalid_target", "message": "session_id must be a non-empty string"})
    return PixelsClient(
        session_id=session_id,
        dcc_type="speedtree",
        process_id=process_id,
        window_handle=window_handle,
        allow_raw_input=bool(runtime.allowed_actions),
        options=runtime,
        window_title=window_title,
    )


class BoundedLiveSession:
    """Read-only typed view over ONE server-owned ``PixelsMcpHostClient``.

    Only ``status()`` and ``capture()`` are exposed to skill scripts.
    ``live._require_session`` accepts this exact concrete type, so a forged
    object, a self-reported marker or a spoofed ``__class__`` cannot pass;
    ``TrustedLiveExecutionBridge`` strips every caller-supplied ``trusted_*``
    argument before reaching a script anyway. ``close()`` is owner-only.
    """

    def __init__(
        self,
        client: Any,
        *,
        runtime: Any,
        target: Mapping[str, Any],
        menu_routes: Any = None,
    ):
        Runtime, _, PixelsClient = _core_ui_types()
        if not isinstance(client, PixelsClient):
            raise LiveError(
                {
                    "error": "no_authorized_ui_route",
                    "message": "A trusted live session requires a real server-owned PixelsMcpHostClient.",
                }
            )
        if not isinstance(runtime, Runtime) or client.options is not runtime:
            raise LiveError(
                {
                    "error": "session_rebind_rejected",
                    "message": "The owned client was built from a different trusted runtime configuration.",
                }
            )
        if bool(runtime.allowed_actions) != bool(getattr(client, "_actions", ())):
            raise LiveError(
                {
                    "error": "session_action_ceiling_mismatch",
                    "message": (
                        "The owned client's registered physical actions do not match the "
                        "runtime's allowed_actions ceiling."
                    ),
                }
            )
        pid = target.get("process_id")
        hwnd = target.get("window_handle")
        if type(pid) is not int or pid <= 0 or type(hwnd) is not int or hwnd <= 0:
            raise LiveError(
                {"error": "invalid_target", "message": "An exact positive PID and HWND binding is required."}
            )
        bound = client.target
        if bound.get("process_id") != pid or bound.get("window_handle") != hwnd:
            raise LiveError(
                {"error": "invalid_target", "message": "The owned client is not bound to the declared PID/HWND."}
            )
        self._client = client
        self._runtime = runtime
        self._target = {"process_id": pid, "window_handle": hwnd}
        self._menu_routes = _validate_menu_routes(menu_routes)
        self._closed = False

    @property
    def bound_process_id(self) -> int:
        """The exact PID this session is bound to."""
        return self._target["process_id"]

    def _require_action(self, action: Any) -> None:
        """Refuse an action the trusted runtime ceiling does not authorize."""
        if action not in self._runtime.allowed_actions:
            raise LiveError(
                {
                    "error": "unauthorized_action",
                    "action": action,
                    "allowed_actions": list(self._runtime.allowed_actions),
                    "message": (
                        f"The trusted UI Control runtime does not authorize the physical "
                        f"action {action!r}. The startup owner must add it to "
                        "UiControlRuntimeOptions.allowed_actions."
                    ),
                }
            )

    def _menu_route(self, name: Any) -> dict[str, Any]:
        route = self._menu_routes.get(name)
        if not isinstance(route, dict):
            raise LiveError(
                {
                    "error": "menu_route_undeclared",
                    "menu": name,
                    "declared_routes": sorted(self._menu_routes),
                    "message": (
                        f"No trusted physical route is declared for '{name}'. The startup "
                        "owner must pass it in menu_routes; pixels_only cannot read the menu."
                    ),
                }
            )
        return dict(route)

    def menu(self, name: Any) -> dict[str, Any]:
        """Deliver one operator-declared menu operation as authorized input.

        Core's ``PixelsMcpHostClient.execute`` requires a FRESH native
        observation taken immediately beforehand and reports the action's
        ``effect`` as ``unverifiable`` with ``verification_required``. Both are
        propagated: this method never converts an unverifiable delivery into a
        claimed success, and it never reads or fakes a menu tree.
        """
        self._require_open()
        route = self._menu_route(name)
        self._require_action(route["action"])
        self.capture()  # fresh native observation; execute() consumes it
        try:
            raw = self._client.execute({**route, "input_kind": "raw_input"})
        except Exception as exc:
            # A rejected delivery invalidates the local mutation evidence; the
            # owned task itself stays open until the owner closes it.
            raise LiveError(
                {
                    "error": "menu_action_rejected",
                    "menu": name,
                    "action": route["action"],
                    "message": f"The owned dcc-cua task rejected the {name} action: {exc}",
                }
            ) from exc
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
        return {
            "menu": name,
            "action": route["action"],
            "process_id": self._target["process_id"],
            "provider": _PROVIDER,
            "runtime_version": self._runtime.runtime_version,
            "target": self._client.target,
            "success": raw.get("success"),
            "effect": raw.get("effect", "unverifiable"),
            "verification_required": raw.get("verification_required", True),
            "fresh_observation_required": raw.get("fresh_observation_required", True),
            "delivery_completed": delivery.get("delivery_completed"),
            "post_dispatch_validated": delivery.get("post_dispatch_validated"),
        }

    def unsupported_open_recent(self, path: Any) -> LiveError:
        """The exact missing public API for opening a file, stated precisely.

        The owned task is bound to ONE exact PID/HWND -- ``UiControlRuntimeOptions``
        carries a single binary/target and ``PixelsMcpHostClient._check_target``
        rejects a response for any other window -- so a native file dialog is a
        different window the task may not target. ``pixels_only`` observation
        also reports ``accessibility_available: False`` and
        ``whole_desktop_capture: False``, so a menu cannot be read, enumerated or
        targeted. Core 0.20.44 offers no typed "open this file in the bound DCC"
        action. Needed: either a public typed DCC document-open action, or a
        public API to retarget/extend the owned task to a child dialog HWND with
        its own authorization scope.
        """
        return LiveError(
            {
                "error": "open_recent_unsupported_by_exact_window_route",
                "path": str(path),
                "capability": "open_recent",
                "missing_api": [
                    "a public typed DCC document-open action on the owned ui-control task",
                    "or a public API to retarget the owned task to a child dialog HWND",
                    "and semantic/accessibility targeting (pixels_only exposes none)",
                ],
                "evidence": [
                    "dcc_mcp_core/host/ui_control_options.py: UiControlRuntimeOptions binds one binary and one target",
                    "dcc_mcp_core/host/cua_mcp_client.py: PixelsMcpHostClient._check_target rejects another window",
                    "dcc_mcp_core/host/cua_mcp_client.py: snapshot() requires accessibility_available is False",
                ],
                "message": (
                    "Opening a file is not available on the exact-window pixels-only route: "
                    "the owned task cannot target the file dialog and cannot read the menu. "
                    "Use dcc-cua / DCC-MCP ui-control to open the document, then continue."
                ),
            }
        )

    @property
    def closed(self) -> bool:
        return self._closed

    def require_target(self, process_id: Any = None) -> None:
        """Validate an explicit request PID before any native read or output work.

        ``None`` means "use the exact bound window". A supplied PID must be a
        positive, exact integer equal to the PID this session is bound to; a
        foreign, malformed or non-integer value is refused without contacting
        the owned task and without creating output paths.
        """
        if process_id is None:
            return
        if (
            type(process_id) is not int
            or process_id <= 0
            or process_id != self._target["process_id"]
        ):
            raise LiveError(
                {
                    "error": "invalid_target",
                    "message": (
                        "An explicit process_id must be a positive integer matching "
                        "the exact bound window."
                    ),
                    "bound_process_id": self._target["process_id"],
                }
            )

    def _require_open(self) -> None:
        Runtime, _, _ = _core_ui_types()
        if self._closed or not getattr(self._client, "task_id", None):
            raise LiveError(
                {"error": "session_stopped", "message": "The owned dcc-cua task has been stopped or expired."}
            )
        # Rebind check on EVERY call, not just at construction.
        if not isinstance(self._client.options, Runtime) or self._client.options is not self._runtime:
            self._closed = True
            raise LiveError(
                {"error": "session_rebind_rejected", "message": "The owned session was rebound; refusing to reuse it."}
            )

    def status(self) -> dict[str, Any]:
        """Exact-target window state via the public typed ``window_state()``."""
        self._require_open()
        try:
            raw = self._client.window_state()
        except Exception as exc:
            self._closed = True
            raise LiveError(
                {
                    "error": "window_state_rejected",
                    "message": "The owned dcc-cua task rejected the window-state proof: {}".format(exc),
                }
            ) from exc
        return {
            "provider": _PROVIDER,
            "runtime_version": self._runtime.runtime_version,
            "observation_mode": self._runtime.observation_mode,
            "target": self._client.target,
            "window_state": raw.get("state", raw),
            "instances": [self._client.target],
            "scope": "exact_bound_window_only",
            "capabilities": {
                "window_state": True,
                "native_pixels": True,
                "accessibility_tree": False,
                "file_recents": False,
                "active_document_path": False,
                "active_document_from_title": True,
                "active_document_verified": False,
                "modal_dialog": False,
                "ui_input": bool(self._runtime.allowed_actions),
                "menu_routes": sorted(self._menu_routes),
            },
        }

    def capture(self) -> dict[str, Any]:
        """Request a FRESH native pixel observation via public ``snapshot()``.

        No observation is cached here: every call asks the owned client for a
        new one. Core's client rejects a repeated ``observation_id``, a
        semantic/accessibility snapshot, a whole-desktop capture, missing
        pixel provenance, invalid geometry, occlusion/overlay evidence and
        anything other than exactly one native PNG, then stops the owned task.
        Those rejections are propagated as fatal ``LiveError``; a safe
        refusal is never reported as a successful screenshot.
        """
        self._require_open()
        try:
            raw = self._client.snapshot(max_depth=_SNAPSHOT_MAX_DEPTH, max_nodes=_SNAPSHOT_MAX_NODES)
        except Exception as exc:
            self._closed = True
            raise LiveError(
                {
                    "error": "capture_proof_rejected",
                    "message": "The owned dcc-cua task rejected the capture proof: {}".format(exc),
                }
            ) from exc
        pixels = raw.get("image_bytes")
        if not isinstance(pixels, (bytes, bytearray)) or len(pixels) < 24 or bytes(pixels[:8]) != _PNG_MAGIC:
            self._closed = True
            raise LiveError(
                {
                    "error": "capture_proof_rejected",
                    "message": "The owned task did not return a complete native PNG.",
                }
            )
        return {
            "image_bytes": bytes(pixels),
            "observation_id": raw.get("observation_id"),
            "observation": raw.get("observation"),
            "provider": _PROVIDER,
            "runtime_version": self._runtime.runtime_version,
            "target": self._client.target,
        }

    def close(self) -> dict[str, Any]:
        """Close admission and delegate cleanup to Core, including repeat calls.

        Core owns the cached failure and independent success receipts, and
        performs the underlying task stop and transport close only once.
        """
        self._closed = True
        return self._client.stop()


class TrustedLiveExecutionBridge(HostExecutionBridge):
    """Adapter-scoped extension of Core's reviewed in-process route.

    ``ExecutionBridgeBinder._with_adapter_context`` wraps whatever
    ``as_inprocess_executor()`` returns and injects Core's own trusted
    ``ui-control`` metadata. This subclass composes (never replaces) that
    injection: it strips EVERY caller-supplied ``trusted_*`` param, then
    injects the server-owned ``BoundedLiveSession`` under
    ``TRUSTED_SESSION_PARAM`` only when BOTH the catalog identity
    (``speedtree-live`` / ``speedtree_live__*``) and a published physical
    entry path from the shipped ``tools.yaml`` match. A foreign script that
    merely claims the skill name, uses the same basename, or escapes through a
    relative path receives no session, while Core's parent executor is still
    called with the original path and metadata.

    The injected object is a live reference to the SERVER's own attribute,
    captured in a closure. There is no global slot, no public ``bind()``, no
    broker and no client-reported authorization. A caller cannot forge it
    through tool JSON because every ``trusted_*`` key is removed first.
    """

    def __init__(self, *args, **kwargs):
        session_provider: Callable[[], Any] | None = kwargs.pop("session_provider", None)
        super().__init__(*args, **kwargs)
        if session_provider is not None and not callable(session_provider):
            raise TypeError("session_provider must be callable")
        self._session_provider = session_provider

    def as_inprocess_executor(self):
        core = super().as_inprocess_executor()

        def executor(script_path, params, **metadata):
            effective = {key: value for key, value in params.items() if not str(key).startswith("trusted_")}
            skill_name = str(metadata.get("skill_name") or "")
            action_name = str(metadata.get("action_name") or "")
            if (
                skill_name == "speedtree-live"
                and _is_published_live_entry(script_path)
                and action_name in ("", "speedtree_live__" + Path(script_path).stem)
            ):
                provider = self._session_provider
                session = provider() if provider is not None else None
                if session is not None and not session.closed:
                    effective[TRUSTED_SESSION_PARAM] = session
            return core(script_path, effective, **metadata)

        return executor
