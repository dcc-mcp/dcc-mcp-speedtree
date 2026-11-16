"""Owned export process-tree supervision contract (RED/GREEN regression).

Only isolated, short, own-Python child fixtures are spawned. No Modeler,
Blender, UI, Host, MCP, Core/Rust compile or global process sweep. A fixture
PASS is NOT a real-machine Modeler supervision pass; native stays NOT_RUN.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from dcc_mcp_core.cancellation import (
    CancelToken,
    DccMcpCancelledError,
    reset_cancel_token,
    set_cancel_token,
)

from dcc_mcp_speedtree.export import export_batch, verify_export
from dcc_mcp_speedtree.process import run_modeler

FIX = Path(__file__).parent / "fixtures"
CHILD = str(FIX / "owned_tree_child.py")
GRANDCHILD = str(FIX / "owned_tree_grandchild.py")


def _pid_alive(pid):
    """Return True only if pid still designates a running (non-zombie) process."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return (not ok) or code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file():
        try:
            state = stat.read_text().rsplit(") ", 1)[-1].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
    return True


def _settle_dead(pid, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.02)
    return not _pid_alive(pid)


def _argv(work, child_sleep, grandchild_sleep):
    return [sys.executable, CHILD, str(work), GRANDCHILD, str(child_sleep), str(grandchild_sleep)]


def _marker(work, name, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = work / name
        if path.is_file():
            return int(path.read_text())
        time.sleep(0.02)
    raise AssertionError(f"fixture marker {name} was not written")


def _run(argv, work, timeout):
    log = work / "export.log"
    with log.open("wb") as output:
        return run_modeler(argv, cwd=str(work), stdout=output, timeout=timeout)


# 1) Timeout must terminate the WHOLE owned tree and attach a return receipt.
def test_timeout_returns_whole_tree_within_unified_deadline(tmp_path):
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _run(_argv(tmp_path, 20, 20), tmp_path, 6.0)
    elapsed = time.monotonic() - start
    receipt = getattr(caught.value, "process_tree", None)
    assert receipt is not None, "timeout carried no owned-tree return receipt"
    assert receipt["drained"] is True, receipt
    assert elapsed < 12.0, f"cleanup exceeded the finite deadline: {elapsed:.2f}s"
    grandchild = _marker(tmp_path, "grandchild.pid")
    assert _settle_dead(grandchild), "grandchild survived timeout cleanup"


# 2) Cancellation must terminate the WHOLE owned tree and still propagate.
def test_cancellation_returns_whole_tree_and_propagates(tmp_path):
    token = CancelToken()

    def cancel_when_tree_exists():
        deadline = time.monotonic() + 8
        while not (tmp_path / "grandchild.pid").is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        token.cancel()

    threading.Thread(target=cancel_when_tree_exists, daemon=True).start()
    marker = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError) as caught:
            _run(_argv(tmp_path, 20, 20), tmp_path, 12.0)
    finally:
        reset_cancel_token(marker)
    receipt = getattr(caught.value, "process_tree", None)
    assert receipt is not None, "cancellation carried no owned-tree return receipt"
    assert receipt["drained"] is True, receipt
    grandchild = _marker(tmp_path, "grandchild.pid")
    assert _settle_dead(grandchild), "grandchild survived cancellation cleanup"


# 3) Normal exit must report that the whole tree drained (not just the parent).
def test_normal_exit_reports_drained_tree_receipt(tmp_path):
    result = _run(_argv(tmp_path, 0.1, 0.1), tmp_path, 10.0)
    assert result.returncode == 0
    receipt = result.process_tree
    assert receipt["status"] == "drained"
    assert receipt["drained"] is True
    assert receipt["clean_exit"] is True
    assert receipt["owned_before_spawn"] is True
    assert receipt["child_assigned"] is True


# 4) Parent-only exit with a lingering descendant is UNKNOWN, never success.
def test_parent_only_exit_with_lingering_descendant_is_unknown(tmp_path):
    result = _run(_argv(tmp_path, 0.1, 20), tmp_path, 6.0)
    receipt = result.process_tree
    assert receipt["clean_exit"] is False, receipt
    assert receipt["status"] in {"terminated", "unknown"}, receipt
    grandchild = _marker(tmp_path, "grandchild.pid")
    assert _settle_dead(grandchild), "lingering descendant was not cleaned up"


# 5) An unownable/uncooperative child must be bounded and truthfully UNKNOWN.
# Mock contract only: no OS handle, so no whole-tree claim is possible.
def test_unownable_child_cleanup_is_bounded_and_unknown(tmp_path, monkeypatch):
    class Stuck:
        killed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def wait(self, timeout=None):
            if timeout is None:
                return -9
            raise subprocess.TimeoutExpired("modeler", timeout)

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    stuck = Stuck()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: stuck)
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_modeler(["modeler"], cwd=str(tmp_path), stdout=None, timeout=1.5)
    elapsed = time.monotonic() - start
    assert elapsed < 8.0, f"cleanup was not bounded: {elapsed:.2f}s"
    assert stuck.killed
    receipt = getattr(caught.value, "process_tree", None)
    assert receipt is not None
    assert receipt["drained"] is False
    assert receipt["status"] == "unknown"


# 6) Concurrent runs must each own a separate tree (no shared/global state).
def test_concurrent_runs_own_separate_trees(tmp_path):
    results = {}

    def worker(key):
        work = tmp_path / key
        work.mkdir()
        results[key] = _run(_argv(work, 0.1, 0.1), work, 10.0)

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not any(t.is_alive() for t in threads)
    assert {k: v.process_tree["drained"] for k, v in results.items()} == {"a": True, "b": True}
    assert results["a"].process_tree["child_pid"] != results["b"].process_tree["child_pid"]


# 7) export_batch must refuse "exported" when the tree return is UNKNOWN.
def test_export_batch_refuses_unknown_tree_drain(tmp_path, monkeypatch):
    exe = tmp_path / "SpeedTree_Modeler.exe"
    exe.write_bytes(b"test executable")
    source = tmp_path / "Tree.spm"
    source.write_bytes(b"test source")
    preset = tmp_path / "Preset.ini"
    preset.write_text("[General]\nType=VFX\n")
    monkeypatch.setenv("DCC_MCP_SPEEDTREE_EXECUTABLE", str(exe))

    def fake(argv, **kwargs):
        Path(argv[2]).write_bytes(b"# Wavefront OBJ\nv 0 0 0\n")
        return SimpleNamespace(
            returncode=0,
            process_tree={
                "status": "unknown",
                "drained": False,
                "reason": "tree_drain_not_confirmed",
            },
        )

    monkeypatch.setattr("dcc_mcp_speedtree.export.run_modeler", fake)
    result = export_batch([str(source)], str(preset), str(tmp_path / "output"), "obj")
    assert result["items"][0]["status"] == "tree_drain_unknown", result["items"][0]
    assert result["status"] == "failed"
    assert not verify_export(result["manifest_path"])["verified"]
