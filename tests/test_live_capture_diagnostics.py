"""Capture error propagation through the real bounded session; native execution=0."""

import builtins
import json
import runpy

import live_ui_harness as harness
import pytest
from dcc_mcp_core.host.cua_mcp_errors import OwnedCuaMcpError

from dcc_mcp_speedtree import live


def capture_error():
    return OwnedCuaMcpError(
        "CaptureFailed",
        "exact-window capture refused",
        {
            "details": {
                "phase": "evidence_dispatch",
                "capture": {
                    "stage": "visible_capture",
                    "reason": "root_overlap",
                    "route": "verified_visible",
                    "target_process_id": harness.PID,
                    "target_window_handle": harness.HWND,
                    "blocker_process_id": 5151,
                    "blocker_window_handle": 6161,
                    "blocker_bounds": [10, 20, 300, 400],
                    "token": "PRIVATE_TOKEN",
                    "CommandLine": "PRIVATE_COMMAND",
                    "title": "PRIVATE_OTHER_APP_BODY",
                    "pixels": "PRIVATE_PIXELS",
                },
            },
        },
    )


def refusing_session(monkeypatch, error):
    gui = harness.Harness(monkeypatch, allowed_actions=(), menu_routes={})

    def reject(**kwargs):
        raise error

    monkeypatch.setattr(gui.client, "snapshot", reject)
    return gui


def test_capture_retains_safe_core_error_details_without_writing_png(monkeypatch, tmp_path):
    gui = refusing_session(monkeypatch, capture_error())
    output = tmp_path / "new" / "capture.png"
    with pytest.raises(live.LiveError) as caught:
        live.screenshot(harness.PID, output, session=gui.session)
    result = caught.value.payload
    assert result["error"] == "capture_proof_rejected"
    assert "exact-window capture refused" in result["message"]
    capture = result["native_evidence"]["details"]["capture"]
    assert capture["blocker_process_id"] == 5151
    assert capture["blocker_window_handle"] == 6161
    assert capture["blocker_bounds"] == [10, 20, 300, 400]
    assert capture["route"] == "verified_visible"
    assert not output.parent.exists()
    assert gui.transport.action_keys() == []


def test_packaged_screenshot_entry_preserves_diagnostics_in_its_error(monkeypatch, tmp_path):
    gui = refusing_session(monkeypatch, capture_error())
    main = runpy.run_path(harness.published_live_entry("live_screenshot.py"))["main"]
    result = main(
        process_id=harness.PID,
        output_path=str(tmp_path / "capture.png"),
        **{live.TRUSTED_SESSION_PARAM: gui.session},
    )
    assert result["success"] is False
    assert result["context"]["native_evidence"]["details"]["capture"]["reason"] == "root_overlap"


def test_capture_resanitizes_core_evidence_and_never_dumps_exception_attributes(monkeypatch):
    error = capture_error()
    error.native_evidence["details"]["capture"]["token"] = "PRIVATE_TOKEN"
    error.native_evidence["details"]["capture"]["CommandLine"] = "PRIVATE_COMMAND"
    error.private_state = "PRIVATE_EXCEPTION_ATTRIBUTE"
    gui = refusing_session(monkeypatch, error)
    with pytest.raises(live.LiveError) as caught:
        gui.session.capture()
    evidence = caught.value.payload["native_evidence"]
    serialized = json.dumps(evidence)
    assert "root_overlap" in serialized
    assert "PRIVATE_" not in serialized


def test_arbitrary_exception_cannot_supply_native_evidence(monkeypatch):
    error = RuntimeError("unclassified capture failure")
    error.native_evidence = {"details": {"capture": {"blocker_process_id": 5151}}}
    gui = refusing_session(monkeypatch, error)
    with pytest.raises(live.LiveError) as caught:
        gui.session.capture()
    assert "native_evidence" not in caught.value.payload
    assert caught.value.payload["error"] == "capture_proof_rejected"


def test_missing_capture_fields_are_not_invented(monkeypatch):
    gui = refusing_session(monkeypatch, OwnedCuaMcpError("CaptureFailed", "refused", {}))
    with pytest.raises(live.LiveError) as caught:
        gui.session.capture()
    assert "native_evidence" not in caught.value.payload


def test_core_without_public_error_projection_keeps_legacy_refusal(monkeypatch):
    gui = refusing_session(monkeypatch, capture_error())
    original_import = builtins.__import__

    def older_core(name, *args, **kwargs):
        if name == "dcc_mcp_core.host.cua_mcp_errors":
            raise ImportError("older Core fixture")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", older_core)
    with pytest.raises(live.LiveError) as caught:
        gui.session.capture()
    assert caught.value.payload["error"] == "capture_proof_rejected"
    assert "native_evidence" not in caught.value.payload


def test_capture_refusal_still_delegates_truthful_idempotent_core_cleanup(monkeypatch):
    gui = refusing_session(monkeypatch, capture_error())
    with pytest.raises(live.LiveError):
        gui.session.capture()
    first = gui.session.close()
    second = gui.session.close()
    assert first == second
    assert sum(name == "stop_task" for name, _ in gui.transport.calls) == 1
    assert gui.transport.closed == 1
