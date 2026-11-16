# Trusted UI-Control bootstrap contract (SpeedTree)

Status: **source-side wiring complete; startup-side integration and GUI
acceptance are not done.** This document is the handoff contract for the trusted
AgentHost / plugin / MCP startup owner. It does not install or configure a
plugin, start the Modeler, or perform any UI observation or input.

All Core facts below were checked against the interpreter actually used by this
checkout (`Python 3.12.10`, `dcc-mcp-core 0.20.44` installed in
`site-packages`), not inferred from a document.

## 1. Verified public API chain (Core 0.20.44)

| Step | Public symbol | Location |
| --- | --- | --- |
| Startup config | `UiControlRuntimeOptions`, `UiControlCapturePreparationOptions`, `UiControlRecordingOptions` | `dcc_mcp_core.server` (`__all__`) |
| Attach to adapter | `DccServerOptions.from_env(..., ui_control=..., execution_bridge=...)` | `dcc_mcp_core.server` |
| In-process route | `HostExecutionBridge.as_inprocess_executor`, `HostExecutionBridge.execute_script`, `ExecutionBridgeBinder` | `dcc_mcp_core.server` |
| Trusted object injection | `ExecutionBridgeBinder._with_adapter_context` | `dcc_mcp_core/_server/execution_bridge.py` |
| Script invocation | `run_skill_script` → `main(**params)` | `dcc_mcp_core/_server/inprocess_executor.py` |
| Owned pixels session | `PixelsMcpHostClient` | `dcc_mcp_core.host.cua_mcp_client` |

`HostExecutionBridge.execute_script` strips caller-supplied
`trusted_adapter_scope` / `trusted_ui_control_runtime` from `params` and
re-adds them only from trusted metadata. `run_skill_script` calls a script's
`main(**params)` in-process, so a server-owned Python object can reach the
seven `speedtree-live` entries. The earlier claim that these entries run in an
isolated JSON-only child process was **wrong** for this checkout; it was
verified by driving the real in-process executor.

`PixelsMcpHostClient.__init__` constructs `OwnedCuaMcpTransport`, calls the
public `start_task`, validates `provider=dcc-cua`, the pinned
`runtime_version` and the exact target, and retains the **runtime-issued**
`task_id` on that same stdio connection. Its `snapshot()` returns native PNG
bytes under `image_bytes`; `window_state()` returns the bound window state;
`stop()` runs `OwnedPixelsTaskCleanup`. No grant is minted by this adapter and
no opaque ID is copied between connections.

## 2. Supported bootstrap call point

The startup owner constructs **one** runtime and **one** client and passes
both to the adapter server. `start_server(**kwargs)` forwards the same
keywords.

```python
from dcc_mcp_speedtree.server import SpeedTreeMcpServer
from dcc_mcp_speedtree.trusted_session import (
    build_ui_control_runtime,
    create_owned_pixels_session,
)

runtime = build_ui_control_runtime(
    binary=r"C:\...\dcc-cua.exe",       # real, absolute, operator-pinned
    sha256="<64 lowercase hex>",        # exact digest of that binary
    runtime_version="<pinned version>", # runtime the host actually started
    journal_root=r"C:\...\journal",     # operator-owned ordinary directory
    allowed_actions=("keyboard_shortcut",),  # bounded physical-input ceiling
    window_operations=(),               # no window-state mutation
    ttl_minutes=15,
    timeout_seconds=45.0,
)

client = create_owned_pixels_session(
    runtime=runtime,
    session_id="<host-scoped id>",
    process_id=<exact PID>,
    window_handle=<exact native HWND>,
    window_title="<optional title>",
)

server = SpeedTreeMcpServer(
    dcc_pid=<exact PID>,
    dcc_window_handle=<exact native HWND>,
    ui_control=runtime,
    ui_control_session=client,
    ui_control_menu_routes={           # operator-declared menu chords
        "save": {"action": "keyboard_shortcut", "keys": "ctrl+s"},
        "revert": {"action": "keyboard_shortcut", "keys": "<declared chord>"},
    },
)
```

`create_owned_pixels_session` passes `allow_raw_input=bool(runtime.allowed_actions)`
and `dcc_type="speedtree"`. With an empty `allowed_actions` tuple no physical
input method is registered in the `start_task` grant, and every menu operation
then fails with `error=unauthorized_action`.

### Parameter contract

| Parameter | Owner | Constraint |
| --- | --- | --- |
| `binary` | startup owner | Absolute path to the real dcc-cua executable. Core rejects a relative path. |
| `sha256` | startup owner | Exactly 64 lowercase hex characters of that binary. |
| `runtime_version` | startup owner | Non-empty string, the runtime version the host actually pinned. Core's client rejects a mismatch. |
| `journal_root` | startup owner | Stable ordinary absolute directory that already exists, with **no reparse or symlink ancestor**, and **different from any recording `output_root`**. `UiControlCapturePreparationOptions.__post_init__` enforces all of this. It must **not** come from tool JSON or a business caller's ad-hoc environment. |
| `allowed_actions` / `window_operations` | startup owner | `allowed_actions` is the bounded physical-input ceiling (`PIXEL_ACTIONS`); empty grants no input. `BoundedLiveSession` requires the client's registered actions to match it. |
| `ui_control_menu_routes` | startup owner | `{"save": ..., "revert": ...}`, each a public physical action with its payload (for example `{"action": "keyboard_shortcut", "keys": "ctrl+s"}`). Both routes are required; an unknown action, an unknown payload field or a missing route is rejected at startup. |
| `ttl_minutes` | startup owner | Integer 1–60 (Core validation). |
| `timeout_seconds` | startup owner | `0 < x <= 120` (Core validation). |
| `session_id` | startup owner | Non-empty host-scoped string. |
| `process_id` / `window_handle` | startup owner | Exact positive PID and native HWND of the same bound window; checked again against `client.target`. |

`build_ui_control_runtime` reads **no** environment variable and accepts
**no** tool JSON. On a Core without these public types it raises
`LiveError(error=no_authorized_ui_route)` and every live tool stays fail-closed.

## 3. What the server does with the pair

1. `SpeedTreeMcpServer` requires an exact GUI PID/HWND binding; a session
   without one is rejected at startup, not silently downgraded.
2. It validates that the client is a real `PixelsMcpHostClient`, that
   `client.options is runtime`, that the client's registered action ceiling
   matches the runtime's `allowed_actions`, and that the client's exact target
   equals the declared PID/HWND. Any mismatch raises.
3. It creates one `BoundedLiveSession` and stores it on the **server**. A
   `TrustedLiveExecutionBridge` (a subclass of Core's `HostExecutionBridge`,
   composed with — not replacing — `ExecutionBridgeBinder._with_adapter_context`)
   strips **every** caller-supplied `trusted_*` parameter and injects that
   bounded view under `trusted_speedtree_live_session` only for the
   `speedtree-live` / `speedtree_live__*` entries.
4. `live_status` / `live_screenshot` accept **only the exact concrete**
   `BoundedLiveSession` type. A self-reported marker or a spoofed `__class__`
   is rejected. An explicit `process_id` must be a positive integer equal to
   the bound PID; a foreign, malformed or non-integer value is refused before
   any native read or output path work. `None` uses the exact bound window.
   The same concrete-type gate applies to `live_save`, `live_revert`,
   `live_apply`, `live_undo` and `live_open`.
5. The bridge requires the `speedtree-live` skill, a published physical entry
   path resolved from the shipped `tools.yaml`, and, when supplied, the exact
   action name for that script (for example `speedtree_live__live_status`). A foreign script
   with the same basename, a relative-path escape or another skill receives
   no session; Core's parent executor still owns the script lifecycle.
6. `SpeedTreeMcpServer.stop()` awaits `session.close()` → `client.stop()`
   **before** stopping the server, even if cleanup raises. Admission closure
   (a refused proof, a rebind or an expired `task_id`) is **not** cleanup:
   `close()` delegates on every call to Core's idempotent stop. Core performs
   the underlying cleanup once, returns independent success receipts and
   re-raises its cached `cleanup_unknown` / `cleanup_failed` error. The server
   retains a failed session so repeated stops preserve that failure; a stopped,
   expired or rebound session can never be reused for observation.
7. Capture never caches an observation: each call asks `snapshot()` again with
   bounded `max_depth` / `max_nodes`. A raised proof, missing/non-PNG bytes or
   truncated PNG is fatal, closes admission, and leaves no SPM, history or
   screenshot directory change behind.

**How the write entries work.** `live_save`, `live_revert`, `live_apply` and
`live_undo` take a fresh native observation, deliver the operator-declared menu
action as authorized physical input and then observe again. Three properties
are reported instead of being asserted away:

- the runtime reports the action's `effect` as `unverifiable`, and the adapter
  propagates it together with `verification_required`; a rejected delivery
  raises `error=menu_action_rejected` rather than being reported as done;
- the active document is parsed from the bound window title and is always
  returned with `active_document_verified: False`; an unparseable title is
  refused with `error=active_document_unverifiable`;
- a modal dialog cannot be observed (`pixels_only` reports
  `accessibility_available: False`), so `status()` reports
  `capabilities.modal_dialog: False` instead of claiming the window is clear.

`live_open` is **not** available on this route and refuses with
`error=open_recent_unsupported_by_exact_window_route`, naming the missing API:
a public typed DCC document-open action, or a public way to retarget the owned
task to a child dialog HWND, plus semantic targeting that `pixels_only` does not
expose.

`apply` / `undo` keep the on-disk guarantees from the transaction repair: one
atomic rename per commit, a private staging directory per call, a structured
receipt with `file_restored` / `history_retained` / `gui_state` on a failed
reload, history consumed only after the reload is confirmed, and a screenshot
failure reported as `screenshot_error` without rolling the commit back.

## 4. Precise remaining Core extension point

`ExecutionBridgeBinder._with_adapter_context` in
`dcc_mcp_core/_server/execution_bridge.py` gates trusted-object injection on:

```python
if skill_name == "ui-control" or action_name.startswith("ui_control__"):
```

That hardcoded gate cannot be extended by an adapter without a Core change.
`TrustedLiveExecutionBridge` composes the **same reviewed in-process route**
and adds an adapter-scoped, server-owned injection for `speedtree-live`; it is
not a new protocol, binder, broker, grant issuer or ID exchange.

The minimal Core change for the **Core/Host owner** to review:

1. Add a public, adapter-declared trusted-skill allowlist to
   `DccServerOptions` (for example
   `ui_control_trusted_skills: frozenset[str] = frozenset({"ui-control"})`)
   and a public trusted-context injector, so `_with_adapter_context` uses the
   declared allowlist instead of the hardcoded skill name. The adapter would
   then drop its subclass in favour of that official extension point. This is
   a Core/Host authorization decision, not something this adapter can approve.
2. Export `PixelsMcpHostClient` from `dcc_mcp_core.host.__all__`; today it is
   only importable from the submodule `dcc_mcp_core.host.cua_mcp_client`
   (the same module Core's own bundled `ui-control` scripts import).

A Core change is **not** a prerequisite for the landable local wiring in this
candidate; it only replaces the adapter-scoped composition with an official
one. No new "grant issuance" or "cross-connection redemption" protocol is
proposed.

## 5. Explicitly not done here

- Startup-side plugin integration and the actual `journal_root` selection are
  owned by the plugin maintenance thread; this document supplies the call
  point and contract only. No plugin file or global install config is changed.
- No Modeler is started, no PID/HWND from a previous session is reused, and
  no UI observation or input is performed.
- No controlled wiring regression counts as native GUI acceptance. Full GUI,
  apply/save, reload and undo/retry remain blocked on the original QA
  acceptance.
- No raw `live.ps1`, UIA / PostMessage / `PrintWindow` bridge or generic UI
  provider is restored.
