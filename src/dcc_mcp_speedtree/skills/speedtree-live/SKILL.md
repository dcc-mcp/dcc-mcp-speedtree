---
name: speedtree-live
description: Bound live session with the SpeedTree Modeler window the user is watching - observe it and deliver a configured revert command through the owned dcc-cua / DCC-MCP ui-control route, with every application effect reported as unverified and no background, keyboard-free or headless editing promise.
license: MIT
metadata:
  dcc-mcp:
    dcc: speedtree
    layer: domain
    version: "0.1.0"
    tools: tools.yaml
    search-hint: "SpeedTree live modeler revert screenshot undo co-design collaborate GUI window"
---

# Bound live session with the Modeler

The user watches a running SpeedTree Modeler (Windows). The Modeler has no
scripting API. Observation and input go through the project-owned **dcc-cua /
DCC-MCP `ui-control`** route only: one owned, integrity-pinned runtime task bound
to an **exact PID and native window handle**, with a bounded physical-input
ceiling and real Host authorization. Input is **bounded physical foreground
input** in that exact window — it is **not** a background, headless,
mouse-and-keyboard-free edit, and there is no raw PowerShell / UI Automation /
PostMessage / PrintWindow fallback. Nothing here reads a grant from tool JSON,
from a business caller's environment, or from a self-reported flag.

Before the first real observation or input, report the actual route attestation
for that task: `provider=dcc-cua`, the runtime version, the exact PID and the
exact native HWND. Keep the connection, task and observation references issued
for that individual task; they are per-task and are not a single gate for a whole
round, and they are not a recipe for a new permission grant.

Without the trusted server-owned session every entry fails closed with
`error=no_authorized_ui_route`.

## What each entry actually does

1. `live_status` reports the bound window state, the active document and the
   capability view. The active document comes from the bound window **title** and
   is reported as **unverified**; `pixels_only` exposes no accessibility tree and
   a modal dialog cannot be observed.
2. `live_screenshot` takes a fresh native capture of the exact bound window and
   returns the PNG path. It is not a background capture.
3. `live_revert` can deliver its declared physical foreground command. Delivery
   and application effect are separate; the effect remains UNVERIFIED/UNKNOWN.
   Partial or unknown completion is not proof that no input occurred. A PNG
   does not prove that the Modeler reloaded the document.
4. `live_save`, `live_apply` and `live_undo` are **unsupported on the implemented
   pixels-only adapter**. They return `error=active_document_binding_unverified`
   before Save input, file/history changes, reload or output work. The bound
   window title supplies a name, not reliable full-document identity or save
   completion. A same-name file elsewhere cannot be excluded. Caller flags,
   custom dictionaries, timestamps, hashes and old snapshots cannot supply the
   missing proof. Do not retry automatically or present these refusals as
   completed live co-design. Full operation needs a real provider integration
   and native verification; public Core semantic APIs already exist.
5. The retained transaction/recovery helpers are not reached by these entries
   on this route. Their controlled tests do not establish native acceptance.
6. `live_open` is **unsupported on the implemented pixels-only route**
   (`error=open_recent_unsupported_on_pixels_only_route`): it exposes no element
   targeting, so a File > Recents entry cannot be located or activated. That is
   likewise an adapter capability gap, not a statement that the public semantic
   protocol or another host lacks the ability. Open the document with dcc-cua /
   DCC-MCP `ui-control` first.

## Read-only use and route declarations

A read-only startup is valid: with an empty `allowed_actions` and **no** declared
menu routes, the session still constructs and `live_status` / `live_screenshot`
still work. Declaring the `save` and `revert` routes is **not** required for that
startup; route presence and action permission are checked when a menu operation
is actually used, and a missing route is refused then
(`error=menu_route_undeclared`) without any physical input being sent.

## Rules

- The target path must be the document active in the Modeler, and that is read
  from the window title and reported as unverified; it never authorizes a write.
- Keep the file next to its textures (SPM texture paths are relative).
- The window must not be minimised for capture.
- Never report a delivered command as an applied effect. Report disk state, the
  delivery, and the unverified effect separately.
- Geometry statistics in screenshots are the Modeler's own; use the official
  exporter for asset verification.
