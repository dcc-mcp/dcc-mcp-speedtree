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
_REQUIRED_MENU_ROUTES: tuple[str, ...] = ()


def _validate_menu_routes(menu_routes: Any) -> dict[str, dict[str, Any]]:
    """Validate operator-declared menu routes without inventing a protocol.

    A route is one physical action with the payload fields the public protocol
    accepts. ``PIXEL_ACTIONS`` is imported from Core, so an unknown action name
    is refused here rather than being forwarded to the runtime.

    Declaring routes is OPTIONAL. A read-only startup (empty
    ``allowed_actions``, no menu routes) must still be able to construct a
    session and use ``status()`` / ``capture()``; the presence of a route is
    enforced where it is actually needed, in ``BoundedLiveSession.menu``.
    """
    from dcc_mcp_core.host.ui_control_options import PIXEL_ACTIONS

    if menu_routes is None:
        menu_routes = {}
    if not isinstance(menu_routes, Mapping):
        raise LiveError(
            {"error": "invalid_menu_routes", "message": "menu_routes must be a mapping."}
        )
    validated: dict[str, dict[str, Any]] = {}
    for name, route in menu_routes.items():
        if not isinstance(name, str) or not isinstance(route, Mapping):
            raise LiveError(
                {
                    "error": "invalid_menu_routes",
                    "message": "Each menu route must be a named mapping.",
                }
            )
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


# The runtime reports every delivered physical action's application effect as
# "unverifiable". The only same-task observations Core 0.20.44 exposes are
# native pixels and window state, and neither proves the Modeler applied a menu
# command, so an unverified effect is reported as unknown -- never upgraded to
# success and never silently turned into a failure that triggers compensation.
_UNVERIFIED_EFFECT_REASON = (
    "The runtime reports the physical action's effect as unverifiable. Native "
    "pixels and window state are the only same-task observations available and "
    "neither proves the Modeler applied the menu command."
)


def delivery_confirmed(result: Any) -> bool:
    """Whether the runtime confirmed the physical action was actually DELIVERED.

    A structured ``success: false``, or a ``delivery_completed`` /
    ``post_dispatch_validated`` that is not exactly ``True``, is a failed or
    unknown delivery and must be refused. No exception is required for that:
    Core's client returns a boolean result rather than raising. This says
    nothing about the application EFFECT, which stays unverified either way.
    """
    return classify_delivery(result) == DISPATCH_DELIVERED


# Dispatch classification. A false completion flag is NOT affirmative evidence
# that nothing was sent: the runtime's physical input fence accumulates
# requested/inserted events and keeps ``delivery_completed`` false until every
# dispatch, cleanup and post-check has passed, so a partial insertion reports
# false while real input already reached the window. Only ``not_dispatched``
# proves zero input, and it requires affirmative action-stage evidence -- never
# a transport label and never an inference from false booleans. Every other
# non-confirmed state may already have been executed, so recovery material must
# be preserved instead of being spent on a blind compensating restore.
DISPATCH_DELIVERED = "delivered"
DISPATCH_NOT_DISPATCHED = "not_dispatched"
DISPATCH_DELIVERED_UNVERIFIED = "delivered_unverified"
DISPATCH_PARTIAL = "partial"
DISPATCH_UNKNOWN = "unknown_dispatch"

# Affirmative action-stage evidence from the runtime's own typed error details
# (``ComputerUseErrorDetails``), serialised snake_case: pre-dispatch phase, no
# action attempted, or no input sent -- with completion KNOWN and the effect
# explicitly NOT unknown, and no contradictory mutation or event count.
_NO_DISPATCH_PHASES = frozenset({"pre_dispatch"})
_NO_DISPATCH_INPUT = frozenset({"not_sent"})
_POSSIBLE_INPUT = frozenset({"sent", "unknown"})
_CONTRADICTORY_MUTATIONS = ("mutation_attempted", "focus_mutation_attempted")
_EVIDENCE_KEYS = ("delivery", "native_outcome", "details", "native_evidence", "native_error")


def _evidence_views(result: Any) -> list[Mapping]:
    """Every bounded place a result may carry runtime action-stage evidence."""
    if not isinstance(result, Mapping):
        return []
    views: list[Mapping] = [result]
    for key in _EVIDENCE_KEYS:
        nested = result.get(key)
        if isinstance(nested, Mapping):
            views.append(nested)
            for inner in _EVIDENCE_KEYS:
                deep = nested.get(inner)
                if isinstance(deep, Mapping):
                    views.append(deep)
    return views


def _evidence(views: list[Mapping], key: str) -> Any:
    for view in views:
        if key in view:
            return view[key]
    return None


def _affirmative_no_dispatch(views: list[Mapping]) -> bool:
    """Whether the runtime affirmatively reports that no input was dispatched."""
    phase = _evidence(views, "phase")
    attempted = _evidence(views, "action_attempted")
    input_sent = _evidence(views, "input_sent")
    affirmative = (
        (isinstance(phase, str) and phase.lower() in _NO_DISPATCH_PHASES)
        or attempted is False
        or (isinstance(input_sent, str) and input_sent.lower() in _NO_DISPATCH_INPUT)
    )
    if not affirmative:
        return False
    # The runtime must also state that the outcome is KNOWN and that the effect
    # is not unknown; absent or contradictory values leave the state unproven.
    if _evidence(views, "completion") != "known" or _evidence(views, "effect_unknown") is not False:
        return False
    for key in _CONTRADICTORY_MUTATIONS:
        if _evidence(views, key) is True:
            return False
    for key in ("inserted_events", "cleanup_inserted_events"):
        inserted = _evidence(views, key)
        if isinstance(inserted, int) and inserted > 0:
            return False
    return True


def _partial_dispatch(views: list[Mapping]) -> bool:
    """Whether the evidence shows input that may already have been executed."""
    requested = _evidence(views, "requested_events")
    inserted = _evidence(views, "inserted_events")
    if isinstance(requested, int) and isinstance(inserted, int) and 0 < inserted < requested:
        return True
    for key in _CONTRADICTORY_MUTATIONS:
        if _evidence(views, key) is True:
            return True
    input_sent = _evidence(views, "input_sent")
    return isinstance(input_sent, str) and input_sent.lower() in _POSSIBLE_INPUT


def _classify_uncertain(views: list[Mapping]) -> str:
    if _affirmative_no_dispatch(views):
        return DISPATCH_NOT_DISPATCHED
    if _partial_dispatch(views):
        return DISPATCH_PARTIAL
    return DISPATCH_UNKNOWN


def classify_delivery(result: Any) -> str:
    """Classify a structured action result by what reached the window.

    ``delivered`` — success, delivery_completed and post_dispatch_validated are
    all exactly ``True``.

    ``delivered_unverified`` — ``delivery_completed`` is ``True``: input was
    dispatched, but success or post-dispatch validation is not ``True``. The
    command may already have been executed.

    ``not_dispatched`` — the runtime affirmatively reports no input, or an
    adapter-owned boundary refused before ``execute`` was entered. This is the
    only classification that licenses a compensating restore.

    ``partial`` — a false completion flag accompanied by evidence of real input
    (fewer inserted than requested events, a mutation attempt, or input marked
    sent/unknown). Possibly executed.

    ``unknown_dispatch`` — nothing in the data establishes the dispatch state.
    """
    if not isinstance(result, Mapping):
        return DISPATCH_UNKNOWN
    success = result.get("success")
    delivered = result.get("delivery_completed")
    post = result.get("post_dispatch_validated")
    if success is True and delivered is True and post is True:
        return DISPATCH_DELIVERED
    if delivered is True:
        return DISPATCH_DELIVERED_UNVERIFIED
    return _classify_uncertain(_evidence_views(result))


def classify_execution_error(exc: BaseException) -> str:
    """Classify a dispatch-time failure from the runtime's own stage evidence.

    An exception alone never proves a non-dispatch: a transport error, timeout
    or rejected call can occur after the physical input was inserted, and a
    failed post-check keeps ``delivery_completed`` false without meaning zero
    input. Only affirmative action-stage evidence establishes it.
    """
    evidence = native_error_evidence(exc)
    return _classify_uncertain(_evidence_views(evidence))


def pre_dispatch_refusal(error: str, *, boundary: str, **fields: Any) -> LiveError:
    """A refusal proven to have happened BEFORE any physical input was sent.

    The proof is the boundary itself: these checks run in the adapter, on this
    side of the client, so ``execute`` is never entered and no transport call
    carrying input is made. That, and not a completion flag, is what makes the
    non-dispatch positively known.
    """
    payload = {
        "error": error,
        "dispatch": DISPATCH_NOT_DISPATCHED,
        "no_dispatch_proof": {
            "boundary": boundary,
            "kind": "adapter_owned_pre_execute_boundary",
            "execute_entered": False,
        },
        "gui_state": "unchanged",
        **fields,
    }
    return LiveError(payload)


def native_error_evidence(exc: BaseException) -> dict[str, Any]:
    """Project a Core error for truthful classification, inventing nothing."""
    evidence: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        evidence["code"] = code
    native = getattr(exc, "native_evidence", None)
    if isinstance(native, Mapping):
        evidence["native_evidence"] = dict(native)
    fresh = getattr(exc, "fresh_observation_required", None)
    if fresh is not None:
        evidence["fresh_observation_required"] = bool(fresh)
    return evidence


def capture_failure_evidence(exc: BaseException) -> dict[str, Any]:
    """Retain only Core's bounded safe fields from an actual owned MCP error."""
    try:
        from dcc_mcp_core.host.cua_mcp_errors import OwnedCuaMcpError, safe_failure_evidence
    except ImportError:
        # Older supported Core versions may have only the legacy error shape.
        return {}
    if not isinstance(exc, OwnedCuaMcpError):
        return {}
    native = exc.native_evidence
    return safe_failure_evidence(native) if isinstance(native, dict) else {}


# Typed action-stage fields the runtime may report. Only these keys, and only
# with these value types, are copied into an adapter result: no free text, no
# title, no path, no payload, and nothing a caller could use as a grant.
_STAGE_BOOLS = (
    "action_attempted",
    "mutation_attempted",
    "focus_mutation_attempted",
    "effect_unknown",
)
_STAGE_INTS = ("requested_events", "inserted_events", "cleanup_inserted_events")
_STAGE_ENUMS = {
    "phase": _NO_DISPATCH_PHASES
    | {
        "action_dispatch",
        "local_mutation_dispatch",
        "activation_dispatch",
        "upstream_session_refresh",
        "evidence_dispatch",
    }
}
_STAGE_ENUMS["input_sent"] = _NO_DISPATCH_INPUT | _POSSIBLE_INPUT
_STAGE_ENUMS["completion"] = frozenset({"known", "unknown"})


def _action_stage_evidence(result: Any) -> dict[str, Any]:
    """Typed action-stage fields of a structured result, projected by type."""
    evidence: dict[str, Any] = {}
    for view in _evidence_views(result):
        for key in _STAGE_BOOLS:
            value = view.get(key)
            if type(value) is bool:
                evidence[key] = value
        for key in _STAGE_INTS:
            value = view.get(key)
            if type(value) is int and 0 <= value < 2**32:
                evidence[key] = value
        for key, allowed in _STAGE_ENUMS.items():
            value = view.get(key)
            if isinstance(value, str) and value.lower() in allowed:
                evidence[key] = value.lower()
    if evidence:
        evidence["stage_evidence_provenance"] = "runtime_action_stage_fields"
    return evidence


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
        raise LiveError(
            {"error": "invalid_target", "message": "session_id must be a non-empty string"}
        )
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
                {
                    "error": "invalid_target",
                    "message": "An exact positive PID and HWND binding is required.",
                }
            )
        bound = client.target
        if bound.get("process_id") != pid or bound.get("window_handle") != hwnd:
            raise LiveError(
                {
                    "error": "invalid_target",
                    "message": "The owned client is not bound to the declared PID/HWND.",
                }
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
        """Refuse an action the trusted runtime ceiling does not authorize.

        This runs before ``execute`` is entered, so nothing was dispatched.
        """
        if action not in self._runtime.allowed_actions:
            raise pre_dispatch_refusal(
                "unauthorized_action",
                boundary="allowed_actions_ceiling",
                action=action,
                allowed_actions=list(self._runtime.allowed_actions),
                message=(
                    f"The trusted UI Control runtime does not authorize the physical "
                    f"action {action!r}. The startup owner must add it to "
                    "UiControlRuntimeOptions.allowed_actions."
                ),
            )

    def _menu_route(self, name: Any) -> dict[str, Any]:
        route = self._menu_routes.get(name)
        if not isinstance(route, dict):
            raise pre_dispatch_refusal(
                "menu_route_undeclared",
                boundary="menu_route_declaration",
                menu=name,
                declared_routes=sorted(self._menu_routes),
                message=(
                    f"No trusted physical route is declared for '{name}'. The startup "
                    "owner must pass it in menu_routes; pixels_only cannot read the menu."
                ),
            )
        return dict(route)

    def menu(self, name: Any) -> dict[str, Any]:
        """Deliver one operator-declared menu operation as authorized input.

        Core's ``PixelsMcpHostClient.execute`` requires a FRESH native
        observation taken immediately beforehand and reports the action's
        ``effect`` as ``unverifiable`` with ``verification_required``. Both are
        propagated: this method never converts an unverifiable delivery into a
        claimed success, and it never reads or fakes a menu tree.

        Everything before the ``try`` is an adapter-owned boundary: it runs on
        this side of the client, so no input can have been dispatched when one
        of those checks refuses. Only the ``try`` block can leave input in an
        uncertain state, and even then a false ``delivery_completed`` is not
        treated as proof of zero input -- the runtime keeps that flag false for
        a partial insertion too.
        """
        self._require_open()
        route = self._menu_route(name)
        self._require_action(route["action"])
        try:
            self.capture()  # fresh native observation; execute() consumes it
        except Exception as exc:
            # Observation is not input, and this is still before execute(): no
            # physical input was dispatched, which the boundary proves without
            # relying on any completion flag from the runtime.
            raise pre_dispatch_refusal(
                "pre_dispatch_observation_failed",
                boundary="fresh_observation_before_execute",
                menu=name,
                action=route["action"],
                original_error=f"{type(exc).__name__}: {exc}",
                message=(
                    f"The fresh native observation before the {name} action failed "
                    f"({exc}). No physical input was dispatched; refusing before any "
                    "action is sent."
                ),
            ) from exc
        try:
            raw = self._client.execute({**route, "input_kind": "raw_input"})
        except Exception as exc:
            # A rejected delivery invalidates the local mutation evidence; the
            # owned task itself stays open until the owner closes it. The
            # dispatch state follows the runtime's own action-stage evidence. An
            # exception by itself proves nothing: a transport error, timeout or
            # rejected call can happen after input was inserted, so only
            # affirmative no-dispatch evidence yields "not_dispatched".
            dispatch = classify_execution_error(exc)
            raise LiveError(
                {
                    "error": "menu_action_rejected",
                    "menu": name,
                    "action": route["action"],
                    "dispatch": dispatch,
                    "native_error": native_error_evidence(exc),
                    "gui_state": "unknown",
                    "message": (
                        f"The owned dcc-cua task rejected the {name} action ({exc}). The "
                        f"dispatch state is {dispatch}: the command may already have been "
                        "executed, so nothing is claimed about the Modeler state and no "
                        "automatic compensation may be inferred from this failure."
                    ),
                }
            ) from exc
        result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
        delivery = result.get("delivery") if isinstance(result.get("delivery"), dict) else {}
        outcome = {
            "menu": name,
            "action": route["action"],
            "process_id": self._target["process_id"],
            "provider": _PROVIDER,
            "runtime_version": self._runtime.runtime_version,
            "target": self._client.target,
            "success": raw.get("success"),
            "delivery_completed": delivery.get("delivery_completed"),
            "post_dispatch_validated": delivery.get("post_dispatch_validated"),
            "effect": raw.get("effect", "unverifiable"),
            "verification_required": raw.get("verification_required", True),
            "fresh_observation_required": raw.get("fresh_observation_required", True),
            "verification": {
                "status": "unknown",
                "effect": raw.get("effect", "unverifiable"),
                "evidence": ["delivery_completed", "post_dispatch_validated", "native_pixels"],
                "reason": _UNVERIFIED_EFFECT_REASON,
            },
        }
        # Action-stage evidence the runtime may attach (requested/inserted event
        # counts, phase, input state) is projected by type only, so a false
        # completion flag can be told apart from a partial insertion and no free
        # text, path or payload is ever copied through.
        outcome.update(_action_stage_evidence(result))
        outcome["dispatch"] = classify_delivery(outcome)
        return outcome

    def unsupported_open_recent(self, path: Any) -> LiveError:
        """The exact missing contract for opening a file, stated precisely.

        The limitation is the OBSERVATION MODE and the absence of element
        targeting on the adapter's supported startup route -- not a file-dialog
        HWND. File > Recents is a menu of the SAME bound window, so it does not
        inherently require another window, and the owned public-MCP transport
        (``OwnedCuaMcpTransport.rpc`` / ``.tool``) is a generic protocol
        transport that is not itself pixels-limited; the connected Host owns the
        real grants. What Core 0.20.44 exposes to an adapter is the constraint:
        ``UiControlRuntimeOptions`` accepts only ``owned_mcp_pixels`` with
        ``pixels_only``, and ``PixelsMcpHostClient`` is the only public host
        client -- it refuses element tokens, refuses a semantic observation
        (``node_count`` 0) and leaves ``invoke_menu`` unsupported. Without
        element targeting there is no supported way to locate or activate a
        recents entry; guessing pixel coordinates is not a document contract.
        """
        return LiveError(
            {
                "error": "open_recent_unsupported_on_pixels_only_route",
                "path": str(path),
                "capability": "open_recent",
                "route": "owned_mcp_pixels / pixels_only",
                "available_primitives": [
                    "physical input at declared pixel coordinates (click / keypress / type)",
                    "native pixel observation and exact window state",
                ],
                "missing_contract": [
                    "a public semantic-capable host client, or an observation_mode/transport value other than owned_mcp_pixels + pixels_only in UiControlRuntimeOptions",
                    "element targeting in the adapter client (element_token / element_index are rejected today)",
                    "or a typed DCC document-open action on the owned task",
                ],
                "evidence": [
                    "dcc_mcp_core/host/ui_control_options.py: __post_init__ requires transport == 'owned_mcp_pixels' and observation_mode == 'pixels_only'",
                    "dcc_mcp_core/host/cua_mcp_client.py: execute() rejects element_token / element_index / accessibility_state_id / secret_handle",
                    "dcc_mcp_core/host/cua_mcp_client.py: snapshot() rejects semantic observation, node_count is 0, invoke_menu maps to _unsupported",
                    "dcc_mcp_core/host/cua_mcp_transport.py: OwnedCuaMcpTransport.rpc/tool is a generic public-protocol transport, so the transport is not the limit",
                ],
                "not_claimed": [
                    "File > Recents does not inherently require a different file-dialog HWND; the earlier wording was wrong",
                    "no assumption that the dcc-cua task protocol lacks a semantic method when the Host grants one",
                ],
                "message": (
                    "Opening a recent file needs element targeting, which the supported "
                    "pixels-only startup route does not expose. Use dcc-cua / DCC-MCP "
                    "ui-control to open the document, then continue with the live tools."
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
            raise pre_dispatch_refusal(
                "session_stopped",
                boundary="session_lifecycle",
                message="The owned dcc-cua task has been stopped or expired.",
            )
        # Rebind check on EVERY call, not just at construction.
        if (
            not isinstance(self._client.options, Runtime)
            or self._client.options is not self._runtime
        ):
            self._closed = True
            raise pre_dispatch_refusal(
                "session_rebind_rejected",
                boundary="session_lifecycle",
                message="The owned session was rebound; refusing to reuse it.",
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
                    "message": "The owned dcc-cua task rejected the window-state proof: {}".format(
                        exc
                    ),
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
            raw = self._client.snapshot(
                max_depth=_SNAPSHOT_MAX_DEPTH, max_nodes=_SNAPSHOT_MAX_NODES
            )
        except Exception as exc:
            self._closed = True
            evidence = capture_failure_evidence(exc)
            raise LiveError(
                {
                    "error": "capture_proof_rejected",
                    "message": "The owned dcc-cua task rejected the capture proof: {}".format(exc),
                    **({"native_evidence": evidence} if evidence else {}),
                }
            ) from exc
        pixels = raw.get("image_bytes")
        if (
            not isinstance(pixels, (bytes, bytearray))
            or len(pixels) < 24
            or bytes(pixels[:8]) != _PNG_MAGIC
        ):
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
            effective = {
                key: value for key, value in params.items() if not str(key).startswith("trusted_")
            }
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
