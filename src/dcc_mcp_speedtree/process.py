"""Own and drain one Modeler process tree under the core cancellation contract.

On Windows the child is created SUSPENDED, assigned to this call's Job Object
while it cannot execute a single instruction, and only then resumed. No process
or thread enumeration and no post-hoc subtree kill are used: the resume works
solely on the process handle already owned by ``subprocess.Popen``. A POSIX
child is placed in a new session before exec, which is likewise creation-time.
Every wait is bounded by one finite deadline; the whole owned tree is terminated
and its return is evidenced before the call returns or raises. A parent-only exit
is never reported as a whole-tree success, and a tree whose return cannot be
confirmed stays UNKNOWN.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress

from dcc_mcp_core.cancellation import check_cancelled

_POLL_SECONDS = 0.25
_CLEANUP_GRACE_SECONDS = 2.0
_CREATE_SUSPENDED = 0x00000004
_STATUS_SUCCESS = 0


class OwnedTreeError(RuntimeError):
    """A real export child could not be placed under whole-tree ownership."""


class _ModelerResult(subprocess.CompletedProcess):
    """CompletedProcess carrying the owned process-tree return receipt."""


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectExtendedLimitInformation = 9
    _JobObjectBasicAccountingInformation = 1

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
    ]
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    # NtResumeProcess releases the whole process using only our own child's
    # process handle. No Thread32/Snapshot enumeration, no unknown PID, no
    # post-hoc subtree kill. If unavailable, creation is rejected (no leak).
    try:
        _NtResumeProcess = _ntdll.NtResumeProcess
        _NtResumeProcess.argtypes = [wintypes.HANDLE]
        _NtResumeProcess.restype = ctypes.c_long
    except AttributeError:
        _NtResumeProcess = None

    def _job_create():
        # Real API contract: the KILL_ON_JOB_CLOSE flag belongs in
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION with info class 9. Sending the
        # basic-limit structure (or a mismatched class) yields WinError 87.
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(
            job,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            _k32.CloseHandle(job)
            raise error
        return job

    def _job_assign(job, process_handle):
        if not _k32.AssignProcessToJobObject(job, wintypes.HANDLE(process_handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _job_resume(process_handle):
        """Release the creation barrier on a child already owned by this Job."""
        if _NtResumeProcess is None:
            raise OSError("NtResumeProcess unavailable; refusing to resume an unowned child")
        status = _NtResumeProcess(wintypes.HANDLE(process_handle))
        if status != _STATUS_SUCCESS:
            raise OSError(f"NtResumeProcess failed: NTSTATUS 0x{status & 0xFFFFFFFF:08x}")
        return status

    def _job_terminate(job):
        if not _k32.TerminateJobObject(job, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def _job_accounting(job):
        info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        returned = wintypes.DWORD()
        if not _k32.QueryInformationJobObject(
            job,
            _JobObjectBasicAccountingInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            ctypes.byref(returned),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.ActiveProcesses, info.TotalProcesses

    def _job_close(job):
        # KILL_ON_JOB_CLOSE is the fallback for any survivor after a drain.
        _k32.CloseHandle(job)


class _OwnedProcessTree:
    """One supervision object owned before spawn; drains the whole child tree."""

    def __init__(self):
        self.kind = "windows_job_object" if os.name == "nt" else "posix_process_group"
        self._job = _job_create() if os.name == "nt" else None
        self._pgid = None
        self.assigned = False
        self.unownable_reason = None
        # Windows: CREATE_SUSPENDED + assign + resume. POSIX: setsid() in the
        # child before exec is itself a creation-time ownership barrier.
        self.creation_barrier = "CREATE_SUSPENDED" if os.name == "nt" else "start_new_session"
        self.assigned_before_resume = False if os.name == "nt" else None
        self.resume_status = None
        self.members_before_resume = None

    def popen_kwargs(self):
        if os.name == "nt":
            flags = _CREATE_SUSPENDED
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                flags |= subprocess.CREATE_NO_WINDOW
            return {"creationflags": flags}
        return {"start_new_session": True}

    def bind(self, process):
        if os.name == "nt":
            handle = getattr(process, "_handle", None)
            if handle is None:
                # Unit-test fake / no OS handle: no whole-tree claim is possible.
                # A real Popen always owns _handle; the bounded cleanup path then
                # kills and reaps the child without ever claiming containment.
                self.unownable_reason = "no_windows_process_handle"
                return
            native_handle = int(handle)  # borrowed; Popen owns and closes it
            try:
                _job_assign(self._job, native_handle)
            except OSError as exc:
                raise OwnedTreeError(
                    "Cannot own the export process tree before its first execution"
                ) from exc
            self.assigned = True
            # The child is STILL SUSPENDED here. It belongs to this Job and has
            # not executed a single instruction. Take real accounting evidence
            # at that boundary instead of asserting a self-reported boolean.
            try:
                active, total = _job_accounting(self._job)
            except OSError as exc:
                raise OwnedTreeError("Cannot verify creation-time Job membership") from exc
            self.members_before_resume = {"active": active, "total": total}
            self.assigned_before_resume = True
            if total < 1:
                raise OwnedTreeError("Child was not in this Job before its first execution")
            try:
                self.resume_status = _job_resume(native_handle)
            except OSError as exc:
                raise OwnedTreeError("Cannot release the export process creation barrier") from exc
        else:
            pid = getattr(process, "pid", None)
            if not isinstance(pid, int):
                self.unownable_reason = "no_child_pid"
                return
            self._pgid = pid
            self.assigned = True

    def accounting(self):
        """(active, total); (None, None) when whole-tree evidence is unavailable."""
        if os.name == "nt":
            if not self.assigned or self._job is None:
                return None, None
            try:
                return _job_accounting(self._job)
            except OSError:
                return None, None
        if self._pgid is None:
            return None, None
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return 0, None
        except PermissionError:
            return None, None
        return 1, None

    def drain(self, deadline):
        """Bounded wait for whole-tree quiescence; never waits past deadline."""
        while True:
            active, total = self.accounting()
            base = {"active_processes": active, "total_processes": total}
            if active is None:
                return {
                    **base,
                    "status": "unknown",
                    "drained": False,
                    "reason": self.unownable_reason or "accounting_unavailable",
                }
            if active == 0:
                return {**base, "status": "drained", "drained": True, "reason": None}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    **base,
                    "status": "unknown",
                    "drained": False,
                    "reason": "deadline_exhausted",
                }
            time.sleep(min(_POLL_SECONDS, remaining))

    def terminate(self, process, deadline):
        """Terminate the WHOLE owned tree, then bounded reap + bounded drain."""
        if self.assigned:
            try:
                if os.name == "nt":
                    _job_terminate(self._job)
                else:
                    with suppress(ProcessLookupError, PermissionError):
                        os.killpg(self._pgid, signal.SIGKILL)
            except OSError:
                pass
        if process is not None:
            with suppress(OSError, ValueError):
                if process.poll() is None:
                    process.kill()
            with suppress(subprocess.TimeoutExpired, OSError, ValueError):
                process.wait(
                    timeout=max(0.001, min(_CLEANUP_GRACE_SECONDS, deadline - time.monotonic()))
                )
        receipt = self.drain(deadline)
        receipt["forced_termination"] = True
        receipt["status"] = "terminated" if receipt["drained"] else "unknown"
        return receipt

    def close(self):
        if os.name == "nt" and self._job is not None:
            _job_close(self._job)
            self._job = None


def run_modeler(argv, *, cwd, stdout, timeout):
    """Run one owned Modeler process tree and return its whole-tree receipt."""
    check_cancelled()
    started = time.monotonic()
    deadline = started + timeout
    grace = min(_CLEANUP_GRACE_SECONDS, max(0.0, timeout / 2.0))
    wait_deadline = deadline - grace
    tree = None
    process = None
    receipt = {
        "supervision": "windows_job_object" if os.name == "nt" else "posix_process_group",
        "creation_barrier": "CREATE_SUSPENDED" if os.name == "nt" else "start_new_session",
        "job_handle_owner": "run_modeler",
        "child_handle_owner": "subprocess.Popen",
        "fallback_on_handle_close": (
            "kill_on_job_close" if os.name == "nt" else "process_group_kill"
        ),
        "deadline_seconds": timeout,
    }
    try:
        tree = _OwnedProcessTree()  # supervision object created BEFORE spawn
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            shell=False,
            **tree.popen_kwargs(),
        )
        tree.bind(process)
        receipt.update(
            {
                "child_pid": getattr(process, "pid", None),
                "child_assigned": tree.assigned,
                "assigned_while_suspended": tree.assigned_before_resume,
                "job_members_before_resume": tree.members_before_resume,
                "resume_status": tree.resume_status,
                "unownable_reason": tree.unownable_reason,
            }
        )
        while True:
            check_cancelled()
            remaining = wait_deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                returncode = process.wait(timeout=min(_POLL_SECONDS, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        # Parent exit alone is not whole-tree success. Reserve the cleanup
        # grace so a forced termination can still be confirmed as returned.
        normal = tree.drain(min(deadline, time.monotonic() + grace))
        if normal["drained"]:
            receipt.update(normal)
            receipt["clean_exit"] = True
        else:
            forced = tree.terminate(process, deadline)
            receipt.update(forced)
            receipt["clean_exit"] = False
            receipt["reason"] = "whole_tree_required_forced_termination"
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result = _ModelerResult(argv, returncode)
        result.process_tree = receipt
        return result
    except BaseException as exc:
        cleanup_deadline = min(deadline, time.monotonic() + grace)
        if tree is not None:
            forced = tree.terminate(process, cleanup_deadline)
        else:
            # The supervision object itself failed (e.g. a real
            # SetInformationJobObject return-value failure). No child exists;
            # refuse the creation with finite cleanup and truthful UNKNOWN.
            forced = {
                "status": "unknown",
                "drained": False,
                "clean_exit": False,
                "reason": "supervision_object_not_created",
                "active_processes": None,
                "total_processes": None,
                "forced_termination": False,
            }
        receipt.update(forced)
        receipt["clean_exit"] = False
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        with suppress(AttributeError, TypeError):
            exc.process_tree = receipt
        raise
    finally:
        if tree is not None:
            tree.close()
