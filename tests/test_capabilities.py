from pathlib import Path

import pytest

from dcc_mcp_speedtree.capabilities import (
    SUPPORTED_ASSET_SUFFIXES,
    capability_status,
    discover_official_content,
    inspect_asset,
    inspect_preset,
    plan_export,
)


def test_discover_content_returns_categorized_files(tmp_path: Path):
    samples = tmp_path / "samples" / "Forest"
    presets = tmp_path / "export_presets" / "Games"
    samples.mkdir(parents=True)
    presets.mkdir(parents=True)
    (samples / "Pine.spm").write_bytes(b"spm")
    (presets / "Unreal.ini").write_text("[Export]\n", encoding="utf-8")

    result = discover_official_content(tmp_path)

    assert result["root"] == str(tmp_path.resolve())
    assert result["counts"] == {"samples": 1, "game_export_presets": 1}
    assert result["samples"] == [str((samples / "Pine.spm").resolve())]


def test_inspect_asset_returns_stable_fingerprint(tmp_path: Path):
    asset = tmp_path / "Pine.spm"
    asset.write_bytes(b"speedtree asset")

    result = inspect_asset(asset)

    assert result["kind"] == "model"
    assert result["suffix"] == ".spm"
    assert result["size_bytes"] == len(b"speedtree asset")
    assert len(result["sha256"]) == 64
    assert result["text_preview"] is None


def test_inspect_asset_rejects_unknown_suffix(tmp_path: Path):
    asset = tmp_path / "secret.bin"
    asset.write_bytes(b"x")

    with pytest.raises(ValueError, match="unsupported SpeedTree asset suffix"):
        inspect_asset(asset)


def test_plan_export_is_read_only_and_reports_missing_preset(tmp_path: Path):
    source = tmp_path / "Pine.spm"
    source.write_bytes(b"spm")

    result = plan_export(source, tmp_path / "missing.ini", tmp_path / "out")

    assert result["ready"] is False
    assert result["requires_operator_action"] is True
    assert result["missing"] == ["preset"]
    assert not (tmp_path / "out").exists()


def test_plan_export_ready_with_new_output(tmp_path: Path):
    source = tmp_path / "Pine.spm"
    preset = tmp_path / "Unreal.ini"
    output = tmp_path / "out"
    source.write_bytes(b"spm")
    preset.write_text("[General]\nType=Game\n", encoding="utf-8")

    result = plan_export(source, preset, output, format="st9")

    assert result["ready"] is True
    assert result["format"] == "st9"
    assert result["mutated"] is False


def test_inspect_preset_reads_sections_without_applying(tmp_path: Path):
    preset = tmp_path / "Unreal.ini"
    preset.write_text("[Export]\nFormat=SRT\nOutput=out\n", encoding="utf-8")

    result = inspect_preset(preset)

    assert result["section_names"] == ["Export"]
    assert result["sections"]["Export"]["Format"] == "SRT"
    assert result["option_count"] == 2
    assert result["mutated"] is False


def test_supported_suffixes_are_lowercase():
    assert SUPPORTED_ASSET_SUFFIXES == frozenset(SUPPORTED_ASSET_SUFFIXES)
    assert all(suffix == suffix.lower() for suffix in SUPPORTED_ASSET_SUFFIXES)


def test_capability_status_fails_closed_for_live_control():
    result = capability_status()

    assert result["read_only_research"] == "available"
    assert result["live_in_process"] == "integration_unavailable"
    assert result["mutating_operations"] == "official_cli_export"


def test_discovery_skill_is_packaged_with_scripts():
    skill_dir = (
        Path(__file__).parents[1] / "src" / "dcc_mcp_speedtree" / "skills" / "speedtree-discovery"
    )
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "tools.yaml").is_file()
    assert {path.stem for path in (skill_dir / "scripts").glob("*.py")} == {
        "discover_content",
        "inspect_asset",
        "inspect_runtime",
        "inspect_preset",
        "inspect_unreal_project",
        "plan_export",
    }
