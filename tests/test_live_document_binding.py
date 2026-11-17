"""Regression: undo must refuse a same-basename document without bound identity.

This reproduces the controlled A/tree.spm vs B/tree.spm counterexample using
the production route's existing scripted transport. No native Modeler, task,
process or input is started. The assertion is fail-closed: if no supported
source-bound full document identity exists, undo must preserve BOTH files and
must not deliver Ctrl+R to the bound window.
"""

from __future__ import annotations

from pathlib import Path

import live_ui_harness as harness
import pytest

from dcc_mcp_speedtree import live


def test_real_status_declares_no_full_path_and_no_verification(monkeypatch, tmp_path):
    """The static invariant: no caller flag can create an observation that is absent."""
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch)
    try:
        state = gui.session.status()
        capabilities = state["capabilities"]
        assert capabilities["active_document_path"] is False
        assert capabilities["active_document_verified"] is False
        assert capabilities["active_document_from_title"] is True
        assert "bound_document_path" not in state, (
            "the pixels-only status contract exposes no full active-document path"
        )
    finally:
        gui.session.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"capabilities": {"active_document_verified": True}},  # flag only, no path
        {"bound_document_path": "C:/forged/tree.spm"},  # caller/mock asserted path
        {"capabilities": {"active_document_path": True, "active_document_verified": False}},
        {"scope": "whole_desktop"},  # wrong scope
        {"bound_document_path": 12345},  # non-string
    ],
)
def test_bound_document_observation_rejects_forged_or_partial_states(tmp_path, overrides):
    """No caller boolean, forged path or partial state can manufacture proof."""
    tree = harness.write_tree(tmp_path / "tree.spm", "2")
    base = {
        "scope": "exact_bound_window_only",
        "target": {"process_id": harness.PID, "window_handle": harness.HWND},
        "capabilities": {"active_document_path": False, "active_document_verified": False},
    }
    base.update(overrides)
    assert live._bound_document_observation(base, tree.resolve()) is None


def test_bound_document_observation_rejects_a_different_full_path(tmp_path):
    """Even a typed full-path observation must resolve to the REQUESTED file."""
    a = tmp_path / "A"
    a.mkdir()
    requested = harness.write_tree(a / "tree.spm", "2")
    b = tmp_path / "B"
    b.mkdir()
    other = harness.write_tree(b / "tree.spm", "9")
    state = {
        "scope": "exact_bound_window_only",
        "target": {"process_id": harness.PID, "window_handle": harness.HWND},
        "capabilities": {"active_document_path": True, "active_document_verified": True},
        "bound_document_path": str(other.resolve()),
    }
    assert live._bound_document_observation(state, requested.resolve()) is None


def test_exact_formal_interface_required_for_a_bound_document(tmp_path):
    """Documents the ONE admissible extension point, NOT a route capability.

    Only a typed observation FROM the exact scoped target that declares BOTH
    capabilities true, is scoped to the bound window, and carries a full path
    resolving to the requested file can unlock the guarded transaction. The
    pixels-only route never emits such a state (see the status-invariant test),
    so this is a contract specification, not evidence that the live route works.
    """
    tree = harness.write_tree(tmp_path / "tree.spm", "2")
    state = {
        "scope": "exact_bound_window_only",
        "target": {"process_id": harness.PID, "window_handle": harness.HWND},
        "capabilities": {"active_document_path": True, "active_document_verified": True},
        "bound_document_path": str(tree.resolve()),
    }
    observation = live._bound_document_observation(state, tree.resolve())
    assert observation is not None
    assert observation["resolved_path"] == str(Path(tree).resolve())
    assert observation["authority"] == "scoped_target_observation"
    assert observation["scope"] == "exact_bound_window_only"
    assert observation["established"] is True


def test_undo_refuses_wrong_document_with_same_basename(tmp_path, monkeypatch):
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()
    requested = harness.write_tree(a / "tree.spm", "2")
    active_fixture = harness.write_tree(b / "tree.spm", "9")
    snapshot = harness.seed_snapshot(requested, "5")
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")

    gui = harness.Harness(monkeypatch, title=harness.TITLE)
    # The simulated active document is B; its window title exposes only the
    # shared basename. Pixels-only status declares neither a full path nor a
    # verified active document.
    gui.transport.document_path = active_fixture
    try:
        before = {
            "requested": harness.length(requested),
            "active_fixture": harness.length(active_fixture),
        }
        assert before == {"requested": "2", "active_fixture": "9"}
        with pytest.raises(live.LiveError) as caught:
            live.undo(requested, process_id=harness.PID, settle_seconds=0, session=gui.session)
        payload = caught.value.payload
        assert payload["error"] == "active_document_binding_unverified"
        assert payload["disk_mutation"] is False
        assert payload["history_mutation"] is False
        assert payload["reload_dispatch"] is False
        assert {
            "requested": harness.length(requested),
            "active_fixture": harness.length(active_fixture),
        } == before
        assert gui.transport.action_keys() == []
        assert snapshot.exists()
        assert (tmp_path / "shots").exists() is False
    finally:
        gui.session.close()


def test_undo_refuses_even_matching_basename_without_capability(tmp_path, monkeypatch):
    """A title match and a caller-supplied marker must not manufacture proof."""
    requested = harness.write_tree(tmp_path / "tree.spm", "2")
    snapshot = harness.seed_snapshot(requested, "5")
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, title=harness.TITLE)
    try:
        # A self-asserted path is NOT an observation of the scoped target; the
        # capability contract still declares no full path and no verification.
        gui.transport.document_path = requested
        with pytest.raises(live.LiveError) as caught:
            live.undo(
                requested,
                process_id=harness.PID,
                settle_seconds=0,
                session=gui.session,
            )
        assert caught.value.payload["error"] == "active_document_binding_unverified"
        assert harness.length(requested) == "2"
        assert snapshot.exists()
        assert gui.transport.action_keys() == []
    finally:
        gui.session.close()
