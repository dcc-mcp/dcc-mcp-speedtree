"""The write-phase / result matrix for save, apply, undo and revert.

Save/apply/undo admission precedes any command. Reachable revert delivery and
the retained helper contracts distinguish structured false results, exceptions
and partial insertion; none alone proves that nothing was executed. Direct
classification/recovery checks remain in ``test_live_dispatch_contract``.

The assertions are about external facts: the value actually in the file, whether
a history snapshot exists, what the real shipped wrapper reports, and whether a
dependent write happened at all. Labels and call counts alone carry nothing --
the proved-no-dispatch control uses an adapter-owned boundary before ``execute``
is entered, or the runtime's own pre-dispatch evidence.

No dcc-cua binary, no Modeler, no native call: only ``OwnedCuaMcpTransport`` is
replaced, so Core's real ``PixelsMcpHostClient`` still runs its own fences.
"""

import json

import live_ui_harness as harness
import pytest
from live_ui_harness import REVERT_ROUTE, SAVE_ROUTE, length, write_tree

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
    import runpy

    module = runpy.run_path(harness.published_live_entry(name))
    return module["main"](**params, **{live.TRUSTED_SESSION_PARAM: session})


# --- save ---------------------------------------------------------------------


def test_save_structured_false_is_refused_and_never_reported_as_saved(gui):
    gui.transport.delivery_success = False  # bare false flags, i.e. a partial
    payload = payload_of(live.save, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert payload["save_dispatch"] is False
    result = run_wrapper("live_save.py", gui.session)
    assert result["success"] is False
    assert "saved" not in result["message"].lower()
    assert result["context"]["save_dispatch"] is False
    assert gui.transport.action_keys() == []


def test_save_binding_gate_precedes_a_successful_delivery_fixture(gui):
    saved = payload_of(live.save, session=gui.session)
    assert saved["error"] == "active_document_binding_unverified"
    assert saved["save_dispatch"] is False
    result = run_wrapper("live_save.py", gui.session)
    message = result["message"].lower()
    assert "document saved" not in message, "delivery is not the effect"
    assert result["success"] is False
    assert result["context"]["gui_state"] == "unknown"
    assert gui.transport.action_keys() == []


def test_save_binding_gate_precedes_a_transport_exception(gui):
    gui.transport.fail_action_matching = {"keys": SAVE_ROUTE["keys"]}
    payload = payload_of(live.save, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert payload["save_dispatch"] is False
    assert gui.transport.action_keys() == []


# --- apply: document admission ------------------------------------------------


def test_apply_refuses_the_dependent_edit_for_every_save_fixture(gui, tmp_path):
    """None of the three armed Save effects may run before document admission."""
    for effect in ("none", "touch", "content"):
        folder = tmp_path / effect
        folder.mkdir()
        tree = write_tree(folder / "tree.spm")
        gui.arm_document(tree, effect=effect)
        gui.transport.calls.clear()
        payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
        assert payload["error"] == "active_document_binding_unverified"
        assert payload["phase"] == "active_document_binding"
        assert payload["save_dispatch"] is False
        assert payload["disk_mutation"] is False
        assert payload["history_mutation"] is False
        assert payload["document_binding"]["established"] is False
        assert payload["adapter_capability"]["active_document_path_verifier"] == "NOT_AVAILABLE", (
            "the gap must be named as an adapter capability, not a protocol claim"
        )
        assert length(tree) == "2", "the gate precedes even the fixture's Save"
        assert not live._history(tree).exists(), "no history may be created"
        assert not list(live._snapshots(tree))
        assert not list(tmp_path.rglob(".live_*"))
        assert gui.transport.action_keys() == [], "no Save or reload may be attempted"
        json.dumps(payload)


def test_apply_never_reaches_the_edit_even_with_a_fixture_flush(gui, tmp_path):
    """An armed fixture cannot bypass admission or flush its pending value."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree, pending="13", effect="content")
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert length(tree) == "2"
    assert payload["save_dispatch"] is False
    assert gui.transport.action_keys() == []
    assert not live._history(tree).exists(), "no snapshot of a refused phase"


@pytest.mark.parametrize("effect", ["none", "touch", "content"])
def test_apply_refusal_reaches_the_wrapper_without_an_effect_claim(gui, tmp_path, effect):
    """The shipped wrapper must not present the refusal as an applied change."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree, effect=effect)
    result = run_wrapper(
        "live_apply.py", gui.session, path=str(tree), operations=SET_LENGTH, settle_seconds=0
    )
    assert result["success"] is False
    assert result["error"] == "active_document_binding_unverified"
    assert "applied" not in result["message"].lower()
    assert result["context"]["disk_mutation"] is False
    assert result["context"]["history_mutation"] is False
    assert result["context"]["save_dispatch"] is False
    assert result["context"]["document_binding"]["established"] is False
    assert (
        result["context"]["adapter_capability"]["active_document_path_verifier"] == "NOT_AVAILABLE"
    )
    assert length(tree) == "2"
    assert gui.transport.action_keys() == []


# --- apply: edit / reload ------------------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected_dispatch",
    [
        ("post_invalidated", "delivered_unverified"),
        ("partial", "partial"),
        ("transport_error", "unknown_dispatch"),
    ],
)
def test_apply_reload_uncertainty_never_reaches_the_dependent_phase(
    gui, tmp_path, outcome, expected_dispatch
):
    """The gate comes first, so no reload-uncertainty form can start an edit.

    Both write entries now refuse at the active-document binding gate.
    No dependent edit
    or reload-uncertainty form is reachable on the pixels-only route.
    """
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: outcome}
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert length(tree) == "2", "no adapter edit may exist to preserve or roll back"
    assert not live._history(tree).exists()
    assert gui.transport.action_keys() == []


def test_undo_binding_gate_precedes_a_missing_revert_route(monkeypatch, tmp_path):
    """The gate is the first refusal, before even the menu-route boundary."""
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, menu_routes={"save": SAVE_ROUTE})  # no revert route
    tree = write_tree(tmp_path / "tree.spm")
    snap = harness.seed_snapshot(tree, "5")  # controlled fixture
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert payload["error"] == "active_document_binding_unverified"
    assert payload["disk_mutation"] is False
    assert payload["history_mutation"] is False
    assert payload["reload_dispatch"] is False
    assert length(tree) == "2", "the file is never restored"
    assert snap.is_file(), "the snapshot is retained"
    assert gui.transport.action_keys() == [], "no reload was attempted"


# --- undo / revert -------------------------------------------------------------


def test_undo_wrapper_reports_the_refusal_without_an_effect_claim(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture, not an apply
    result = run_wrapper("live_undo.py", gui.session, path=str(tree), settle_seconds=0)
    assert result["success"] is False
    assert length(tree) == "2", "no disk restore is a real, external fact"
    message = result["message"].lower()
    assert "undone and reloaded" not in message
    assert "restored" not in message
    assert "refuses" in message
    assert result["error"] == "active_document_binding_unverified"
    assert result["context"]["disk_mutation"] is False
    assert result["context"]["history_mutation"] is False
    assert result["context"]["reload_dispatch"] is False


def test_undo_keeps_the_snapshot_for_every_uncertain_dispatch_form(gui, tmp_path):
    """No delivery outcome can unlock undo without a bound-document observation."""
    tree = write_tree(tmp_path / "tree.spm")
    harness.seed_snapshot(tree, "5")  # controlled fixture
    for outcome in ("post_invalidated", "partial", "transport_error"):
        gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: outcome}
        payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
        assert payload["error"] == "active_document_binding_unverified", outcome
        assert length(tree) == "2", f"{outcome}: the file stays"
        assert len(list(live._snapshots(tree))) == 1, f"{outcome}: the backup survives"
        assert payload["disk_mutation"] is False
        assert gui.transport.action_keys() == [], outcome


def test_revert_structured_false_is_refused_and_not_reported_as_reloaded(gui):
    gui.transport.delivery_success = False
    payload = payload_of(live.revert, settle_seconds=0, shot=False, session=gui.session)
    assert payload["error"] == "revert_not_confirmed"
    assert payload["dispatch"] == "partial"
    result = run_wrapper("live_revert.py", gui.session, settle_seconds=0)
    assert result["success"] is False
    assert "reloaded" not in result["message"].lower()


# --- read-only sessions --------------------------------------------------------


def test_read_only_session_serves_status_and_capture_without_write_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    read_only = harness.Harness(monkeypatch, allowed_actions=(), menu_routes={})
    state = read_only.session.status()
    assert state["capabilities"]["ui_input"] is False
    assert state["capabilities"]["menu_routes"] == []
    assert read_only.session.capture()["image_bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    assert "execute_action" not in read_only.transport.methods()
