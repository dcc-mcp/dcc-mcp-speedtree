"""Delivery truth and target-validation boundaries for the live route.

A delivered physical action is not the same as a confirmed application effect,
and a structured ``success: false`` delivery needs no exception to be a
failure. These tests use the real ``PixelsMcpHostClient`` over a scripted owned
transport: no dcc-cua binary is launched, no Modeler is started, no native
input is delivered and no shared Host is touched.
"""

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
    gui.transport.delivery_success = False  # a bare false flag, i.e. a partial
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "save_not_confirmed"
    assert payload["delivery_completed"] is False
    assert payload["dispatch"] == "partial", "a false flag is not a proved non-dispatch"
    assert length(tree) == "2", "no edit may be written on an unconfirmed save"
    assert not live._history(tree).exists(), "no history may be created"
    assert not list(tmp_path.glob(".live_*"))


def test_revert_refuses_an_unconfirmed_delivery(gui):
    gui.transport.delivery_success = False
    payload = payload_of(live.revert, settle_seconds=0, shot=False, session=gui.session)
    assert payload["error"] == "revert_not_confirmed"
    assert payload["delivery_completed"] is False
    assert payload["dispatch"] == "partial"


def test_apply_creates_no_history_and_sends_no_reload(gui, tmp_path):
    """The dependent phase never starts, so no reload is delivered either."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "save_prerequisite_unverified"
    assert not live._history(tree).exists(), "no history may be created"
    assert gui.transport.action_keys() == ["ctrl+s"], "no reload is delivered"


def test_undo_refuses_before_the_history_and_reload_boundaries(gui, tmp_path):
    """A seeded snapshot cannot manufacture a bound-document observation.

    Undo is fail-closed on pixels_only, so the only backup survives untouched
    and no reload can be delivered -- a stronger guarantee than merely keeping
    the snapshot through an unverified reload.
    """
    tree = write_tree(tmp_path / "tree.spm")
    snapshots = [harness.seed_snapshot(tree, "5")]
    assert len(snapshots) == 1
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert payload["disk_mutation"] is False
    assert payload["history_mutation"] is False
    assert payload["reload_dispatch"] is False
    assert snapshots[0].is_file(), "the only backup is untouched"
    assert length(tree) == "2", "the file is not restored"
    assert gui.transport.action_keys() == [], "no reload may be dispatched"


def test_a_delivered_but_unverified_reload_cannot_be_reached_by_undo(gui, tmp_path):
    """No reload is delivered at all, so there is nothing to compensate."""
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert length(tree) == "2", "the file stays; no silent rollback"
    assert gui.transport.action_keys() == []


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
