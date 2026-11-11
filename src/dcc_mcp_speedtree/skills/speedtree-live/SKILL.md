---
name: speedtree-live
description: Co-design a tree live in the SpeedTree Modeler window the user is watching - apply generator edits, reload, screenshot and undo in the background without touching the user's mouse or keyboard.
license: MIT
metadata:
  dcc-mcp:
    dcc: speedtree
    layer: domain
    version: "0.1.0"
    tools: tools.yaml
    search-hint: "SpeedTree live modeler reload revert screenshot undo co-design collaborate GUI window"
---

# Live co-design in the Modeler

The user watches a running SpeedTree Modeler (Windows). The Modeler has no
scripting API, so every change goes through the open file:

1. `live_status` lists Modeler windows, the active document and File > Recents.
2. `live_open` activates a file from File > Recents. A file that was never
   opened must first be opened once by the user with File > Open.
3. Inspect generator IDs and property names with `inspect_graph` and
   `inspect_properties` on the same path; never guess them.
4. `live_apply` takes the same `operations` list as `edit_graph`. It saves the
   active document (keeping the user's own GUI edits), copies it into
   `_live_history/<name>/`, rewrites the file in place, reloads it with
   File > Revert to saved and returns a screenshot path. Read that PNG to see
   the result, then ask the user for feedback.
5. `live_undo` restores the copy taken before the last `live_apply` and reloads.
   It drops GUI edits the user made after that apply.

`live_screenshot`, `live_save` and `live_revert` are available on their own.

Rules: the target path must be the document active in the Modeler. Keep the
file next to its textures (SPM texture paths are relative). The window must not
be minimised for screenshots. If a Modeler dialog is open, ask the user to close
it. Dialogs opened by these tools are answered by keys posted to the dialog
window only (Enter confirms the revert warning, Escape cancels anything else).
Geometry statistics in screenshots are the Modeler's own; use the official
exporter for asset verification.
