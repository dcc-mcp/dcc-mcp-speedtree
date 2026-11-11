"""Live design loop with a SpeedTree Modeler window the user is watching (Windows only).

The Modeler has no scripting API, so changes go through the file on disk: save the
open document, keep a history copy, rewrite the file with ``edit_graph`` and make the
Modeler reload it with File > Revert to saved. ``live.ps1`` drives the menus through
UI Automation in the background; it never moves the user's mouse or keyboard.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .node_tools import edit_graph

SCRIPT = Path(__file__).with_name("live.ps1")
HISTORY_DIR = "_live_history"
SHOT_DIR = Path(tempfile.gettempdir()) / "speedtree-live"
_NO_WINDOW = 0x08000000


class LiveError(RuntimeError):
    def __init__(self, payload):
        self.payload = dict(payload)
        super().__init__(self.payload.get("message", "SpeedTree live command failed"))


def _run(command, timeout=300, **params):
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-Command",
        command,
    ]
    for key, value in params.items():
        if value not in (None, "", 0):
            args += [f"-{key}", str(value)]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        raise LiveError(
            {"error": "timeout", "message": f"live.ps1 {command} exceeded {timeout}s"}
        ) from None
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise LiveError(
            {"error": "no_output", "message": (proc.stderr or proc.stdout).strip()[-2000:]}
        )
    data = json.loads(lines[-1])
    if not data.get("ok"):
        raise LiveError(data)
    return data


def _history(src: Path) -> Path:
    return src.parent / HISTORY_DIR / src.stem


def _snapshots(src: Path):
    folder = _history(src)
    return sorted(folder.glob(f"*{src.suffix}")) if folder.is_dir() else []


def _replace(src: Path, content_from: Path):
    # Copy beside the target first so the final swap is a single atomic rename.
    staged = src.with_name(f".live_restore_{src.name}")
    shutil.copy2(content_from, staged)
    os.replace(staged, src)


def _require_active(src: Path, process_id):
    instances = _run("status", ProcessId=process_id)["instances"]
    if not instances:
        raise LiveError({"error": "not_running", "message": "No SpeedTree Modeler window found"})
    if len(instances) > 1 and not process_id:
        raise LiveError(
            {
                "error": "ambiguous_instance",
                "message": "Several Modeler windows are open; pass process_id",
                "process_ids": [i["process_id"] for i in instances],
            }
        )
    inst = instances[0]
    if inst.get("modal_dialog"):
        raise LiveError(
            {
                "error": "modal_dialog_open",
                "message": f"Modeler shows dialog '{inst['modal_dialog']}'; close it first",
            }
        )
    if (inst.get("active_document") or "").lower() != src.name.lower():
        raise LiveError(
            {
                "error": "not_active",
                "active_document": inst.get("active_document"),
                "message": f"Modeler shows '{inst.get('active_document')}', not '{src.name}'; use live_open first",
            }
        )
    return inst["process_id"]


def status(process_id=None):
    return _run("status", ProcessId=process_id)


def screenshot(process_id=None, path=None, scale=0.6):
    if not path:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"modeler_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    return _run("screenshot", ProcessId=process_id, Path=path, Scale=scale)


def open_recent(path, process_id=None):
    return _run("recent", ProcessId=process_id, Path=Path(path).resolve(strict=True))


def save(process_id=None):
    return _run("menu", ProcessId=process_id, Menu="File", Item="Save")


def revert(process_id=None, settle_seconds=3.0, shot=True):
    result = _run("revert", ProcessId=process_id)
    if shot:
        time.sleep(settle_seconds)
        result["screenshot"] = screenshot(result["process_id"])["path"]
    return result


def apply(path, operations, process_id=None, settle_seconds=3.0):
    """Save the open tree, record a history copy, apply operations and reload it."""
    src = Path(path).resolve(strict=True)
    pid = _require_active(src, process_id)
    save(pid)  # keeps the user's own GUI edits in the file we edit
    folder = _history(src)
    folder.mkdir(parents=True, exist_ok=True)
    snap = folder / f"{datetime.now():%Y%m%d_%H%M%S_%f}{src.suffix}"
    shutil.copy2(src, snap)
    tmp = src.with_name(f".live_edit_{src.name}")
    tmp.unlink(missing_ok=True)
    try:
        edited = edit_graph(str(src), str(tmp), operations)
    except Exception:
        tmp.unlink(missing_ok=True)
        snap.unlink(missing_ok=True)
        raise
    os.replace(tmp, src)
    reload = revert(pid, settle_seconds)
    return {
        "path": str(src),
        "process_id": pid,
        "operations": edited["operations"],
        "history_snapshot": str(snap),
        "undo_depth": len(_snapshots(src)),
        "screenshot": reload["screenshot"],
    }


def undo(path, process_id=None, settle_seconds=3.0):
    """Restore the file as it was before the last apply and reload it."""
    src = Path(path).resolve(strict=True)
    pid = _require_active(src, process_id)
    snaps = _snapshots(src)
    if not snaps:
        raise LiveError({"error": "no_history", "message": f"No live history for {src.name}"})
    _replace(src, snaps[-1])
    snaps[-1].unlink()
    reload = revert(pid, settle_seconds)
    return {
        "path": str(src),
        "process_id": pid,
        "restored": snaps[-1].name,
        "undo_depth": len(snaps) - 1,
        "screenshot": reload["screenshot"],
    }
