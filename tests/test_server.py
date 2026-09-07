import pytest

from dcc_mcp_speedtree.server import SpeedTreeMcpServer


def test_standalone_does_not_bind_optional_gui(tmp_path, monkeypatch):
    from dcc_mcp_core.server_base import DccServerBase

    exe = tmp_path / "SpeedTree_Modeler.exe"
    exe.write_bytes(b"fixture")
    monkeypatch.setenv("DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS", "1")
    captured = {}
    monkeypatch.setattr(DccServerBase, "__init__", lambda self, **kwargs: captured.update(kwargs))
    server = SpeedTreeMcpServer(executable=str(exe))
    assert server.binding is None
    assert captured["options"].instance_type == "standalone"


@pytest.mark.parametrize(
    "arguments", [{"dcc_pid": 1}, {"dcc_window_handle": 1}, {"dcc_pid": 0, "dcc_window_handle": 1}]
)
def test_partial_or_invalid_binding_rejected(arguments):
    with pytest.raises(ValueError):
        SpeedTreeMcpServer(**arguments)
