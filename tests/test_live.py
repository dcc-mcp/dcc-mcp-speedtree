"""Behaviour of the seven live entries on the repaired dcc-cua/ui-control route.

The GUI boundary is a scripted owned transport (``live_ui_harness``): Core's real
``PixelsMcpHostClient`` runs, but no dcc-cua binary is launched, no Modeler is
started and no native input is delivered.
"""

import gzip
from pathlib import Path

import live_ui_harness as harness
import pytest

from dcc_mcp_speedtree import live
from dcc_mcp_speedtree.graph import SpeedTreeGraph

SET_LENGTH = [{"op": "set_property", "node_id": "root", "name": "Spine:Length:Absolute", "value": 9}]
BAD_EDIT = [{"op": "set_property", "node_id": "missing", "name": "x", "value": 1}]


def write_tree(path, value="2"):
    xml = (
        '<SpeedTree Version="8"><Generators><Generator Type="Tree"><GUID>root</GUID>'
        "<Name>root</Name><Level>0</Level><Hidden>false</Hidden><Properties><SplineProperty>"
        f"<Name>Spine:Length:Absolute</Name><Value>{value}</Value></SplineProperty>"
        "</Properties></Generator></Generators></SpeedTree>"
    )
    path.write_bytes(gzip.compress(xml.encode()))
    return path


def length(path):
    props = SpeedTreeGraph.load(path).properties("root")
    return next(p for p in props if p["name"] == "Spine:Length:Absolute")["components"]["Value"]


@pytest.fixture
def gui(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    return harness.Harness(monkeypatch)


def test_status_reports_the_exact_target_and_unverified_document(gui):
    state = live.status(session=gui.session)
    assert state["target"]["process_id"] == harness.PID
    assert state["target"]["window_handle"] == harness.HWND
    assert state["capabilities"]["modal_dialog"] is False
    assert state["capabilities"]["accessibility_tree"] is False
    assert state["capabilities"]["active_document_verified"] is False


def test_screenshot_writes_a_real_native_png(gui):
    result = live.screenshot(session=gui.session)
    assert Path(result["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["target"]["process_id"] == harness.PID


def test_apply_edits_in_place_snapshots_and_reloads(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    result = live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9"
    assert length(result["history_snapshot"]) == "2"
    assert result["undo_depth"] == 1
    assert result["process_id"] == harness.PID
    assert result["reload_effect"] == "unverifiable"
    assert result["reload_verification_required"] is True
    assert Path(result["screenshot"]).name.startswith("modeler_")
    methods = gui.transport.methods()
    assert methods.count("execute_action") == 2
    assert gui.transport.action_keys() == ["ctrl+s", "ctrl+r"]


def test_undo_restores_the_previous_state_and_consumes_history(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    result = live.undo(tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "2"
    assert result["undo_depth"] == 0
    assert not list(live._snapshots(tree))
    with pytest.raises(live.LiveError) as raised:
        live.undo(tree, settle_seconds=0, session=gui.session)
    assert raised.value.payload["error"] == "no_history"


def test_save_and_revert_report_the_unverifiable_effect(gui):
    saved = live.save(session=gui.session)
    assert saved["menu"] == "save"
    assert saved["effect"] == "unverifiable"
    assert saved["verification_required"] is True
    reverted = live.revert(settle_seconds=0, shot=False, session=gui.session)
    assert reverted["menu"] == "revert"
    assert reverted["effect"] == "unverifiable"


def test_apply_refuses_when_the_bound_window_shows_another_document(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    other = harness.Harness(monkeypatch, title="other.spm - SpeedTree Modeler")
    tree = write_tree(tmp_path / "tree.spm")
    with pytest.raises(live.LiveError) as raised:
        live.apply(tree, SET_LENGTH, settle_seconds=0, session=other.session)
    payload = raised.value.payload
    assert payload["error"] == "not_active"
    assert payload["active_document"] == "other.spm"
    assert payload["active_document_verified"] is False
    assert not list(tmp_path.rglob("_live_history"))


def test_a_failed_edit_leaves_the_file_and_history_untouched(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    before = tree.read_bytes()
    with pytest.raises(Exception):
        live.apply(tree, BAD_EDIT, settle_seconds=0, session=gui.session)
    assert tree.read_bytes() == before
    assert not list(live._snapshots(tree))
    assert not list(tmp_path.glob(".live_*"))


@pytest.mark.parametrize(
    "entry", ["apply", "undo", "revert", "save", "open_recent", "status", "screenshot"]
)
def test_every_entry_fails_closed_without_the_server_session(tmp_path, entry):
    tree = write_tree(tmp_path / "tree.spm")
    before = tree.read_bytes()
    with pytest.raises(live.LiveError) as raised:
        if entry == "apply":
            live.apply(tree, SET_LENGTH)
        elif entry == "undo":
            live.undo(tree)
        elif entry == "open_recent":
            live.open_recent(tree)
        else:
            getattr(live, entry)()
    assert raised.value.payload["error"] == "no_authorized_ui_route"
    assert tree.read_bytes() == before
    assert not list(tmp_path.rglob("_live_history"))
