"""Delivery truth and target-validation boundaries for the live route.

A delivered physical action is not the same as a confirmed application effect,
and a structured ``success: false`` delivery needs no exception to be a
failure. These tests use the real ``PixelsMcpHostClient`` over a scripted owned
transport: no dcc-cua binary is launched, no Modeler is started, no native
input is delivered and no shared Host is touched.
"""

from pathlib import Path

import live_ui_harness as harness
import pytest
from live_ui_harness import length, write_tree

from dcc_mcp_speedtree import live

SET_LENGTH = [
    {"op": "set_property", "node_id": "root", "name": "Spine:Length:Absolute", "value": 9}
]


@pytest.fixture
def gui(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    return harness.Harness(monkeypatch)


def payload_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except live.LiveError as exc:
        return exc.payload
    raise AssertionError("expected a LiveError")


def test_apply_refuses_when_the_save_delivery_is_not_completed(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.transport.delivery_success = False
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "save_not_confirmed"
    assert payload["delivery_completed"] is False
    assert length(tree) == "2", "no edit may be written on an unconfirmed save"
    assert not live._history(tree).exists(), "no history may be created"
    assert not list(tmp_path.glob(".live_*"))


def test_revert_refuses_an_unconfirmed_delivery(gui):
    gui.transport.delivery_success = False
    payload = payload_of(live.revert, settle_seconds=0, shot=False, session=gui.session)
    assert payload["error"] == "revert_not_confirmed"
    assert payload["delivery_completed"] is False


def test_apply_reports_the_reload_as_unverified_and_keeps_the_history(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    result = live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    verification = result.get("verification")
    assert verification, "a delivered-but-unverifiable reload must be reported"
    assert verification["status"] in {"unknown", "pending"}
    assert verification["history_retained"] is True
    assert Path(verification["history_snapshot"]).is_file()
    assert result["reload"]["delivered"] is True
    assert result["reload"]["effect"] == "unverifiable"
    assert result["reload"]["verification_required"] is True


def test_undo_keeps_the_only_snapshot_when_the_reload_is_unverified(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    snapshots = list(live._snapshots(tree))
    assert len(snapshots) == 1
    result = live.undo(tree, settle_seconds=0, session=gui.session)
    assert snapshots[0].is_file(), "the only backup must survive an unverified reload"
    assert length(tree) == "2", "the disk restore itself is real"
    assert result["verification"]["history_retained"] is True
    assert result["undo_depth"] == 1, "retained history is still undoable"
    assert result["verification"]["status"] in {"unknown", "pending"}


def test_a_delivered_but_unverified_reload_is_not_compensated(gui, tmp_path):
    """Compensation would undo an edit the Modeler may already have loaded."""
    tree = write_tree(tmp_path / "tree.spm")
    result = live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9", "an unverified reload must not silently revert the edit"
    assert result["verification"]["status"] in {"unknown", "pending"}
    assert gui.transport.action_keys() == ["ctrl+s", "ctrl+r"]


def test_apply_refuses_a_process_id_that_is_not_the_bound_window(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    payload = payload_of(
        live.apply, tree, SET_LENGTH, process_id=9999, settle_seconds=0, session=gui.session
    )
    assert payload["error"] == "invalid_target"
    assert length(tree) == "2"
    assert gui.transport.methods() == [], "no native read may precede the target check"


def test_write_entries_validate_the_target_before_source_path_work(gui, tmp_path):
    missing = tmp_path / "missing.spm"
    payload = payload_of(live.undo, missing, process_id=9999, session=gui.session)
    assert payload["error"] == "invalid_target", "the target check must precede path resolution"


@pytest.mark.parametrize("process_id", ["7", 7.0, 0, -1, True])
def test_invalid_process_id_types_are_refused(gui, process_id):
    payload = payload_of(live.save, process_id=process_id, session=gui.session)
    assert payload["error"] == "invalid_target"
