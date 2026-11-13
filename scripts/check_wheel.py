"""Exercise the built wheel, isolated from the checkout's editable package."""

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

CHECK = r"""
import json
import runpy
from pathlib import Path
from PIL import Image, ImageDraw
import dcc_mcp_speedtree
from dcc_mcp_speedtree.server import SpeedTreeMcpServer

root = Path.cwd().resolve()
package = Path(dcc_mcp_speedtree.__file__).resolve().parent
assert package.is_relative_to(root), (package, root)
skills = package / "skills"
assert (skills / "speedtree-official/metadata/depends.md").is_file()
expected = {"speedtree-discovery": 7, "speedtree-export": 4, "speedtree-official": 0,
            "speedtree-nodes": 5, "speedtree-production": 6}
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
        mutating = action["name"] == "speedtree_export__export_batch"
        assert action["annotations"]["read_only_hint"] is not (
            mutating or action["name"] in {"speedtree_nodes__edit_graph",
                                           "speedtree_production__production_generate",
                                           "speedtree_production__compare_reference_views",
                                           "speedtree_production__generate_diagnostic_views",
                                           "speedtree_production__rank_reference_candidates"})
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
    source_before = source.read_bytes()
    production_result = runpy.run_path(str(skills / "speedtree-production/scripts/production_generate.py"))["main"](
        source_path=str(source), output_dir=str(root / "candidate"),
        operations=[{"op": "rename", "node_id": "root", "name": "Production candidate"}],
        brief={"seed": 17})
    assert production_result["success"], production_result
    context = production_result["context"]
    assert context["status"] == "candidate_prepared", context
    assert context["validation"]["modeler_regeneration"] == "not_run"
    assert source.read_bytes() == source_before
    manifest = json.loads(Path(context["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["brief"]["seed"] == 17 and manifest["validation"]["seed_effect"] == "not_verified"
    assert manifest["candidate_graph"]["generators"][0]["name"] == "Production candidate"
    assert Path(context["project_path"]).is_file()
    obj = root / "fixture.obj"
    obj.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nusemtl leaf\nf 1 2 3 4\n", encoding="utf-8")
    budget = runpy.run_path(str(skills / "speedtree-production/scripts/validate_obj_budget.py"))["main"](
        obj_path=str(obj), material_categories={"leaf": "cards"},
        total_max_triangles=2, category_limits={"cards": {"min": 2, "max": 2}})
    assert budget["success"] and budget["context"]["status"] == "passed", budget
    assert budget["context"]["total_triangles"] == 2
    bare = root / "bare.obj"
    bare.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    pair = runpy.run_path(str(skills / "speedtree-production/scripts/validate_obj_pair.py"))["main"](
        full_path=str(obj), bare_path=str(bare), total_max_triangles=2, card_triangles=1)
    assert pair["success"] and pair["context"]["status"] == "passed", pair
    assert pair["context"]["full_minus_bare_triangles"] == 1
    mask_path = root / "silhouette.png"
    mask = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(mask).rectangle((10, 8, 29, 30), fill=255)
    mask.save(mask_path)
    specs = {view: {"path": str(mask_path), "mode": "light"}
             for view in ("front", "back", "left", "right")}
    compare = runpy.run_path(str(skills / "speedtree-production/scripts/compare_reference_views.py"))["main"](
        references=specs, candidates=specs, output_dir=str(root / "compare"), canvas_size=64)
    assert compare["success"] and compare["context"]["status"] == "diagnostic_only", compare
    assert compare["context"]["mean_iou"] == 1.0
    rank = runpy.run_path(str(skills / "speedtree-production/scripts/rank_reference_candidates.py"))["main"](
        references=specs, candidate_sets={"A": specs, "B": specs},
        output_dir=str(root / "rank"), canvas_size=64)
    assert rank["success"] and rank["context"]["status"] == "diagnostic_only", rank
    assert [x["candidate"] for x in rank["context"]["candidates"]] == ["A", "B"]
    preview_entry = runpy.run_path(str(skills / "speedtree-production/scripts/generate_diagnostic_views.py"))
    assert callable(preview_entry["main"])
    assert (skills / "speedtree-production/scripts/_preview_worker.py").is_file()
    print(json.dumps({"wheel_import": True, "discovered_and_loaded": expected,
                      "capability_entry_point": "passed", "node_entry_point": "passed",
                      "production_entry_point": "passed", "budget_entry_point": "passed",
                      "compare_entry_point": "passed", "rank_entry_point": "passed",
                      "pair_entry_point": "passed", "preview_wrapper": "present_not_executed",
                      "host_probe": False}))
finally:
    server.stop()
"""


def main():
    wheel = Path(sys.argv[1]).resolve(strict=True)
    archives = list(wheel.parent.glob("*.tar.gz"))
    assert len(archives) == 1, "Build the sdist and wheel into the same output directory"
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
