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
| `ui_control_menu_routes` | startup owner | `{"save": ..., "revert": ...}`, each a public physical action with its payload (for example `{"action": "keyboard_shortcut", "keys": "ctrl+s"}`). **Declaring routes is optional and neither route is required for startup.** A read-only startup (empty `allowed_actions`, no routes) still constructs the session and serves `live_status` / `live_screenshot`. An unknown action or an unknown payload field is still rejected at startup; a route that is simply absent is refused later, when that menu operation is used (`error=menu_route_undeclared`), before any physical input is sent. |
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

**How the write entries work.** `live_save` and `live_revert` validate an
explicit `process_id` against the bound window first, take a fresh native
observation, deliver the operator-declared menu action as authorized physical
input and then observe again. `live_apply` and `live_undo` validate the PID first
too, but both are **fail-closed** on the implemented pixels-only route: `apply`
delivers only the SAVE and then refuses its dependent edit, and `undo` refuses
at the active-document binding gate before dispatching ANY input. The input is
**bounded physical foreground input** in the exact bound window; nothing here
edits in the background, and there is no raw PowerShell / UI Automation /
PostMessage / PrintWindow route. Before the first real observation or input, report the actual
route attestation for that task: `provider=dcc-cua`, the runtime version, the
exact PID and the exact native HWND. The connection, task and observation
references belong to the individual owned task and are kept with it; they are not
a single gate for a whole round and not a recipe for a new permission grant.
Delivery and effect are reported separately, because they are different facts:

- **Delivery** is a data check, not an exception check. Core's client returns a
  boolean `structuredContent` result and raises nothing for a refused action, so
  `success` / `delivery_completed` / `post_dispatch_validated` are each required
  to be exactly `True`. Anything else raises `error=save_not_confirmed`,
  `revert_not_confirmed` or `reload_not_confirmed`, and `live_apply` checks the
  save **before** creating history, staging an edit or touching the document. A
  transport-level rejection still surfaces as `error=menu_action_rejected`.
- **A false completion flag is not proof that nothing was dispatched.** The
  runtime's physical input fence accumulates `requested_events` / `inserted_events`
  and keeps `delivery_completed` false until every dispatch, cleanup and
  post-check passes, so a partial insertion reports false while real input
  already reached the window. Every delivery therefore carries a `dispatch`
  classification — `delivered`, `delivered_unverified`, `partial`,
  `unknown_dispatch` or `not_dispatched` — and only `not_dispatched` is treated
  as proved, which requires either an adapter-owned boundary that refused before
  `execute` was entered or the runtime's own action-stage evidence
  (`pre_dispatch` phase, `action_attempted` false, or `input_sent` `not_sent`,
  with `completion` `known`, `effect_unknown` false and no contradictory
  mutation or event count). Compensation and backup deletion are gated on that
  proof; every uncertain state preserves the file and the only backup.
- **`live_apply` refuses its dependent phase on this route.** The entry requires
  a source-bound save confirmation — a project-route acknowledgement with
  explicit application semantics, correct process/document binding and
  verifiable provenance proving that the bound Modeler saved its current GUI
  edits into **this** document. The implemented pixels-only client reports the
  save effect as `unverifiable` and exposes no such confirmation, so `live_apply`
  returns `error=save_prerequisite_unverified` with `disk_mutation: false` and
  `history_mutation: false`, **before** the business-file edit, the history
  snapshot and the reload — even when the file's mtime or its content hash
  changed. A file observation is still reported, as a diagnostic with
  `authority: "none"`: it shows that the disk changed, not that the bound
  Modeler saved into that document. No automatic retry, and no synthesized
  acknowledgement. This is a reported adapter capability gap
  (`save_effect_verifier: NOT_AVAILABLE`), not full real-time co-design
  acceptance and not a statement that the public protocol lacks the ability.
- **Effect** stays unverified. The runtime reports every delivered physical
  action's `effect` as `unverifiable`, and the only same-task observations
  available are native pixels and window state — neither proves the Modeler
  applied a menu command. Results therefore carry
  `verification.status: "unknown"` with `established_by: null`. Taking another
  screenshot is observation, not effect verification.
- **`live_undo` is fail-closed on the active-document binding.** The route can
  only report a best-effort document *name* from the bound window title; the
  scoped-target status declares `active_document_path: False` and
  `active_document_verified: False` and exposes no full canonical path bound to
  the exact PID/HWND. A caller path therefore cannot be positively matched to
  the open document, and a same-name document in another directory cannot be
  excluded. `live_undo` returns
  `error=active_document_binding_unverified` with `disk_mutation: false`,
  `history_mutation: false` and `reload_dispatch: false`, **before** any history
  read, disk replacement, reload dispatch or output work. No caller boolean,
  title basename, transport/test attribute, historical snapshot, file mtime or
  content hash is accepted as a substitute. This is a reported adapter
  capability gap (`active_document_path_verifier: NOT_AVAILABLE`), not full
  real-time co-design acceptance and not a claim that the public protocol or
  another host lacks document semantics. The required interface is a typed,
  process/document-bound observation of the FULL canonical active-document path
  from the exact scoped target, with verifiable provenance.
- The guarded transaction code is retained for a route that does provide that
  observation. The earlier guarantees are unchanged for it: backups are not
  spent on an unverified reload (`undo_depth`), recovery is reported with
  `file_restored` / `history_retained` / `gui_state`, and nothing sets
  `effect="verified"` or adds a self-reported flag. On the implemented
  pixels-only route that code is unreachable, so no snapshot is consumed.
- The active document is parsed from the bound window title and is always
  returned with `active_document_verified: False`; an unparseable title is
  refused with `error=active_document_unverifiable`.
- A modal dialog cannot be observed (`pixels_only` reports
  `accessibility_available: False`), so `status()` reports
  `capabilities.modal_dialog: False` instead of claiming the window is clear.

`live_open` is **not** available on this route and refuses with
`error=open_recent_unsupported_on_pixels_only_route`. The limitation is the
supported startup configuration, not a file-dialog HWND: File > Recents is a
menu of the same bound window, and `OwnedCuaMcpTransport.rpc` / `.tool` is a
generic public-protocol transport, so neither is the blocker. What is missing is
element targeting — `UiControlRuntimeOptions` accepts only `owned_mcp_pixels`
with `pixels_only`, `PixelsMcpHostClient` is the only public host client, and it
rejects `element_token` / `element_index`, refuses a semantic observation
(`node_count` 0) and leaves `invoke_menu` unsupported. The needed contract is a
public semantic-capable host client (or another `observation_mode` /
`transport` value), element targeting in the adapter client, or a typed DCC
document-open action.

`apply` / `undo` keep the on-disk guarantees from the transaction repair: one
atomic rename per commit, a private staging directory per call, a structured
receipt with `file_restored` / `history_retained` / `gui_state` when a reload is
not delivered (including disk compensation and keeping the sole backup when
compensation itself fails), and a screenshot failure reported as
`screenshot_error` without rolling the commit back. On the implemented
pixels-only route BOTH entries stop before that phase: `apply` at the save
prerequisite, `undo` at the active-document binding gate. No disk compensation,
history write, restore, reload or screenshot is exercised there. The retained
transaction engine runs only on a route that provides both a source-bound save
confirmation and a source-bound full active-document path observation.

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
