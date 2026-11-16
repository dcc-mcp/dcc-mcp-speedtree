---
name: speedtree-live
description: Bound live session with the SpeedTree Modeler window the user is watching - observe it and deliver configured save/revert commands through the owned dcc-cua / DCC-MCP ui-control route, with every application effect reported as unverified and no background, keyboard-free or headless editing promise.
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
3. `live_save` and `live_revert` deliver the configured physical command to the
   bound window. They report the **delivery** and report the application
   **effect as UNVERIFIED/UNKNOWN**. A command the runtime did not confirm as
   delivered (`success` / `delivery_completed` / `post_dispatch_validated` not
   all true) is refused. Neither entry claims that the document was saved or that
   the Modeler reloaded it, and a fresh PNG is not proof of either.
4. `live_undo` restores the file **on disk** from the newest history snapshot and
   delivers the reload command. The disk restore is real; the snapshot is **kept**
   until a supported reload confirmation exists, and the reload effect stays
   unverified.
5. `live_apply` — **not available as an edit on the implemented pixels-only
   adapter.** It returns `error=save_prerequisite_unverified`
   **before** any dependent business-file edit, history snapshot or reload,
   because that route offers no formal process/document-bound save confirmation:
   a changed mtime or a changed content hash only shows that the disk changed,
   not that the bound Modeler saved its current GUI edits into that document.
   Do not present this entry as working, do not retry it automatically, and do
   not substitute a file check for the missing confirmation. This is a reported
   adapter capability gap, not full real-time co-design acceptance.
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
  from the window title and reported as unverified.
- Keep the file next to its textures (SPM texture paths are relative).
- The window must not be minimised for capture.
- Never report a delivered command as an applied effect. Report disk state, the
  delivery, and the unverified effect separately.
- Geometry statistics in screenshots are the Modeler's own; use the official
  exporter for asset verification.
