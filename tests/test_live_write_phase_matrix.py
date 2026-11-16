"""The write-phase / result matrix for save, apply, undo and revert.

Each stage is covered for BOTH response forms -- a structured false result and
an exception -- because neither form proves that nothing was executed: the
runtime keeps ``delivery_completed`` false for a partial insertion too, and an
exception can be raised after input was already inserted.

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
    assert payload["error"] == "save_not_confirmed"
    assert payload["delivery_completed"] is False
    assert payload["dispatch"] == "partial", "false flags are not a proved non-dispatch"
    result = run_wrapper("live_save.py", gui.session)
    assert result["success"] is False
    assert "saved" not in result["message"].lower()
    assert result["context"]["dispatch"] == "partial"


def test_save_delivered_reports_the_unverified_effect_and_the_missing_verifier(gui):
    saved = live.save(session=gui.session)
    assert saved["delivery_completed"] is True
    assert saved["effect"] == "unverifiable"
    assert saved["effect_verifier"]["status"] == "NOT_AVAILABLE"
    result = run_wrapper("live_save.py", gui.session)
    message = result["message"].lower()
    assert "document saved" not in message, "delivery is not the effect"
    assert "unverified" in message
    assert result["context"]["effect_verifier"]["status"] == "NOT_AVAILABLE"
    assert result["context"]["verification"]["status"] == "unknown"


def test_save_exception_is_not_a_proved_non_dispatch(gui):
    gui.transport.fail_action_matching = {"keys": SAVE_ROUTE["keys"]}
    payload = payload_of(live.save, session=gui.session)
    assert payload["dispatch"] == "unknown_dispatch"
    assert payload["native_error"]["type"] == "OwnedCuaMcpError"


# --- apply: save prerequisite --------------------------------------------------


def test_apply_refuses_the_dependent_edit_when_the_save_is_unproven(gui, tmp_path):
    """Delivery alone must not promote to 'the GUI edits are on disk'."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    gui.transport.flush_on_save = False  # delivered, but the file never changes
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert payload["error"] == "save_prerequisite_unverified"
    assert payload["phase"] == "save_prerequisite"
    assert payload["dispatch"] == "delivered"
    assert payload["disk_mutation"] is False
    assert payload["history_mutation"] is False
    assert payload["save_postcondition"]["established"] is False
    assert payload["save_postcondition"]["method"] == "same_task_file_observation"
    assert payload["adapter_capability"]["save_effect_verifier"] == "NOT_AVAILABLE", (
        "the gap must be named as an adapter capability, not a protocol claim"
    )
    # External facts: the file is untouched, no history, no stage, no reload.
    assert length(tree) == "2", "no dependent write may happen"
    assert not live._history(tree).exists(), "no history may be created"
    assert not list(live._snapshots(tree))
    assert not list(tmp_path.glob(".live_*"))
    assert gui.transport.action_keys() == ["ctrl+s"], "the reload must not be attempted"


def test_apply_proceeds_only_with_an_established_save_postcondition(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    result = live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9", "the edit landed on disk"
    assert length(result["history_snapshot"]) == "5", "the snapshot holds the flushed edits"
    postcondition = result["save_postcondition"]
    assert postcondition["established"] is True
    assert postcondition["evidence"]["before"] != postcondition["evidence"]["after"]
    json.dumps(postcondition)  # the receipt stays JSON-serialisable


def test_apply_refusal_reaches_the_wrapper_without_an_effect_claim(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    gui.transport.flush_on_save = False
    result = run_wrapper(
        "live_apply.py", gui.session, path=str(tree), operations=SET_LENGTH, settle_seconds=0
    )
    assert result["success"] is False
    assert result["error"] == "save_prerequisite_unverified"
    assert "applied" not in result["message"].lower()
    assert result["context"]["disk_mutation"] is False
    assert result["context"]["history_mutation"] is False
    assert result["context"]["adapter_capability"]["save_effect_verifier"] == "NOT_AVAILABLE"


# --- apply: edit / reload ------------------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected_dispatch",
    [
        ("post_invalidated", "delivered_unverified"),
        ("partial", "partial"),
        ("transport_error", "unknown_dispatch"),
    ],
)
def test_apply_reload_uncertainty_preserves_the_edit_and_the_backup(
    gui, tmp_path, outcome, expected_dispatch
):
    """Every uncertain form, structured false and exception alike."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: outcome}
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9", "the edit stays; the reload may already have run"
    assert len(list(live._snapshots(tree))) == 1, "the only backup must survive"
    assert payload["dispatch"] == expected_dispatch
    assert payload["file_restored"] is False
    assert payload["history_retained"] is True
    assert payload["gui_state"] == "unknown"
    assert "compensation_error" not in payload, "no blind compensation was attempted"


def test_apply_reload_proved_before_execute_may_compensate(monkeypatch, tmp_path):
    """The control: the refusal happens on this side of the client."""
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    gui = harness.Harness(monkeypatch, menu_routes={"save": SAVE_ROUTE})
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "5", "the saved file is restored"
    assert not list(live._snapshots(tree))
    assert payload["dispatch"] == "not_dispatched"
    assert payload["no_dispatch_proof"]["execute_entered"] is False
    assert payload["file_restored"] is True
    assert payload["history_retained"] is False
    assert gui.transport.action_keys() == ["ctrl+s"], "no reload was attempted"


# --- undo / revert -------------------------------------------------------------


def test_undo_wrapper_reports_the_disk_restore_without_claiming_the_application(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    result = run_wrapper("live_undo.py", gui.session, path=str(tree), settle_seconds=0)
    assert length(tree) == "5", "the disk restore is a real, external fact"
    message = result["message"].lower()
    assert "undone and reloaded" not in message
    assert "unverified" in message, "the Modeler effect is not claimed"
    assert "snapshot is retained" in message
    assert result["context"]["verification"]["status"] == "unknown"


def test_undo_keeps_the_snapshot_for_both_uncertain_forms(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.arm_document(tree)
    live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    for outcome in ("post_invalidated", "partial", "transport_error"):
        gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: outcome}
        payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
        assert length(tree) == "5", f"{outcome}: the disk restore stays"
        assert len(list(live._snapshots(tree))) == 1, f"{outcome}: the backup must survive"
        assert payload["history_retained"] is True


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
