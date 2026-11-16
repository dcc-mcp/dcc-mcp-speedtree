"""Exercise the built wheel, isolated from the checkout's editable package."""

import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

CHECK = r"""
import json
import runpy
from pathlib import Path
import dcc_mcp_speedtree
from dcc_mcp_speedtree.server import SpeedTreeMcpServer

root = Path.cwd().resolve()
package = Path(dcc_mcp_speedtree.__file__).resolve().parent
assert package.is_relative_to(root), (package, root)
skills = package / "skills"
assert (skills / "speedtree-official/metadata/depends.md").is_file()
expected = {"speedtree-discovery": 7, "speedtree-export": 4, "speedtree-official": 0, "speedtree-nodes": 5,
            "speedtree-live": 7}
assert not (package / "live.ps1").exists(), "raw UI bridge must not be installed"
exe = root / "SpeedTree_Modeler.exe"
exe.write_bytes(b"not executable; metadata-only fixture")
server = SpeedTreeMcpServer(executable=str(exe), enable_gateway_failover=False,
                          enable_file_logging=False, enable_telemetry=False)
try:
    server.register_builtin_actions()
    discovered = {item["name"]: item for item in server.search_skills(dcc="speedtree")}
    for name, count in expected.items():
        assert name in discovered, name
        assert discovered[name]["tool_count"] == count, discovered[name]
        assert server.load_skill(name), name
        assert server.get_skill_info(name) is not None, name
    actions = [a for a in server.list_actions("speedtree") if a.get("skill_name") in expected]
    assert len(actions) == sum(expected.values())
    for action in actions:
        script = Path(action["source_file"]).resolve()
        assert script.is_file() and script.is_relative_to(package), script
        if action["name"].startswith("speedtree_live__"):
            continue  # live tools act on the open Modeler document; tests/test_skill_catalog.py checks them
        mutating = action["name"] == "speedtree_export__export_batch"
        assert action["annotations"]["read_only_hint"] is not (mutating or action["name"] == "speedtree_nodes__edit_graph")
        assert action["annotations"]["destructive_hint"] is mutating
    result = runpy.run_path(str(skills / "speedtree-discovery/scripts/inspect_capabilities.py"))["main"]()
    assert result["success"] and result["context"]["full_modeler_coverage"] is False
    assert result["context"]["live_probe_performed"] is False
    source = root / "source.spm"
    source.write_text('<SpeedTree Version="8"><Generators><Generator Type="Tree">'
                      '<GUID>root</GUID><Name>Tree</Name><Level>0</Level><Properties/>'
                      '</Generator></Generators></SpeedTree>', encoding="utf-8")
    node_result = runpy.run_path(str(skills / "speedtree-nodes/scripts/edit_graph.py"))["main"](
        source_path=str(source), output_path=str(root / "edited.spm"),
        operations=[{"op": "rename", "node_id": "root", "name": "Verified tree"}])
    assert node_result["success"], node_result
    assert node_result["context"]["graph"]["generators"][0]["name"] == "Verified tree"
    assert node_result["context"]["source_modified"] is False
    live_status = runpy.run_path(str(skills / "speedtree-live/scripts/live_status.py"))["main"]()
    assert live_status["success"] is False and live_status["error"] == "no_authorized_ui_route", live_status
    print(json.dumps({"wheel_import": True, "discovered_and_loaded": expected,
                      "capability_entry_point": "passed", "node_entry_point": "passed",
                      "live_entry_point": "no_authorized_ui_route", "host_probe": False}))
finally:
    server.stop()
"""


def main():
    wheel = Path(sys.argv[1]).resolve(strict=True)
    archives = list(wheel.parent.glob("*.tar.gz"))
    assert len(archives) == 1, "Build the sdist and wheel into the same output directory"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any(name.endswith("live.ps1") for name in names), (
            "raw UI bridge must not be packaged"
        )
        for relative in (
            "dcc_mcp_speedtree/skills/speedtree-live/tools.yaml",
            "dcc_mcp_speedtree/skills/speedtree-live/SKILL.md",
            "dcc_mcp_speedtree/skills/speedtree-live/scripts/live_status.py",
        ):
            assert any(name.endswith(relative) for name in names), relative
    with tarfile.open(archives[0]) as archive:
        names = archive.getnames()
        for relative in (
            "docs/capability-audit.md",
            "docs/images/speedtree-to-unreal.png",
            "scripts/check_wheel.py",
            "scripts/build_node_showcases.py",
            "scripts/verify_node_showcases.py",
            "docs/native-capability-matrix.md",
            "docs/images/native-node-workflow.gif",
        ):
            assert any(name.endswith("/" + relative) for name in names), relative
    with tempfile.TemporaryDirectory(prefix="speedtree-wheel-") as temp:
        target = Path(temp)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", temp, str(wheel)],
            check=True,
        )
        env = dict(os.environ)
        for name in list(env):
            if name.startswith("DCC_MCP_"):
                del env[name]
        env.update(PYTHONPATH=temp, DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS="1")
        subprocess.run([sys.executable, "-c", CHECK], cwd=target, env=env, check=True)


if __name__ == "__main__":
    main()
