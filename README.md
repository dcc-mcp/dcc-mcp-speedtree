# dcc-mcp-speedtree

Export licensed SpeedTree Modeler projects through its official command-line
interface, then hand a verified asset bundle to another DCC-MCP adapter.
No injected C++ hook is needed for file-based batch export.

## Start

This is a source preview. Install the checkout with `python -m pip install -e .`,
then configure the installed Modeler executable:

```powershell
$env:DCC_MCP_SPEEDTREE_EXECUTABLE = "C:/Applications/SpeedTree/SpeedTree_Modeler.exe"
dcc-mcp-speedtree
```

The standalone service has its own lifetime and OS-assigned port. Discover it
with `dcc-mcp-cli --gateway local list`, then search and describe its tools.
Optional GUI binding uses `--pid <PID> --window-handle <HWND>` and validates
that the window belongs to the named executable. GUI actions must use the
project-owned `dcc-cua` / `ui-control` route with a fresh exact binding.

## Agent workflow

1. `discover_content` locates installed SPM samples and Games/VFX presets;
   `inspect_preset` reports the selected settings.
2. `plan_export` checks an SPM, preset, format, and **new** output directory.
3. `export_batch` exports 1–16 SPMs through `-export_game` or `-export`, with
   `-export_options`. Supported extensions are `st9`, `st`, `fbx`, `obj`,
   `abc`, and `usd`; availability still depends on product version/license.
4. `export_status` reads progress while Core runs the job; Core cancellation
   stops the owned export process (`DELETE /v1/jobs/{id}` on the owning service). `verify_export` checks the recorded file hashes before handoff. Each tree
   lives in its own directory with its textures and material sidecar.
5. `plan_import` prepares a verified handoff. Discover the destination adapter's importer, import into a new destination,
   and read back geometry, materials, dependencies, transforms, and animation.

The [asset bundle contract](docs/asset-bundle.md) separates export evidence from
target import evidence. [Format and target coverage](docs/compatibility.md)
records the tested combinations and feature limits. The service never runs a
caller-supplied executable or shell command. Existing output directories are
rejected; timeout, failed exit, changed input, missing mesh, or missing explicit
material dependency stops the batch and preserves a partial manifest.

## Unreal

Use the installed Unreal ST9 Games preset for a modern Unreal workflow.
`.spm` is the authoring source, not a Content Browser import format.
`inspect_unreal_project` reports descriptor entries only: a missing entry is
`null` because engine plugin defaults may enable it. Check installation and
loaded modules through `dcc-mcp-unreal`; configure missing plugins only after
the user authorizes the concrete plan. Configuration and restarts belong to
the target adapter. This service does not silently install or enable plugins.

After importing each ST9 via `unreal-assets.import_asset`, read back the mesh
and dependencies. Successful export or enabled plugins alone do not prove a
usable imported asset, correct wind, collision, or rendered appearance.

## Official references

- [Command-line export](https://docs.unity3d.com/speedtree-modeler/manual/export-from-the-command-line.html)
- [Games export options](https://docs.unity3d.com/speedtree-modeler/manual/games-export-options.html)
- [VFX formats and options](https://docs.unity3d.com/speedtree-modeler/manual/vfx-export-options.html)
- [Unreal integration](https://docs.unity3d.com/speedtree-modeler/manual/import-to-unreal.html)

The repository contains no vendor binaries, licensed sample assets, SDK files,
or licensing material. Generated vendor sidecars can contain source-machine
paths; keep raw exports and diagnostics local unless reviewed for sharing.
