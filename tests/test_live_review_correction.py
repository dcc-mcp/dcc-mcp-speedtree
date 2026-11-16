"""Corrections required by the original-32 review of head 971ac98.

F1 — shipped skill wrappers must not assert an effect that is unverified.
F3 — a read-only session must be constructible without write routes.
F4 — a dispatch that happened but could not be validated must not be blindly
     compensated, and its recovery material must not be discarded.

The wrappers are executed as real shipped files through a real
``BoundedLiveSession`` over a scripted owned transport: no real task, no native
call, no Modeler.
"""

import runpy

import live_ui_harness as harness
import pytest
from live_ui_harness import REVERT_ROUTE, length, write_tree

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


def run_wrapper(name, session, **params):
    """Execute a real shipped skill wrapper with the trusted session injected."""
    module = runpy.run_path(harness.published_live_entry(name))
    return module["main"](**params, **{live.TRUSTED_SESSION_PARAM: session})


# --- F4: dispatch that happened but could not be validated --------------------


def test_post_dispatch_unknown_reload_preserves_the_restore_and_backup(gui, tmp_path):
    """Delivery happened, so the Modeler may have executed the reload.

    Undo is the reachable write path: production apply refuses before any edit,
    so this asserts that a possibly-executed reload rolls nothing back and keeps
    the only backup.
    """
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture, not an apply
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "post_invalidated"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "5", "the restore stays on disk"
    assert len(list(live._snapshots(tree))) == 1, "the only backup must survive"
    assert payload["file_restored"] is True, "the local restore already happened"
    assert payload["history_retained"] is True
    assert payload["dispatch"] == "delivered_unverified"
    assert payload["gui_state"] == "unknown"


def test_transport_error_after_dispatch_is_not_a_known_failure(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "transport_error"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "5", "an unclassified dispatch error must roll nothing back"
    assert len(list(live._snapshots(tree))) == 1
    assert payload["dispatch"] == "unknown_dispatch"
    assert payload["history_retained"] is True
    assert payload["gui_state"] == "unknown"


def test_known_no_dispatch_failure_still_compensates(monkeypatch, tmp_path):
    """Control: an adapter-owned boundary refused before execute was entered.

    No transport label and no completion flag is involved: the reload route is
    simply absent, so ``menu()`` refuses on this side of the client and no
    physical input can have been dispatched.
    """
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, menu_routes={"save": harness.SAVE_ROUTE})  # no revert
    tree = write_tree(tmp_path / "tree.spm")
    snap = harness.seed_snapshot(tree, "5")  # controlled fixture
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "5", "the restored file stays restored"
    assert snap.is_file(), "the history is retained for the documented retry"
    assert payload["dispatch"] == "not_dispatched"
    assert payload["no_dispatch_proof"]["boundary"] == "menu_route_declaration"
    assert payload["no_dispatch_proof"]["execute_entered"] is False
    assert payload["gui_state"] == "unknown"
    assert gui.transport.action_keys() == [], "the reload was never attempted"


def test_undo_keeps_the_backup_for_a_post_dispatch_unknown_reload(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "post_invalidated"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "5", "the disk restore is real"
    assert len(list(live._snapshots(tree))) == 1, "the backup must not be discarded"
    assert payload["history_retained"] is True
    assert payload["gui_state"] == "unknown"


# --- F1: wrapper text must not claim an unverified effect ---------------------


def test_apply_wrapper_reports_the_refusal_without_an_effect_claim(gui, tmp_path):
    """The shipped wrapper must not present the refusal as an applied change."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    result = run_wrapper(
        "live_apply.py", gui.session, path=str(tree), operations=SET_LENGTH, settle_seconds=0
    )
    assert result["success"] is False
    message = result["message"].lower()
    assert "applied and reloaded" not in message
    assert "unverified" not in message.replace("unverifiable", "")
    assert result["error"] == "save_prerequisite_unverified"
    assert result["context"]["save_postcondition"]["established"] is False
    assert result["context"]["adapter_capability"]["save_effect_verifier"] == "NOT_AVAILABLE"


def test_undo_wrapper_message_reports_the_retained_backup(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture
    result = run_wrapper("live_undo.py", gui.session, path=str(tree), settle_seconds=0)
    message = result["message"].lower()
    assert "undone and reloaded" not in message
    assert "unverified" in message
    assert "snapshot is retained" in message


def test_save_wrapper_message_does_not_claim_the_document_was_saved(gui):
    result = run_wrapper("live_save.py", gui.session)
    message = result["message"].lower()
    assert "document saved" not in message
    assert "unverified" in message


def test_revert_wrapper_message_does_not_claim_reloaded(gui):
    result = run_wrapper("live_revert.py", gui.session, settle_seconds=0)
    message = result["message"].lower()
    assert "reloaded from disk" not in message
    assert "unverified" in message


# --- F3: read-only sessions must not require write routes ---------------------


def test_read_only_session_constructs_without_menu_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    read_only = harness.Harness(monkeypatch, allowed_actions=(), menu_routes={})
    state = read_only.session.status()
    assert state["capabilities"]["ui_input"] is False
    assert state["capabilities"]["menu_routes"] == []
    assert read_only.session.capture()["image_bytes"][:8] == b"\x89PNG\r\n\x1a\n"


def test_read_only_session_refuses_mutating_menu_at_menu_time(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    read_only = harness.Harness(monkeypatch, allowed_actions=(), menu_routes={})
    payload = payload_of(live.save, session=read_only.session)
    assert payload["error"] == "menu_route_undeclared"
    assert read_only.transport.methods() == [], "no physical action may be attempted"
