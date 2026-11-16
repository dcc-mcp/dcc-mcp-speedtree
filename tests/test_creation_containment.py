"""Creation-containment regression for the owned export process tree.

The child must belong to THIS Job before its first instruction executes, or
creation must be explicitly rejected with no leak. Evidence is the real Job
accounting plus the child's own first-action marker, captured at the exact
assignment boundary while a deterministic event barrier holds the sequence.
Self-reported booleans and "late AssignProcessToJobObject succeeded" mocks are
not used as proof.

Only isolated, short, own-Python children and the Windows Job Object are used.
No Modeler, Blender, Host, MCP, UI, Core/Rust compile, process/PID enumeration
or post-hoc subtree kill. A fixture PASS is NOT a real-machine supervision pass.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from dcc_mcp_speedtree import process as process_module
from dcc_mcp_speedtree.process import OwnedTreeError, run_modeler

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object creation barrier")

FIX = Path(__file__).parent / "fixtures"
CHILD = str(FIX / "owned_tree_child.py")
GRANDCHILD = str(FIX / "owned_tree_grandchild.py")

# Bounded window in which the unfixed child is FREE to run. On the fixed path
# CREATE_SUSPENDED closes the race; the window only observes the negative.
_OBSERVE_SECONDS = 5.0
_BARRIER_TIMEOUT = 20.0


def _argv(work, child_sleep, grandchild_sleep):
    return [sys.executable, CHILD, str(work), GRANDCHILD, str(child_sleep), str(grandchild_sleep)]


def _run(argv, work, timeout):
    with (work / "export.log").open("wb") as output:
        return run_modeler(argv, cwd=str(work), stdout=output, timeout=timeout)


def _marker_appears(work, name, timeout):
    """Bounded negative observation: did the child's first action happen?"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (work / name).is_file():
            return True
        time.sleep(0.02)
    return (work / name).is_file()


def _read_pid(work, name, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (work / name).is_file():
            return int((work / name).read_text(encoding="utf-8"))
        time.sleep(0.02)
    raise AssertionError(f"fixture marker {name} was not written")


def _pid_alive(pid):
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


def _settle_dead(pid, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.02)
    return not _pid_alive(pid)


def _process_id_of(handle):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetProcessId.argtypes = [wintypes.HANDLE]
    k32.GetProcessId.restype = wintypes.DWORD
    return k32.GetProcessId(wintypes.HANDLE(handle))


class _HeldRun:
    """Run run_modeler in a thread so the main thread can hold the barrier."""

    def __init__(self, argv, work, timeout):
        self.argv, self.work, self.timeout = argv, work, timeout
        self.before = threading.Event()
        self.release = threading.Event()
        self.after = threading.Event()
        self.captured = {}
        self.box = {}
        self.thread = threading.Thread(target=self._worker, daemon=True)

    def _worker(self):
        try:
            self.box["result"] = _run(self.argv, self.work, self.timeout)
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            self.box["error"] = exc

    def start(self):
        self.thread.start()
        assert self.before.wait(_BARRIER_TIMEOUT), "Popen never reached Job assignment"
        return self

    def observe_then_release(self, name):
        try:
            return _marker_appears(self.work, name, _OBSERVE_SECONDS)
        finally:
            self.release.set()

    def join(self):
        assert self.after.wait(_BARRIER_TIMEOUT), "the held assignment never completed"
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "run_modeler did not return within the finite deadline"


# 1) The child must be IN this Job BEFORE its first instruction can execute.
# The regression child spawns a grandchild at the earliest executable moment
# and its root exits rapidly. Holding the assignment barrier exposes the race:
# on a late-assign implementation the child demonstrably runs during the hold.
def test_child_belongs_to_job_before_first_execution(tmp_path, monkeypatch):
    real_assign = process_module._job_assign
    run = _HeldRun(_argv(tmp_path, 0.05, 8), tmp_path, 20.0)

    def gated_assign(job, process_handle):
        run.captured["job"] = job
        run.before.set()
        error = None
        try:
            if not run.release.wait(_BARRIER_TIMEOUT):
                raise AssertionError("assignment barrier was never released")
            try:
                real_assign(job, process_handle)
            except OSError as exc:
                error = exc
            # Exact boundary: assigned, but on the fixed path still suspended;
            # _job_resume is called only after _job_assign returns.
            run.captured["active"], run.captured["total"] = process_module._job_accounting(job)
            run.captured["child_ran"] = (tmp_path / "child.pid").is_file()
        finally:
            run.after.set()
        if error is not None:
            raise error

    monkeypatch.setattr(process_module, "_job_assign", gated_assign)
    run.start()
    observed = run.observe_then_release("child.pid")
    run.join()
    assert observed is False, (
        "child executed its first instruction before the creation barrier; "
        "a late AssignProcessToJobObject cannot contain an escaped subtree"
    )
    # Independent proof of membership: real Job accounting at that boundary
    # shows a live child in THIS Job that has not executed yet.
    assert run.captured["total"] >= 1, run.captured
    assert run.captured["active"] >= 1, run.captured
    assert run.captured["child_ran"] is False, run.captured
    assert "error" not in run.box, repr(run.box.get("error"))
    receipt = run.box["result"].process_tree
    # A grandchild spawned at the earliest moment was captured by the Job and
    # returned, not left as an unowned subtree.
    assert receipt["total_processes"] >= 2, receipt
    assert receipt["drained"] is True, receipt
    assert receipt["clean_exit"] is False, receipt
    assert _settle_dead(_read_pid(tmp_path, "grandchild.pid")), "earliest descendant survived"


# 2) A real assignment failure must reject creation with NO executed child and
# NO leaked descendant. The failure is held behind the same barrier so a
# late-assign implementation cannot win by timing luck.
def test_creation_rejection_leaves_no_executed_child(tmp_path, monkeypatch):
    run = _HeldRun(_argv(tmp_path, 0.05, 8), tmp_path, 12.0)

    def failing_assign(job, process_handle):
        run.captured["pid"] = _process_id_of(int(process_handle))
        run.before.set()
        held = run.release.wait(_BARRIER_TIMEOUT)
        run.after.set()
        assert held, "rejection barrier was never released"
        raise OSError("AssignProcessToJobObject failed (injected creation failure)")

    monkeypatch.setattr(process_module, "_job_assign", failing_assign)
    run.start()
    observed = run.observe_then_release("child.pid")
    run.join()
    assert observed is False, "a rejected child executed its first instruction"
    assert not (tmp_path / "child.pid").is_file(), "a rejected child executed"
    assert not (tmp_path / "grandchild.pid").is_file(), "a rejected child spawned a descendant"
    assert run.captured.get("pid"), "no child pid was observed"
    assert _settle_dead(run.captured["pid"]), "rejected child was left running"
    assert isinstance(run.box.get("error"), OwnedTreeError), run.box
    receipt = getattr(run.box["error"], "process_tree", None)
    assert isinstance(receipt, dict), "creation failure carried no truthful receipt"
    assert receipt["clean_exit"] is False, receipt
    assert receipt["drained"] is False, receipt
    assert receipt["status"] == "unknown", receipt


# 3) A real SetInformationJobObject return-value failure must be detected and
# produce finite cleanup / UNKNOWN evidence without ever launching a child.
# Injecting the return value exercises the production check itself; the fixed
# structure/info-class contract (WinError 87) is retained, not relaxed.
def test_setinformation_return_failure_is_bounded_and_unknown(tmp_path, monkeypatch):
    real_kernel32 = process_module._k32
    calls = []

    class FailingKernel32:
        def __getattr__(self, name):
            return getattr(real_kernel32, name)

        def SetInformationJobObject(self, *args):
            calls.append(args[1])  # info class must remain ExtendedLimitInformation=9
            ctypes.set_last_error(87)  # reproduce the original real WinError 87
            return 0  # real API return-value failure

    monkeypatch.setattr(process_module, "_k32", FailingKernel32())
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("a child was launched after the Job limit call failed"),
    )
    start = time.monotonic()
    with pytest.raises(OSError) as caught:
        run_modeler([sys.executable, "-c", "pass"], cwd=str(tmp_path), stdout=None, timeout=10)
    assert time.monotonic() - start < 5.0, "cleanup after the API failure was not finite"
    assert calls == [9], f"real SetInformationJobObject info class changed: {calls}"
    receipt = getattr(caught.value, "process_tree", None)
    assert isinstance(receipt, dict), "API failure carried no truthful UNKNOWN receipt"
    assert receipt["clean_exit"] is False, receipt
    assert receipt["drained"] is False, receipt
    assert receipt["status"] == "unknown", receipt
