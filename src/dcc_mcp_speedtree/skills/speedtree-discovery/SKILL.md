---
name: speedtree-discovery
description: >-
  Inspect an installed SpeedTree runtime, discover official samples and export
  presets, inspect preset options, fingerprint supported assets, plan an
  export, and preflight Unreal integration. Read-only operations do not require
  a C++ hook.
license: MIT
compatibility: "SpeedTree Modeler/Compiler installation; dcc-mcp-core 0.20+"
allowed-tools: "python"
metadata:
  dcc-mcp:
    dcc: speedtree
    layer: domain
    version: "0.1.0"
    search-hint: "SpeedTree inspect runtime discover samples presets asset export plan Unreal preflight"
    tags: "speedtree,modeler,compiler,spm,srt,export,unreal,inspection"
    tools: tools.yaml

---

# SpeedTree discovery

Use these tools before attempting any live operation. They never inject code,
modify the SpeedTree process, or create output directories. A live command or
mutation must be supplied by a separately approved vendor integration.
