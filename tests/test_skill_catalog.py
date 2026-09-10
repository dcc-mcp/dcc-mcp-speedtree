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
        }
        assert server.load_skill("speedtree-official")
        actions = [a for a in server.list_actions("speedtree") if a.get("skill_name") in skills]
        assert len(actions) == 16
        for action in actions:
            assert Path(action["source_file"]).is_file()
            assert action["input_schema"]["type"] == "object"
            assert action["output_schema"]["type"] == "object"
            mutating = action["name"] == "speedtree_export__export_batch"
            assert action["annotations"]["read_only_hint"] is not (
                mutating or action["name"] == "speedtree_nodes__edit_graph"
            )
            assert action["annotations"]["destructive_hint"] is mutating
            if mutating:
                assert action["execution"] == "async"
                assert action["annotations"]["deferred_hint"] is True
    finally:
        server.stop()
