from pathlib import Path

from dcc_mcp_speedtree.server import SpeedTreeMcpServer


def test_registered_contracts_preserve_read_only_hints_and_packaged_scripts(tmp_path, monkeypatch):
    monkeypatch.setenv("DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS", "1")
    exe = tmp_path / "SpeedTree_Modeler.exe"
    exe.write_bytes(b"metadata fixture; never launched")
    server = SpeedTreeMcpServer(executable=str(exe), enable_gateway_failover=False)
    try:
        server.register_builtin_actions()
        skills = {s["name"] for s in server.search_skills(dcc="speedtree")}
        assert skills == {
            "speedtree-discovery",
            "speedtree-export",
            "speedtree-official",
            "speedtree-nodes",
            "speedtree-production",
        }
        assert server.load_skill("speedtree-official")
        actions = [a for a in server.list_actions("speedtree") if a.get("skill_name") in skills]
        assert len(actions) == 24
        action_names = {action["name"] for action in actions}
        assert {
            "speedtree_production__production_generate",
            "speedtree_production__validate_obj_budget",
            "speedtree_production__compare_reference_views",
            "speedtree_production__validate_obj_pair",
            "speedtree_production__generate_diagnostic_views",
            "speedtree_production__rank_reference_candidates",
            "speedtree_production__validate_branch_structure",
            "speedtree_production__fit_reference_modeler",
        } <= action_names
        for action in actions:
            assert Path(action["source_file"]).is_file()
            assert action["input_schema"]["type"] == "object"
            assert action["output_schema"]["type"] == "object"
            mutating = action["name"] in {
                "speedtree_export__export_batch",
                "speedtree_production__fit_reference_modeler",
            }
            assert action["annotations"]["read_only_hint"] is not (
                mutating
                or action["name"] == "speedtree_nodes__edit_graph"
                or action["name"]
                in {
                    "speedtree_production__production_generate",
                    "speedtree_production__compare_reference_views",
                    "speedtree_production__generate_diagnostic_views",
                    "speedtree_production__rank_reference_candidates",
                }
            )
            assert action["annotations"]["destructive_hint"] is mutating
            if mutating:
                assert action["execution"] == "async"
                assert action["annotations"]["deferred_hint"] is True
    finally:
        server.stop()
