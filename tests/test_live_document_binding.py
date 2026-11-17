"""Regression: undo must refuse a same-basename document without bound identity.

This reproduces the controlled A/tree.spm vs B/tree.spm counterexample using
the production route's existing scripted transport. No native Modeler, task,
process or input is started. The assertion is fail-closed: if no supported
source-bound full document identity exists, undo must preserve BOTH files and
must not deliver Ctrl+R to the bound window.
"""

from __future__ import annotations

import subprocess

import live_ui_harness as harness
import pytest

from dcc_mcp_speedtree import live


@pytest.fixture(autouse=True)
def forbid_native_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Document-binding regressions must launch no child process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


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


@pytest.mark.parametrize("different_directory", [True, False])
def test_apply_requires_document_binding_before_save(tmp_path, monkeypatch, different_directory):
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    requested = harness.write_tree(tmp_path / "A/tree.spm", "2")
    active = harness.write_tree(tmp_path / "B/tree.spm", "9") if different_directory else requested
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, title=harness.TITLE)
    gui.arm_document(active, pending="13", effect="content")
    before = (requested.read_bytes(), active.read_bytes())
    try:
        with pytest.raises(live.LiveError) as caught:
            live.apply(
                requested,
                [
                    {
                        "op": "set_property",
                        "node_id": "root",
                        "name": "Spine:Length:Absolute",
                        "value": 7.5,
                    }
                ],
                process_id=harness.PID,
                settle_seconds=0,
                session=gui.session,
            )
        assert gui.transport.action_keys() == []
        assert (requested.read_bytes(), active.read_bytes()) == before
        assert caught.value.payload["error"] == "active_document_binding_unverified"
        assert not live._history(requested).exists()
        assert not (tmp_path / "shots").exists()
    finally:
        gui.session.close()


def test_save_refuses_before_input_without_document_identity(tmp_path, monkeypatch):
    active = harness.write_tree(tmp_path / "tree.spm", "9")
    gui = harness.Harness(monkeypatch, title=harness.TITLE)
    gui.arm_document(active, pending="13", effect="content")
    before = active.read_bytes()
    try:
        with pytest.raises(live.LiveError) as caught:
            live.save(process_id=harness.PID, session=gui.session)
        assert gui.transport.action_keys() == []
        assert active.read_bytes() == before
        assert caught.value.payload["save_dispatch"] is False
        assert caught.value.payload["requested_path"] is None
    finally:
        gui.session.close()


def test_custom_status_dictionary_cannot_unlock_save(tmp_path, monkeypatch):
    active = harness.write_tree(tmp_path / "tree.spm", "9")
    gui = harness.Harness(monkeypatch, title=harness.TITLE)
    gui.arm_document(active, pending="13", effect="content")
    forged = {
        "scope": "exact_bound_window_only",
        "target": {"process_id": harness.PID, "window_handle": harness.HWND},
        "capabilities": {"active_document_path": True, "active_document_verified": True},
        "bound_document_path": str(active.resolve()),
    }
    monkeypatch.setattr(gui.session, "status", lambda: forged)
    try:
        with pytest.raises(live.LiveError) as caught:
            live.save(process_id=harness.PID, session=gui.session)
        assert caught.value.payload["error"] == "active_document_binding_unverified"
        assert gui.transport.action_keys() == []
        assert harness.length(active) == "9"
    finally:
        gui.session.close()
