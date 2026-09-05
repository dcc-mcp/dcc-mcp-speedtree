---
name: speedtree-official
description: Discover and invoke only capabilities exposed by the installed official SpeedTree runtime through the approved command hook.
---

# SpeedTree official capability bridge

This skill is deliberately host-bound. It must report the exact provider, runtime version, PID, and HWND before any mutating action. The adapter may consume an operator-installed official SpeedTree command-hook DLL through `DCC_MCP_SPEEDTREE_COMMAND_HOOK_DLL`; it does not redistribute SpeedTree binaries, bypass licensing, or guess undocumented signatures.

Use the typed capability catalog and the native hook client when available. If no approved hook is installed, return `hook_unavailable` and direct the operator to configure the official integration. Do not fall back to generic computer-use or arbitrary script execution.
