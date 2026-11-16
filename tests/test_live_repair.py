"""Repair regressions for the PR #16 live route.

Covers the raw-route removal, the trusted-session gate, the real bridge entry,
authorization refusal, connection-cleanup truth, the precisely stated missing
API, and the apply/undo recovery receipts. The GUI boundary is a scripted owned
transport: Core's real ``PixelsMcpHostClient`` runs, but no dcc-cua binary is
launched, no Modeler is started and no native input is delivered.
"""

import inspect
import json
from pathlib import Path

import live_ui_harness as harness
import pytest
from dcc_mcp_core.cua_cli import CuaCliError
from live_ui_harness import REVERT_ROUTE, SAVE_ROUTE, length, write_tree

from dcc_mcp_speedtree import live
from dcc_mcp_speedtree.trusted_session import BoundedLiveSession, TrustedLiveExecutionBridge

SET_LENGTH = [
    {"op": "set_property", "node_id": "root", "name": "Spine:Length:Absolute", "value": 9}
]
SRC = Path(live.__file__).resolve().parent


def payload_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except live.LiveError as exc:
        return exc.payload
    raise AssertionError("expected a LiveError")


def _code_strings(module):
    """Every string constant in the module's CODE, ignoring its docstrings."""
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    documented = set()

    def collect_docstrings(node):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                documented.add(text)
            for child in ast.iter_child_nodes(node):
                collect_docstrings(child)

    collect_docstrings(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in documented
    ]


def test_live_module_has_no_raw_powershell_route():
    strings = [value.lower() for value in _code_strings(live)]
    assert not any("powershell" in value for value in strings)
    assert not any(".ps1" in value for value in strings)
    assert "subprocess" not in {name for name in dir(live) if not name.startswith("__")}
    assert not hasattr(live, "SCRIPT")
    assert not list(SRC.glob("*.ps1")), "no PowerShell bridge may ship in the package"


def test_packaging_does_not_ship_the_raw_bridge():
    pyproject = (SRC.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "live.ps1" not in pyproject


def test_every_entry_takes_a_trusted_session_parameter():
    for name in ("status", "screenshot", "save", "revert", "open_recent", "apply", "undo"):
        assert "session" in inspect.signature(getattr(live, name)).parameters


def test_only_the_exact_bounded_session_type_is_accepted():
    class Spoof:
        __class__ = BoundedLiveSession

        def status(self):
            return {}

    payload = payload_of(live.status, session=Spoof())
    assert payload["error"] == "no_authorized_ui_route"
    assert payload_of(live.status, session=object())["error"] == "no_authorized_ui_route"


def test_bridge_injects_only_for_published_entries_and_strips_trusted_params(monkeypatch):
    session = object.__new__(BoundedLiveSession)
    session._closed = False
    bridge = harness.bridge_with_session(session)
    entry = harness.published_live_entry("live_apply.py")

    injected = harness.core_executor_calls(
        monkeypatch,
        bridge,
        entry,
        action_name="speedtree_live__live_apply",
    )
    assert injected["params"].get(live.TRUSTED_SESSION_PARAM) is session

    foreign = str(Path(entry).parent / "foreign_live_apply.py")
    not_injected = harness.core_executor_calls(
        monkeypatch,
        bridge,
        foreign,
        action_name="speedtree_live__live_apply",
    )
    assert live.TRUSTED_SESSION_PARAM not in not_injected["params"]

    forged = harness.core_executor_calls(
        monkeypatch,
        bridge,
        entry,
        action_name="speedtree_live__live_apply",
        params={live.TRUSTED_SESSION_PARAM: "forged", "trusted_other": "x"},
    )
    assert live.TRUSTED_SESSION_PARAM in forged["params"]
    assert forged["params"][live.TRUSTED_SESSION_PARAM] is session
    assert "trusted_other" not in forged["params"]


def test_bridge_is_a_real_host_execution_bridge():
    bridge = TrustedLiveExecutionBridge(dispatcher=None, session_provider=lambda: None)
    assert isinstance(bridge, harness.HostExecutionBridge)


def test_menu_actions_require_runtime_authorization(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    read_only = harness.Harness(monkeypatch, allowed_actions=())
    assert read_only.session.status()["capabilities"]["ui_input"] is False
    payload = payload_of(live.save, session=read_only.session)
    assert payload["error"] == "unauthorized_action"
    assert payload["allowed_actions"] == []
    assert read_only.transport.methods().count("execute_action") == 0


def test_mutating_menu_is_refused_at_menu_time_when_undeclared(monkeypatch, tmp_path):
    """Declaring a write route is optional; using one that is absent is refused."""
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    partial = harness.Harness(monkeypatch, menu_routes={"save": SAVE_ROUTE})
    assert partial.session.status()["capabilities"]["menu_routes"] == ["save"]
    payload = payload_of(live.revert, session=partial.session)
    assert payload["error"] == "menu_route_undeclared"
    assert payload["declared_routes"] == ["save"]
    assert "execute_action" not in partial.transport.methods(), "no physical action"


def test_invalid_menu_routes_are_refused(monkeypatch):
    with pytest.raises(live.LiveError) as raised:
        harness.Harness(
            monkeypatch, menu_routes={"save": {"action": "invoke_menu"}, "revert": REVERT_ROUTE}
        )
    assert raised.value.payload["error"] == "invalid_menu_routes"


def test_open_recent_states_the_missing_contract_precisely(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    payload = payload_of(live.open_recent, tree, session=gui.session)
    assert payload["error"] == "open_recent_unsupported_on_pixels_only_route"
    assert payload["route"] == "owned_mcp_pixels / pixels_only"
    assert len(payload["missing_contract"]) >= 3
    assert len(payload["evidence"]) >= 4
    # The earlier "file-dialog HWND" claim was wrong and is explicitly disclaimed.
    assert any(
        "not inherently require a different file-dialog" in item for item in payload["not_claimed"]
    )
    assert any("transport is not the limit" in item for item in payload["evidence"])
    assert not list(tmp_path.rglob("_live_history"))


def test_connection_cleanup_result_is_truthful(gui):
    first = gui.session.close()
    assert first["cleanup_status"] == "stopped"
    second = gui.session.close()
    assert second == first, "a repeat close must return the same truthful receipt"
    assert gui.transport.closed == 1, "the owned transport is closed exactly once"


def test_a_failed_connection_cleanup_is_retained(gui):
    gui.transport.fail_stop = True
    errors = []
    for _ in range(2):
        with pytest.raises(CuaCliError) as raised:
            gui.session.close()
        errors.append(raised.value)
    assert errors[0] is errors[1], "the cached cleanup failure must be re-raised"
    assert errors[0].native_evidence["cleanup_status"] == "cleanup_failed"


def test_apply_known_non_dispatch_reload_failure_compensates_and_reports_truthfully(gui, tmp_path):
    """Control: only a positively known non-dispatch may roll the edit back."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "not_dispatched"}
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "2", "the user's saved file must be restored"
    assert not list(live._snapshots(tree))
    assert payload["phase"] == "reload"
    assert payload["dispatch"] == "not_dispatched"
    assert payload["file_restored"] is True
    assert payload["history_retained"] is False
    assert payload["history_snapshot"] is None
    assert payload["gui_state"] == "unknown"
    assert payload["error"] == "reload_not_confirmed"
    assert payload["retry"]
    json.dumps(payload)


def test_apply_unclassified_dispatch_error_preserves_mutation_and_backup(gui, tmp_path):
    """A dispatch error the runtime cannot classify is not a known failure."""
    tree = write_tree(tmp_path / "tree.spm")
    gui.transport.fail_action_matching = {"keys": "ctrl+r"}
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9", "the edit stays on disk; the reload may have run"
    snapshots = list(live._snapshots(tree))
    assert len(snapshots) == 1, "the only backup must survive"
    assert payload["error"] == "reload_effect_unknown"
    assert payload["dispatch"] == "unknown_dispatch"
    assert payload["file_restored"] is False
    assert payload["history_retained"] is True
    assert payload["history_snapshot"] == str(snapshots[0])
    assert payload["gui_state"] == "unknown"
    assert payload["native_error"]["type"] == "OwnedCuaMcpError"
    assert payload["recovery"]["restore_with"] == "live_undo"
    assert "compensation_error" not in payload, "no blind compensation may be attempted"
    json.dumps(payload)


def test_apply_compensation_failure_keeps_the_only_backup(gui, tmp_path, monkeypatch):
    tree = write_tree(tmp_path / "tree.spm")
    gui.transport.action_outcomes = {REVERT_ROUTE["keys"]: "not_dispatched"}
    monkeypatch.setattr(
        live, "_replace", lambda src, snap: (_ for _ in ()).throw(OSError("disk full"))
    )
    payload = payload_of(live.apply, tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    snapshots = list(live._snapshots(tree))
    assert len(snapshots) == 1, "the only backup must survive"
    assert payload["file_restored"] is False
    assert payload["history_retained"] is True
    assert payload["history_snapshot"] == str(snapshots[0])
    assert payload["compensation_error"]


def test_undo_keeps_the_snapshot_until_the_reload_is_confirmed(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    gui.transport.fail_action_matching = {"keys": "ctrl+r"}
    payload = payload_of(live.undo, tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "2"
    assert len(list(live._snapshots(tree))) == 1, "the retryable snapshot must survive"
    assert payload["history_retained"] is True
    gui.transport.fail_action_matching = None
    retried = live.undo(tree, settle_seconds=0, session=gui.session)
    assert length(tree) == "2", "the retry still restores the file"
    # A delivered-but-unverifiable reload must never consume the only backup.
    assert retried["undo_depth"] == 1
    assert retried["verification"]["history_retained"] is True


def test_screenshot_failure_after_a_committed_reload_does_not_roll_back(gui, tmp_path):
    tree = write_tree(tmp_path / "tree.spm")
    gui.transport.fail_snapshot_from = 3  # the post-commit observation
    result = live.apply(tree, SET_LENGTH, settle_seconds=0, session=gui.session)
    assert length(tree) == "9", "a committed edit must not be rolled back"
    assert result["undo_depth"] == 1
    assert result["screenshot"] is None
    assert "capture_proof_rejected" in result["screenshot_error"]
    assert result["reload_effect"] == "unverifiable"


@pytest.fixture
def gui(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "SHOT_DIR", tmp_path / "shots")
    return harness.Harness(monkeypatch)
