import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dcc_mcp_speedtree.export import export_batch, verify_export


@pytest.fixture
def request_files(tmp_path, monkeypatch):
    exe = tmp_path / "SpeedTree_Modeler.exe"
    exe.write_bytes(b"test executable")
    source = tmp_path / "Tree.spm"
    source.write_bytes(b"test source")
    preset = tmp_path / "Preset.ini"
    preset.write_text("[General]\nType=Game\nTransformConvertUnit=Centimeter\n")
    monkeypatch.setenv("DCC_MCP_SPEEDTREE_EXECUTABLE", str(exe))
    return [str(source)], str(preset), str(tmp_path / "output")


def fake_export(argv, **kwargs):
    assert argv[1] in {"-export_game", "-export"}
    Path(argv[2]).write_bytes(b"SpeedTree9______payload")
    return SimpleNamespace(returncode=0)


def test_inventory_detects_changed_and_missing_files(request_files, monkeypatch):
    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", fake_export)
    result = export_batch(*request_files)
    assert verify_export(result["manifest_path"])["verified"]
    mesh = Path(request_files[2]) / result["items"][0]["mesh"]
    mesh.write_bytes(b"changed")
    assert not verify_export(result["manifest_path"])["verified"]
    mesh.unlink()
    assert "missing_file:" in verify_export(result["manifest_path"])["errors"][0]


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("exit", "exporter_failed"),
        ("missing", "missing_mesh"),
        ("timeout", "timeout"),
        ("wrong_header", "failed"),
    ],
)
def test_failed_export_never_reports_success(request_files, monkeypatch, failure, expected):
    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 1)
        if failure == "wrong_header":
            Path(argv[2]).write_bytes(b"not a tree")
        return SimpleNamespace(returncode=3 if failure == "exit" else 0)

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", run)
    result = export_batch(*request_files)
    assert result["status"] == "failed"
    assert result["items"][0]["status"] == expected
    assert not verify_export(result["manifest_path"])["verified"]


def test_existing_output_and_duplicate_input_rejected(request_files, monkeypatch):
    monkeypatch.setattr(
        "dcc_mcp_speedtree.export.run_modeler", lambda *a, **k: pytest.fail("must not launch")
    )
    sources, preset, output = request_files
    with pytest.raises(ValueError, match="Duplicate"):
        export_batch(sources * 2, preset, output)
    Path(output).mkdir()
    (Path(output) / "keep").write_text("untouched")
    with pytest.raises(FileExistsError):
        export_batch(sources, preset, output)
    assert (Path(output) / "keep").read_text() == "untouched"


def test_partial_batch_stops_and_keeps_evidence(request_files, monkeypatch):
    sources, preset, output = request_files
    second = Path(preset).with_name("Second.spm")
    second.write_bytes(b"second")

    def run(argv, **kwargs):
        if argv[3] == str(second):
            return SimpleNamespace(returncode=2)
        return fake_export(argv, **kwargs)

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", run)
    result = export_batch(sources + [str(second)], preset, output)
    assert [i["status"] for i in result["items"]] == ["exported", "exporter_failed"]
    assert not verify_export(result["manifest_path"])["verified"]


def test_manifest_path_escape_and_empty_batch(request_files, monkeypatch):
    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", fake_export)
    result = export_batch(*request_files)
    path = Path(result["manifest_path"])
    data = json.loads(path.read_text())
    data["items"][0]["files"][0]["path"] = "../Tree.spm"
    path.write_text(json.dumps(data))
    assert "path_escape" in verify_export(path)["errors"]
    data["items"] = []
    data["requested_count"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="between 1 and 16"):
        verify_export(path)


def test_vfx_uses_official_vfx_command(request_files, monkeypatch):
    sources, preset, output = request_files
    Path(preset).write_text("[General]\nType=VFX\n")

    def run(argv, **kwargs):
        assert argv[1] == "-export"
        Path(argv[2]).write_bytes(b"Kaydara FBX Binary  payload")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", run)
    assert export_batch(sources, preset, output, "fbx")["status"] == "exported"


def test_input_changed_during_export_fails(request_files, monkeypatch):
    def run(argv, **kwargs):
        fake_export(argv, **kwargs)
        Path(argv[3]).write_bytes(b"changed source")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", run)
    assert export_batch(*request_files)["items"][0]["status"] == "input_changed"


def test_handoff_uses_target_adapter_and_rejects_native_in_blender(request_files, monkeypatch):
    from dcc_mcp_speedtree.handoff import plan_import

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", fake_export)
    result = export_batch(*request_files)
    plan = plan_import(result["manifest_path"], "unreal")
    assert plan["target_status"] == "requires_capability_discovery"
    assert plan["mutated"] is False
    with pytest.raises(ValueError, match="No import route"):
        plan_import(result["manifest_path"], "blender")
