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


def _assert_binding_gate_holds(gui, tree, tmp_path, payload):
    assert payload["error"] == "active_document_binding_unverified"
    assert payload["disk_mutation"] is False
    assert payload["history_mutation"] is False
    assert payload["reload_dispatch"] is False
    assert payload["gui_state"] == "unknown"
    assert length(tree) == "2", "the file is never restored or mutated"
    assert len(list(live._snapshots(tree))) == 1, "the only backup is untouched"
    assert gui.transport.action_keys() == [], "no reload may be dispatched"
    assert not (tmp_path / "shots").exists(), "no output work may start"


def test_post_dispatch_unknown_reload_cannot_bypass_the_binding_gate(gui, tmp_path):
    """A possibly-executed reload is moot: undo refuses before any dispatch."""
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture, not an apply
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "post_invalidated"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    _assert_binding_gate_holds(gui, tree, tmp_path, payload)


def test_transport_error_cannot_bypass_the_binding_gate(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "transport_error"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    _assert_binding_gate_holds(gui, tree, tmp_path, payload)


def test_a_missing_revert_route_cannot_bypass_the_binding_gate(monkeypatch, tmp_path):
    """The gate precedes even an adapter-owned no-dispatch boundary in menu()."""
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, menu_routes={"save": harness.SAVE_ROUTE})  # no revert
    tree = write_tree(tmp_path / "tree.spm")
    snap = harness.seed_snapshot(tree, "5")  # controlled fixture
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert length(tree) == "2", "the file stays"
    assert snap.is_file(), "the snapshot is retained"
    assert gui.transport.action_keys() == [], "the reload was never attempted"


def test_undo_keeps_the_backup_for_a_refused_binding(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "post_invalidated"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    _assert_binding_gate_holds(gui, tree, tmp_path, payload)


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


def test_undo_wrapper_reports_the_refusal_without_an_effect_claim(gui, tmp_path):
    """The shipped wrapper must present the fail-closed refusal truthfully."""
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture
    result = run_wrapper("live_undo.py", gui.session, path=str(tree), settle_seconds=0)
    assert result["success"] is False
    message = result["message"].lower()
    assert "undone and reloaded" not in message
    assert "restored" not in message
    assert "refuses" in message
    assert result["error"] == "active_document_binding_unverified"
    assert result["context"]["disk_mutation"] is False
    assert result["context"]["history_mutation"] is False
    assert result["context"]["reload_dispatch"] is False
    assert result["context"]["document_binding"]["established"] is False
    assert result["context"]["adapter_capability"]["active_document_path_verifier"] == (
        "NOT_AVAILABLE"
    )
    assert length(tree) == "2", "no disk restore happened"
    assert len(list(live._snapshots(tree))) == 1


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
