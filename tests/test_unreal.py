from dcc_mcp_speedtree.unreal import inspect_unreal_project

def test_unreal_project_plugin_preflight(tmp_path):
    project = tmp_path / "Game.uproject"
    project.write_text('{"EngineAssociation":"5.5","Plugins":[{"Name":"DccMcpUnreal","Enabled":true}]}')
    result = inspect_unreal_project(project)
    assert result["dcc_mcp_unreal_enabled"] is True
    assert result["speedtree_importer_enabled"] is False
