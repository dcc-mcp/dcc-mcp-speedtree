"""Retained dispatch / recovery contracts, verified directly as pure data.

Undo is now fail-closed at the active-document binding gate, so its reload no
longer exercises these helpers through a live entry. They remain part of the
guarded transaction engine (and ``save`` / ``revert`` still classify deliveries),
and the earlier reviews require the truthful unknown / no-input distinction and
recovery receipts to stay correct. These unit checks exercise them directly with
synthetic data -- NO native call, NO Modeler, NO input, NO file mutation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dcc_mcp_speedtree import live
from dcc_mcp_speedtree.trusted_session import (
    DISPATCH_DELIVERED,
    DISPATCH_DELIVERED_UNVERIFIED,
    DISPATCH_NOT_DISPATCHED,
    DISPATCH_PARTIAL,
    DISPATCH_UNKNOWN,
    classify_delivery,
    classify_execution_error,
    native_error_evidence,
    pre_dispatch_refusal,
)


@pytest.mark.parametrize(
    "result, expected",
    [
        (
            {"success": True, "delivery_completed": True, "post_dispatch_validated": True},
            DISPATCH_DELIVERED,
        ),
        (
            {"success": False, "delivery_completed": True, "post_dispatch_validated": False},
            DISPATCH_DELIVERED_UNVERIFIED,
        ),
        (
            {"success": False, "delivery_completed": False, "post_dispatch_validated": False},
            DISPATCH_UNKNOWN,
        ),
        (
            {
                "success": False,
                "delivery_completed": False,
                "requested_events": 2,
                "inserted_events": 1,
                "mutation_attempted": True,
            },
            DISPATCH_PARTIAL,
        ),
        (
            {
                "success": False,
                "delivery_completed": False,
                "details": {
                    "phase": "pre_dispatch",
                    "action_attempted": False,
                    "input_sent": "not_sent",
                    "completion": "known",
                    "effect_unknown": False,
                },
            },
            DISPATCH_NOT_DISPATCHED,
        ),
        (None, DISPATCH_UNKNOWN),
        ("a transport label is not proof", DISPATCH_UNKNOWN),
    ],
)
def test_classify_delivery_never_infers_a_non_dispatch_from_false_flags(result, expected):
    assert classify_delivery(result) == expected


def test_a_false_completion_flag_with_real_input_is_partial_not_proved_no_dispatch():
    """The core earlier review finding: false != not_dispatched."""
    assert (
        classify_delivery(
            {
                "success": False,
                "delivery_completed": False,
                "requested_events": 2,
                "inserted_events": 1,
                "mutation_attempted": True,
            }
        )
        == DISPATCH_PARTIAL
    )
    assert (
        classify_delivery({"success": False, "delivery_completed": False, "input_sent": "sent"})
        == DISPATCH_PARTIAL
    )


def test_pre_dispatch_refusal_is_the_only_adapter_owned_no_dispatch_proof():
    refusal = pre_dispatch_refusal(
        "menu_route_undeclared",
        boundary="menu_route_declaration",
        menu="revert",
        declared_routes=["save"],
    )
    payload = refusal.payload
    assert payload["dispatch"] == DISPATCH_NOT_DISPATCHED
    assert payload["gui_state"] == "unchanged"
    assert payload["no_dispatch_proof"]["boundary"] == "menu_route_declaration"
    assert payload["no_dispatch_proof"]["execute_entered"] is False
    json.dumps(payload)


def test_execution_error_classification_uses_runtime_stage_evidence_only():
    class Staged(Exception):
        native_evidence = {
            "details": {
                "phase": "pre_dispatch",
                "action_attempted": False,
                "input_sent": "not_sent",
                "completion": "known",
                "effect_unknown": False,
            }
        }

    class Unclassified(Exception):
        pass

    assert classify_execution_error(Staged("before dispatch")) == DISPATCH_NOT_DISPATCHED
    assert classify_execution_error(Unclassified("timeout")) == DISPATCH_UNKNOWN


def test_native_error_evidence_projects_only_typed_fields():
    class Boom(Exception):
        code = "scripted_transport_error"
        native_evidence = {"details": {"phase": "pre_dispatch"}}
        fresh_observation_required = True

    evidence = native_error_evidence(Boom("x"))
    assert evidence["type"] == "Boom"
    assert evidence["code"] == "scripted_transport_error"
    assert evidence["native_evidence"] == {"details": {"phase": "pre_dispatch"}}
    assert evidence["fresh_observation_required"] is True
    assert "token" not in evidence and "grant" not in evidence


def test_dispatch_known_failed_requires_the_affirmative_classification():
    for dispatch in (
        DISPATCH_DELIVERED,
        DISPATCH_DELIVERED_UNVERIFIED,
        DISPATCH_PARTIAL,
        DISPATCH_UNKNOWN,
        None,
    ):
        assert live._dispatch_known_failed(live.LiveError({"dispatch": dispatch})) is False
    assert (
        live._dispatch_known_failed(live.LiveError({"dispatch": DISPATCH_NOT_DISPATCHED})) is True
    )
    assert live._dispatch_known_failed(ValueError("no payload")) is False


def test_transaction_error_preserves_recovery_and_dispatch_as_truth():
    cause = pre_dispatch_refusal(
        "menu_action_rejected",
        boundary="fresh_observation_before_execute",
        dispatch=DISPATCH_NOT_DISPATCHED,
        native_error={"type": "OwnedCuaMcpError"},
        no_dispatch_proof={"boundary": "fresh_observation_before_execute"},
    )
    snap = Path("/controlled/snapshot.spm")
    err = live._transaction_error(
        cause,
        phase="reload",
        file_restored=False,
        history_snapshot=snap,
        history_retained=True,
        retry="retry after inspection",
    )
    payload = err.payload
    assert payload["error"] == "menu_action_rejected"
    assert payload["dispatch"] == DISPATCH_NOT_DISPATCHED
    assert payload["no_dispatch_proof"]["boundary"] == "fresh_observation_before_execute"
    assert payload["native_error"]["type"] == "OwnedCuaMcpError"
    assert payload["file_restored"] is False
    assert payload["history_retained"] is True
    assert payload["history_snapshot"] == str(snap)
    assert payload["gui_state"] == "unknown"
    assert payload["retry"]
    json.dumps(payload)


def test_unknown_reload_error_preserves_the_edit_and_the_only_backup():
    cause = live.LiveError({"error": "reload_not_confirmed", "dispatch": DISPATCH_PARTIAL})
    snap = Path("/controlled/snapshot.spm")
    payload = live._unknown_reload_error(cause, snap).payload
    assert payload["error"] == "reload_effect_unknown"
    assert payload["dispatch"] == DISPATCH_PARTIAL
    assert payload["file_restored"] is False
    assert payload["history_retained"] is True
    assert payload["history_snapshot"] == str(snap)
    assert payload["gui_state"] == "unknown"
    json.dumps(payload)


def test_save_disk_observation_has_no_save_authority():
    before = {"sha256": "a" * 64, "size": 10, "mtime_ns": 1}
    changed = {"sha256": "b" * 64, "size": 11, "mtime_ns": 2}
    touched = {"sha256": "a" * 64, "size": 10, "mtime_ns": 2}
    assert live.save_disk_observation(before, changed)["content_changed"] is True
    assert live.save_disk_observation(before, touched)["metadata_only_change"] is True
    assert live.save_disk_observation(before, touched)["content_changed"] is False
    assert live.save_disk_observation(before, changed)["authority"] == "none"
    assert live.save_disk_observation(before, before)["content_changed"] is False


def test_pending_verification_never_claims_a_confirmed_reload():
    result = live._pending_verification(Path("/controlled/snapshot.spm"), True, "note")
    assert result["status"] == "unknown"
    assert result["history_retained"] is True
    assert result["established_by"] is None


def test_reload_view_keeps_delivery_and_effect_distinct():
    view = live._reload_view(
        {
            "dispatch": DISPATCH_DELIVERED,
            "success": True,
            "delivery_completed": True,
            "post_dispatch_validated": True,
            "effect": "unverifiable",
            "verification_required": True,
            "verification": {"status": "unknown"},
        }
    )
    assert view["delivered"] is True
    assert view["effect"] == "unverifiable"
    assert view["verification_required"] is True
    # A delivered reload is still reported as an unverifiable EFFECT.
    assert view["delivered"] is True and view["effect"] == "unverifiable"
    assert view["verification"]["status"] == "unknown"
    # A structured false is NOT a confirmed delivery even without an exception.
    assert (
        live._reload_view(
            {"success": False, "delivery_completed": False, "effect": "unverifiable"}
        )["delivered"]
        is False
    )
