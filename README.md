# dcc-mcp-speedtree

Local-first adapter for a licensed SpeedTree installation. It binds one exact SpeedTree process/window and exposes an MCP catalog backed by an operator-installed official command hook.

## Local development

```powershell
thm +p speedtree run speedtree
# or, with an already running exact instance:
python -m dcc_mcp_speedtree.server --pid <PID> --window-handle <HWND> --executable <SpeedTree.exe>
```

Set `DCC_MCP_SPEEDTREE_COMMAND_HOOK_DLL` to the approved hook built for the installed SpeedTree version. The adapter fails closed when the hook or exact PID/HWND binding is missing. It never includes SpeedTree binaries or licensing code.
