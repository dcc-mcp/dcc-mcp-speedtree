# dcc-mcp-speedtree

Local-first adapter for a licensed SpeedTree installation. It binds one exact SpeedTree process/window and exposes an MCP catalog backed by an operator-installed official command hook.

## Local development

Run the adapter through your studio's approved package environment, or attach it to an already running SpeedTree instance with its exact PID and native window handle:

```powershell
python -m dcc_mcp_speedtree.server --pid <PID> --window-handle <HWND> --executable <SpeedTree.exe>
```

Set `DCC_MCP_SPEEDTREE_COMMAND_HOOK_DLL` only when an approved, version-matched official hook is installed. The adapter fails closed when the hook or exact binding is missing. It never includes SpeedTree binaries or licensing code.

## Unreal project preflight

`DccMcpUnreal` must be enabled in the target `.uproject`. UE's `SpeedTreeImporter` is an Unreal-side importer; it does not consume SpeedTree `.spm` authoring projects. The supported flow is:

1. Export `.st`/`.srt` from SpeedTree using the installed official Unreal export preset.
2. Import that exported asset into the UE project through `DccMcpUnreal`/Unreal's asset tools.
3. Verify generated materials, LODs, collision, and scene visibility in the target engine version.

The adapter does not claim import success from file discovery alone.

## Unreal-side opt-in configuration

The companion UE project can provide a read-only SpeedTree preflight and an explicit configuration action. Its `configure-speedtree-support.py` script reports whether `DccMcpUnreal` and `SpeedTreeImporter` are enabled; pass `--apply` only after operator approval to add or enable the engine-provided importer entry. It writes a `.uproject.bak` before changing the descriptor. This prepares plugin discovery but does not replace the official SpeedTree export step.
