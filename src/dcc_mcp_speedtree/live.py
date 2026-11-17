"""Bound Modeler observation and limited project-owned physical commands.

The adapter uses the project's dcc-cua / DCC-MCP ui-control route only. Core's
public PixelsMcpHostClient owns the integrity-pinned runtime, exact PID/HWND,
real Host-authorized task and its connection. No raw PowerShell, UI Automation,
posted-key or PrintWindow bridge is shipped. Every entry requires the concrete
server-owned session; tool JSON and environment values never grant authority.

The implemented pixels-only session exposes an unverified document name from
the window title, not a typed full-document identity or save postcondition.
Consequently save, apply and undo refuse with active_document_binding_unverified
BEFORE Save input, file/history changes, reload or output creation. There is no
adapter-defined positive proof format: dictionary paths, capability booleans,
timestamps and hashes cannot unlock these entries. This is an adapter capability
gap, not a statement that Core or another provider lacks semantic APIs.

Status and fresh capture remain available. Revert can deliver its explicitly
authorized physical command; delivery is distinct from its unverified effect.
Partial input and unknown completion never establish that nothing was sent.
The retained transaction/recovery engine below the document gate is unreachable
on the implemented route and is not completed live co-design. Controlled tests
of these boundaries do not establish native Modeler acceptance.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from .node_tools import edit_graph

HISTORY_DIR = "_live_history"
SHOT_DIR = Path(tempfile.gettempdir()) / "speedtree-live"

# Only the trusted in-process execution route may supply this parameter. Core's
# HostExecutionBridge already strips ``trusted_adapter_scope`` /
# ``trusted_ui_control_runtime``; TrustedLiveExecutionBridge strips EVERY
# ``trusted_*`` key and then injects the server-owned bounded session here.
TRUSTED_SESSION_PARAM = "trusted_speedtree_live_session"

# Window-title separators the Modeler uses before its application suffix.
# Parsing is best-effort and always reported as unverified: pixels_only exposes
# no accessibility tree and no document path.
_TITLE_SEPARATORS = (" - ", " – ", " — ")

# Post-state statements for a reload that was DELIVERED but whose application
# effect the runtime reports as unverifiable. These are kept as data, never
# upgraded to "confirmed" and never turned into a failure by themselves.
_APPLY_UNVERIFIED_NOTE = (
    "The edit is committed on disk and the File > Revert to saved command was "
    "delivered, but the runtime reports its effect as unverifiable and no "
    "same-task observation proves the Modeler reloaded it. The history snapshot "
    "is retained; verify the Modeler before trusting the view."
)
_UNDO_UNVERIFIED_NOTE = (
    "The previous file content is restored on disk and the reload command was "
    "delivered, but the runtime reports its effect as unverifiable, so the "
    "history snapshot is kept instead of being consumed. Verify the Modeler "
    "before treating the undo as complete."
)


class LiveError(RuntimeError):
    def __init__(self, payload):
        self.payload = dict(payload)
        super().__init__(self.payload.get("message", "SpeedTree live command failed"))


def _require_session(session):
    """Accept ONLY the server's concrete bounded session, never a caller object.

    Imported lazily because ``trusted_session`` imports this module. An exact
    type check also rejects a foreign object that spoofs ``__class__`` to
    imitate the concrete class; a self-reported marker is never trusted.
    """
    from .trusted_session import BoundedLiveSession

    if type(session) is not BoundedLiveSession:
        raise LiveError(
            {
                "error": "no_authorized_ui_route",
                "message": (
                    "No trusted server-owned dcc-cua/ui-control session is available "
                    "to this live skill entry; live Modeler operations are disabled "
                    "(fail-closed)."
                ),
            }
        )
    return session


def _delivery_confirmed(result):
    """Whether the runtime confirmed the physical action was DELIVERED.

    A structured ``success: false`` is a failure even though Core raises
    nothing, so delivery is checked as data, never inferred from the absence of
    an exception. This is about delivery only: the application EFFECT stays
    unverified either way.
    """
    from .trusted_session import delivery_confirmed

    return delivery_confirmed(result)


def _delivery_failure(phase, result):
    """Truthful payload for an action that was never confirmed delivered.

    The ``dispatch`` classification is carried through so a caller can tell a
    positively known non-dispatch from a dispatched-but-unvalidated one.
    """
    payload = {
        "error": f"{phase}_not_confirmed",
        "phase": phase,
        "dispatch": result.get("dispatch"),
        "success": result.get("success"),
        "delivery_completed": result.get("delivery_completed"),
        "post_dispatch_validated": result.get("post_dispatch_validated"),
        "effect": result.get("effect"),
        "gui_state": "unknown",
        "message": (
            f"The Modeler {phase} command was not confirmed delivered "
            f"(success={result.get('success')!r}, "
            f"delivery_completed={result.get('delivery_completed')!r}). "
            "Refusing to treat it as done."
        ),
    }
    return LiveError(payload)


def _dispatch_known_failed(exc):
    """Whether a failure is positively known never to have reached the window.

    Only the ``not_dispatched`` classification qualifies, and that
    classification itself requires affirmative proof: either an adapter-owned
    boundary that refused before ``execute`` was entered, or the runtime's own
    action-stage evidence (pre-dispatch phase, no action attempted, or no input
    sent, with completion known and the effect not unknown). A false
    ``delivery_completed`` is NOT such proof -- the runtime keeps it false for a
    partial insertion as well -- so it never licenses a compensating restore.
    """
    payload = getattr(exc, "payload", None)
    if not isinstance(payload, dict):
        return False
    return payload.get("dispatch") == "not_dispatched"


def _file_state(path):
    """Same-task observation of the file on disk, content and time."""
    st = path.stat()
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }


def save_disk_observation(before, after):
    """A filesystem diagnostic only: it carries NO save authority.

    A changed mtime or a changed content hash proves that the disk changed. It
    does not prove that the BOUND Modeler wrote its current GUI edits into the
    requested document: another process, the user, a background autosave or a
    plain metadata touch produces the same observation. So this never licenses
    the dependent destructive phase; it is reported as a diagnostic next to the
    unknown save state.
    """
    return {
        "content_changed": before["sha256"] != after["sha256"],
        "metadata_only_change": before["sha256"] == after["sha256"] and before != after,
        "before": dict(before),
        "after": dict(after),
        "authority": "none",
        "reason": (
            "A file observation cannot bind a disk change to the bound Modeler's "
            "save of its GUI edits into this document; another writer or a metadata "
            "touch looks identical."
        ),
    }


# The implemented pixels-only route reports the save EFFECT as unverifiable and
# exposes no source-bound save confirmation -- no application-semantics
# acknowledgement, no process/document binding and no verifiable provenance.
# Until a project route provides one, the prerequisite is unknown on every call.
SAVE_CONFIRMATION_UNAVAILABLE = {
    "established": False,
    "method": "none",
    "authority": "none",
    "reason": (
        "No project-route confirmation with explicit application semantics, correct "
        "process/document binding and verifiable provenance is available on the "
        "implemented pixels-only route, so the save prerequisite stays unknown."
    ),
}


def _save_confirmation(saved, observation):
    """The source-bound save confirmation this route can offer, if any.

    A confirmation must come from the project route with explicit application
    semantics, the correct process/document binding and verifiable provenance for
    THIS document. The implemented pixels-only client reports the save effect as
    unverifiable and exposes nothing of that kind, and a file observation cannot
    be bound to the bound Modeler's save, so there is none here. Returning
    ``None`` keeps the refusal honest and leaves exactly one extension point for
    a route that does provide it; it is not a flag, a grant, a caller-supplied
    value or a synthesized acknowledgement.
    """
    return None


def _save_prerequisite_unverified(saved, observation, confirmation=None):
    """Refuse the dependent destructive phase BEFORE any disk or history write."""
    return LiveError(
        {
            "error": "save_prerequisite_unverified",
            "phase": "save_prerequisite",
            "dispatch": saved.get("dispatch"),
            "disk_mutation": False,
            "history_mutation": False,
            "gui_state": "unknown",
            "save_delivery": {
                "delivery_completed": saved.get("delivery_completed"),
                "post_dispatch_validated": saved.get("post_dispatch_validated"),
                "effect": saved.get("effect"),
            },
            "save_postcondition": dict(confirmation or SAVE_CONFIRMATION_UNAVAILABLE),
            "save_disk_observation": observation,
            "adapter_capability": {
                "save_effect_verifier": "NOT_AVAILABLE",
                "route": "owned_mcp_pixels / pixels_only",
                "scope": (
                    "This adapter's implemented route has no source-bound save "
                    "confirmation: the pixels-only client reports the application effect "
                    "as unverifiable and exposes no application-semantics "
                    "acknowledgement with process/document binding, so the dependent "
                    "phase is refused instead of being inferred from a timestamp or a "
                    "content-hash delta. This is an adapter capability gap, not a "
                    "statement about the public DCC-CUA protocol or another host."
                ),
            },
            "message": (
                "The save command was delivered, but nothing on this route confirms that "
                "the bound Modeler saved its current GUI edits into this document: the "
                "effect is reported as unverifiable and a file timestamp or content "
                "change cannot be bound to that specific save. The dependent file edit "
                "and the history write are refused before either starts. This is a "
                "reported capability gap, not a completed live edit; no automatic retry "
                "is performed."
            ),
        }
    )


def _unknown_reload_error(exc, history_snapshot, staged_retained=None):
    """Preserve the mutation and the backup for a reload that may have happened.

    A dispatched-but-unvalidated, partial or unclassified dispatch is NOT a
    known failure: the Modeler may already have executed the reload. Rolling the
    file back would undo an edit the user may be looking at, and deleting the
    only snapshot would discard recoverability, so both are preserved and the
    uncertainty is reported instead of being resolved by assumption.
    """
    payload = getattr(exc, "payload", None) if isinstance(exc, LiveError) else None
    structured = payload if isinstance(payload, dict) else {}
    error = {
        "error": "reload_effect_unknown",
        "phase": "reload",
        "dispatch": structured.get("dispatch") or "unknown_dispatch",
        "file_restored": False,
        "history_retained": True,
        "history_snapshot": str(history_snapshot),
        "gui_state": "unknown",
        "original_error": _error_detail(exc),
        "recovery": {"history_snapshot": str(history_snapshot), "restore_with": "live_undo"},
        "message": (
            "The edit is on disk and the reload was dispatched, but the result could "
            "not be validated, so the Modeler may already have executed it. The file "
            "and the history snapshot are both preserved: inspect the Modeler and use "
            "live_undo to restore if the reload did not take effect."
        ),
    }
    if "native_error" in structured:
        error["native_error"] = structured["native_error"]
    if staged_retained:
        error["staged_retained"] = list(staged_retained)
    return LiveError(error)


def _reload_view(reload):
    """Delivery/effect view of one reload, without claiming the effect."""
    return {
        "dispatch": reload.get("dispatch"),
        "delivered": _delivery_confirmed(reload),
        "effect": reload.get("effect", "unverifiable"),
        "verification_required": reload.get("verification_required", True),
        "verification": reload.get("verification"),
    }


def effect_message(result, *, action, known):
    """Caller-facing summary that never asserts an unverified effect.

    Disk state and command delivery are known; the application effect is not.
    The message states exactly that, names the retained backup when there is
    one, and never claims the Modeler applied the change.
    """
    verification = result.get("verification") if isinstance(result, Mapping) else None
    status = verification.get("status") if isinstance(verification, Mapping) else None
    parts = [known]
    if status == "confirmed":
        parts.append(f"The Modeler {action} is confirmed.")
    else:
        parts.append(
            f"The Modeler {action} effect is UNVERIFIED: the command was delivered, but "
            "no same-task observation proves the Modeler applied it. Confirm the open "
            "document before relying on this result."
        )
        if isinstance(verification, Mapping) and verification.get("history_retained"):
            parts.append("The history snapshot is retained, so live_undo can still restore it.")
    return " ".join(parts)


def _pending_verification(history_snapshot, history_retained, note):
    """A truthful post-state statement for a delivered but unverified reload."""
    return {
        "status": "unknown",
        "history_retained": history_retained,
        "history_snapshot": str(history_snapshot) if history_retained else None,
        "established_by": None,
        "message": note,
    }


def _history(src: Path) -> Path:
    return src.parent / HISTORY_DIR / src.stem


def _snapshots(src: Path):
    folder = _history(src)
    return sorted(folder.glob(f"*{src.suffix}")) if folder.is_dir() else []


def _owned_stage(src: Path, kind: str):
    """Reserve a private staging directory and a stage path that does not exist.

    ``mkdtemp`` creates a unique directory beside ``src``, so this call can
    never overwrite or delete recovery material left by an earlier run. The
    stage path itself must NOT exist: ``graph.save`` opens its output with
    ``"xb"``. Staying beside ``src`` keeps the final ``os.replace`` atomic on
    the same filesystem.
    """
    folder = Path(tempfile.mkdtemp(prefix=f".live_{kind}_{src.stem}_", dir=src.parent))
    return folder, folder / f"stage{src.suffix}"


def _replace(src: Path, content_from: Path):
    """Atomically restore ``src`` from ``content_from`` using only our own stage."""
    folder, staged = _owned_stage(src, "restore")
    try:
        shutil.copy2(content_from, staged)
        os.replace(staged, src)
    except Exception:
        _cleanup_staged(staged, folder)
        raise
    _cleanup_staged(staged, folder)


def _cleanup_staged(*paths):
    """Best-effort removal of paths owned by this call; report actual residue.

    Returns ``(retained, first_error)`` where ``retained`` lists the real paths
    still present after the attempt. Callers MUST derive each named recovery
    field from its own path, never from ``any()`` across unrelated resources.
    Directories are removed with ``rmdir`` only (empty-only), so an unknown file
    is retained rather than recursively deleted. Cleanup errors never mask the
    caller's original failure.
    """
    error = None
    retained = []
    for path in paths:
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            error = error or exc
        if path.exists():
            retained.append(str(path))
    return retained, error


def _error_detail(exc):
    """Flatten an exception into one JSON-safe, human-readable string."""
    if isinstance(exc, LiveError):
        payload = exc.payload
        return f"{payload.get('error', 'live_failed')}: {payload.get('message', str(exc))}"
    return f"{type(exc).__name__}: {exc}"


def _transaction_error(
    exc,
    *,
    phase,
    file_restored,
    history_snapshot,
    history_retained,
    compensation_error=None,
    retry=None,
    staged_retained=None,
):
    """Build a truthful structured failure for a file transaction.

    The original failure is preserved in ``original_error`` and chained as the
    cause; ``error`` keeps the original ``LiveError`` code when there is one.
    Recovery is reported exactly as it happened: ``history_*`` describes only
    the history snapshot, while ``staged_retained`` lists owned stage residue by
    real path and is never counted as undo history. ``gui_state`` is always
    ``unknown``: restoring the disk file is a limited local data guarantee, not
    proof of what the Modeler window currently shows.
    """
    code = exc.payload.get("error") if isinstance(exc, LiveError) else None
    state = "complete" if file_restored else "incomplete"
    payload = {
        "error": code or f"{phase}_failed",
        "message": (
            f"SpeedTree live {phase} failed ({_error_detail(exc)}). "
            f"Local file recovery is {state}; the Modeler GUI state is unknown. "
            "Inspect the open document before any further write."
        ),
        "phase": phase,
        "dispatch": (exc.payload.get("dispatch") if isinstance(exc, LiveError) else None),
        "original_error": _error_detail(exc),
        "file_restored": file_restored,
        "history_retained": history_retained,
        "history_snapshot": str(history_snapshot) if history_retained else None,
        "gui_state": "unknown",
    }
    if isinstance(exc, LiveError) and "native_error" in exc.payload:
        payload["native_error"] = exc.payload["native_error"]
    if isinstance(exc, LiveError) and "no_dispatch_proof" in exc.payload:
        payload["no_dispatch_proof"] = exc.payload["no_dispatch_proof"]
    if compensation_error is not None:
        payload["compensation_error"] = _error_detail(compensation_error)
    if staged_retained:
        payload["staged_retained"] = list(staged_retained)
    if retry:
        payload["retry"] = retry
    return LiveError(payload)


def _document_from_title(title):
    """Best-effort document name from the bound window title; never verified."""
    if not isinstance(title, str):
        return None
    head = title
    for separator in _TITLE_SEPARATORS:
        head = head.split(separator)[0]
    head = head.strip().strip("*").strip()
    return head or None


def _require_active(bounded, src: Path):
    """Confirm the bound window is showing ``src`` before any write.

    The caller must already have validated an explicit ``process_id`` through
    ``bounded.require_target``; this check only compares the bound window's
    document, so a caller PID can never redirect the write to another window.
    The document name comes from the bound window title only. Pixels-only
    exposes no accessibility tree and no document path, so it is reported as
    unverified and an unparseable title is refused instead of assumed.
    """
    state = bounded.status()
    instances = state.get("instances") or []
    if not instances:
        raise LiveError(
            {"error": "not_running", "message": "No bound SpeedTree Modeler window found"}
        )
    target = instances[0]
    active = _document_from_title(target.get("window_title"))
    if not active:
        raise LiveError(
            {
                "error": "active_document_unverifiable",
                "window_title": target.get("window_title"),
                "message": (
                    "The bound window title does not name an open document; pixels_only "
                    "exposes no document path. Confirm the Modeler is showing "
                    f"'{src.name}' before writing."
                ),
            }
        )
    if active.lower() != src.name.lower():
        raise LiveError(
            {
                "error": "not_active",
                "active_document": active,
                "active_document_verified": False,
                "message": f"Modeler shows '{active}', not '{src.name}'; use live_open first",
            }
        )
    window = state.get("window_state") or {}
    if window.get("minimized") or not window.get("visible"):
        raise LiveError(
            {
                "error": "window_not_visible",
                "message": "The bound Modeler window is minimized or hidden; restore it first.",
            }
        )
    return target["process_id"]


# The implemented pixels-only route reports the active document ONLY as a
# best-effort name parsed from the bound window title. Its own status contract
# (trusted_session.BoundedLiveSession.status) declares both
# ``active_document_path: False`` and ``active_document_verified: False``. There
# is no formal supported interface here that returns the FULL canonical path of
# the document open in the exact bound window: no process/document-bound
# acknowledgement, no source-bound observation, and no typed DCC document
# identity. A full caller path therefore cannot be bound to the scoped target.
# This is an ADAPTER capability gap on the pixels-only route, not a claim that
# the public DCC-CUA protocol or another host lacks document/save semantics.
ACTIVE_DOCUMENT_BINDING_UNAVAILABLE = {
    "established": False,
    "method": "none",
    "authority": "none",
    "required": "full canonical active-document path bound to the exact scoped target",
    "route": "owned_mcp_pixels / pixels_only",
    "capabilities": {
        "active_document_path": False,
        "active_document_from_title": True,
        "active_document_verified": False,
    },
    "reason": (
        "The scoped-target status exposes only a best-effort document name from "
        "the window title and declares no verified full active-document path. A "
        "basename, caller flag, transport fixture, file timestamp or content hash "
        "cannot bind the caller's full path to the document open in this exact "
        "window."
    ),
}


def _require_bound_document(bounded, src=None):
    """Refuse document-dependent actions unsupported by the current adapter.

    The concrete pixels session has no typed full-document observation. Its
    status is diagnostic only; dictionaries, path strings and capability flags
    cannot create a new proof contract. A real provider integration requires a
    separately reviewed implementation using its existing typed contract.
    ``require_target`` must validate the PID before this read.
    """
    raise _active_document_binding_unverified(bounded.status(), src)


def _active_document_binding_unverified(state, src=None):
    """Report unsupported document identity before Save or dependent effects."""
    capabilities = state.get("capabilities") or {}
    return LiveError(
        {
            "error": "active_document_binding_unverified",
            "phase": "active_document_binding",
            "disk_mutation": False,
            "history_mutation": False,
            "save_dispatch": False,
            "reload_dispatch": False,
            "gui_state": "unknown",
            "requested_path": str(src) if src is not None else None,
            "scope": state.get("scope"),
            "document_binding": dict(ACTIVE_DOCUMENT_BINDING_UNAVAILABLE),
            "observed_capabilities": {
                "active_document_path": capabilities.get("active_document_path"),
                "active_document_from_title": capabilities.get("active_document_from_title"),
                "active_document_verified": capabilities.get("active_document_verified"),
            },
            "adapter_capability": {
                "active_document_path_verifier": "NOT_AVAILABLE",
                "route": "owned_mcp_pixels / pixels_only",
                "required_capability": (
                    "A project-route typed observation that returns the FULL canonical "
                    "active-document path with explicit process/document binding, "
                    "verifiable provenance and a fresh same-task observation of the "
                    "exact bound window; the caller path must resolve to it. The "
                    "pixels-only status contract exposes no such field."
                ),
                "scope": (
                    "This adapter's implemented route has no source-bound full "
                    "active-document path; the pixels-only client declares "
                    "active_document_path=false and active_document_verified=false. "
                    "This is an adapter capability gap, not a statement about the "
                    "public DCC-CUA protocol or another host."
                ),
            },
            "message": (
                "The bound window can only report a document NAME from its title; "
                "nothing on this route provides the full canonical path of the "
                "document open in the exact bound window. A same-name document "
                "elsewhere on disk cannot be ruled out, so this adapter refuses "
                "save, apply and undo before Save input, history access, file replacement, reload or "
                "creating any output. This is a reported capability gap, not a "
                "completed live feature; no flag, timestamp or hash is accepted "
                "as a substitute and no automatic retry is performed."
            ),
        }
    )


def status(process_id=None, *, session=None):
    """Read the exact bound window state through the server-owned typed client.

    An explicit ``process_id`` is validated against the bound window BEFORE any
    native read; ``None`` means "use the exact bound window".
    """
    bounded = _require_session(session)
    bounded.require_target(process_id)
    return bounded.status()


def screenshot(process_id=None, path=None, scale=0.6, *, session=None):
    """Capture a fresh native PNG through the server-owned typed client.

    ``scale`` is retained for input compatibility but is NOT applied: the
    pixels-only typed client returns native-resolution pixels and no silent
    resampling is performed.
    """
    bounded = _require_session(session)  # refuse BEFORE any path or directory work
    bounded.require_target(process_id)  # refuse BEFORE native capture and output paths
    auto_path = not path
    if auto_path:
        path = SHOT_DIR / f"modeler_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
    result = bounded.capture()
    # Create output directories only AFTER the typed capture proof succeeded.
    if auto_path:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(result["image_bytes"])
    return {
        "path": str(path),
        "provider": result["provider"],
        "runtime_version": result["runtime_version"],
        "observation_id": result["observation_id"],
        "target": result["target"],
        "scale_requested": scale,
        "scale_applied": False,
    }


def open_recent(path, process_id=None, *, session=None):
    """Refuse precisely: not implementable on the exact-window pixels-only route.

    Opening a file needs a native file dialog or a typed DCC menu action, and
    neither is public API here: the owned task is bound to ONE exact PID/HWND
    (``UiControlRuntimeOptions`` plus ``PixelsMcpHostClient._check_target``
    rejects any other window) and ``pixels_only`` exposes no accessibility tree
    to read or target a menu. See ``BoundedLiveSession.unsupported_open_recent``.
    """
    bounded = _require_session(session)
    bounded.require_target(process_id)
    raise bounded.unsupported_open_recent(Path(path).resolve(strict=True))


def save(process_id=None, *, session=None):
    """Refuse Save before input while reliable document identity is unavailable."""
    bounded = _require_session(session)
    bounded.require_target(process_id)  # before any native read or output work
    _require_bound_document(bounded)


def revert(process_id=None, settle_seconds=3.0, shot=True, *, session=None):
    """Reload the saved document (File > Revert to saved).

    An unconfirmed delivery is refused. A confirmed delivery still reports
    ``verification.status = "unknown"``: the command reached the window, but the
    runtime reports its effect as unverifiable and no same-task observation
    proves the Modeler reloaded the file.
    """
    bounded = _require_session(session)
    bounded.require_target(process_id)  # before any native read or output work
    result = bounded.menu("revert")
    if not _delivery_confirmed(result):
        raise _delivery_failure("revert", result)
    if shot:
        time.sleep(settle_seconds)
        result["screenshot"] = screenshot(result["process_id"], session=bounded)["path"]
    return result


def _reload_and_observe(bounded, settle_seconds):
    """Reload the document (the commit boundary), then observe it separately.

    A reload that was never confirmed DELIVERED is a hard failure and is
    raised, so callers compensate. A reload that was delivered is returned even
    though its effect is unverifiable: taking a fresh observation afterwards is
    observation, not effect verification, and must not be mistaken for proof
    that the Modeler reloaded the file.

    A screenshot failure is an observation failure, NOT an uncommitted
    transaction: it is returned as ``(None, detail)`` instead of being raised,
    so callers never redo or wrongly roll back a committed mutation.
    """
    reload = bounded.menu("revert")
    if not _delivery_confirmed(reload):
        raise _delivery_failure("reload", reload)
    try:
        time.sleep(settle_seconds)
        return reload, screenshot(bounded.bound_process_id, session=bounded)["path"], None
    except Exception as exc:
        return reload, None, _error_detail(exc)


def apply(path, operations, process_id=None, settle_seconds=3.0, *, session=None):
    """Refuse before Save, file/history mutation or reload on this adapter.

    Full document identity and a source-bound save postcondition are unavailable
    on its pixels-only route. The retained transaction below the guard is not a
    completed live feature. No basename, dictionary, flag, timestamp or hash may
    substitute for the missing provider contract.
    """
    bounded = _require_session(session)
    bounded.require_target(process_id)  # before any native read, path, history or output work
    src = Path(path).resolve(strict=True)
    _require_bound_document(bounded, src)
    pid = _require_active(bounded, src)
    # Diagnostic only -- see the docstring. It is not the prerequisite.
    before = _file_state(src)
    saved = bounded.menu("save")  # would keep the user's own GUI edits in the file we edit
    if not _delivery_confirmed(saved):
        # Nothing has been written yet: refuse before any history or staging.
        raise _delivery_failure("save", saved)
    observation = save_disk_observation(before, _file_state(src))
    confirmation = _save_confirmation(saved, observation)
    if not confirmation or not confirmation["established"]:
        # No route on this adapter can confirm the save, so the destructive
        # dependent phase is refused with the disk and the history untouched.
        raise _save_prerequisite_unverified(saved, observation, confirmation)
    history_dir = _history(src)
    history_dir.mkdir(parents=True, exist_ok=True)
    snap = history_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}{src.suffix}"
    shutil.copy2(src, snap)
    stage_dir, tmp = _owned_stage(src, "edit")
    try:
        edited = edit_graph(str(src), str(tmp), operations)
    except Exception:
        # No mutation happened: propagate the original graph error verbatim.
        _cleanup_staged(tmp, stage_dir, snap)
        raise
    try:
        os.replace(tmp, src)
    except Exception as exc:
        # The rename is atomic, so src is still the user's file. Report the
        # snapshot and the owned stage residue by their real, separate paths.
        retained, cleanup_error = _cleanup_staged(tmp, stage_dir, snap)
        raise _transaction_error(
            exc,
            phase="replace",
            file_restored=True,
            history_snapshot=snap,
            history_retained=str(snap) in retained,
            staged_retained=[p for p in retained if p != str(snap)],
            compensation_error=cleanup_error,
            retry="Resolve the file replacement error, then retry apply.",
        ) from exc
    stage_residue, _ = _cleanup_staged(tmp, stage_dir)
    try:
        reload, observed, shot_error = _reload_and_observe(bounded, settle_seconds)
    except Exception as exc:
        # The file was replaced but the Modeler did not confirm the reload.
        # Compensate ONLY for a positively known non-dispatch: when nothing
        # reached the window the edit is still ours to undo. A dispatch that
        # happened but could not be validated, or an unclassified dispatch
        # error, may already have been executed, so rolling the file back
        # would undo an edit the user may be looking at and spending the only
        # snapshot would discard recoverability. Both are preserved instead.
        if not _dispatch_known_failed(exc):
            raise _unknown_reload_error(exc, snap, staged_retained=stage_residue) from exc
        try:
            _replace(src, snap)
        except Exception as compensation_error:
            raise _transaction_error(
                exc,
                phase="reload",
                file_restored=False,
                history_snapshot=snap,
                history_retained=True,
                staged_retained=stage_residue,
                compensation_error=compensation_error,
                retry="Restore the file from the retained snapshot before retrying.",
            ) from exc
        retained, cleanup_error = _cleanup_staged(snap)
        raise _transaction_error(
            exc,
            phase="reload",
            file_restored=True,
            history_snapshot=snap,
            history_retained=str(snap) in retained,
            staged_retained=stage_residue,
            compensation_error=cleanup_error,
            retry="Retry apply once the Modeler can reload the document.",
        ) from exc
    result = {
        "path": str(src),
        "process_id": pid,
        "operations": edited["operations"],
        "save_postcondition": dict(confirmation),
        "save_disk_observation": observation,
        "history_snapshot": str(snap),
        "undo_depth": len(_snapshots(src)),
        "screenshot": observed,
        "reload_effect": reload.get("effect"),
        "reload_verification_required": reload.get("verification_required", True),
        "reload": _reload_view(reload),
        "verification": _pending_verification(snap, True, _APPLY_UNVERIFIED_NOTE),
        "retry": (
            "Verify the Modeler is showing the edited document; the history "
            "snapshot is retained so live_undo can restore it."
        ),
    }
    if stage_residue:
        result["staged_retained"] = stage_residue
    if shot_error is not None:
        result["screenshot_error"] = shot_error
    return result


def undo(path, process_id=None, settle_seconds=3.0, *, session=None):
    """Restore the file as it was before the last apply and reload it.

    On the implemented pixels-only route this is a FAIL-CLOSED refusal: no
    supported observation binds the FULL canonical requested path to the
    document open in the exact bound window, so ``_require_bound_document``
    refuses BEFORE any history read, disk replacement, reload dispatch or
    output work. A same-basename document in another directory cannot be
    excluded by a window title, and no caller flag, transport attribute, file
    timestamp, content hash or historical snapshot is accepted as a substitute.

    The transaction code below the gate is retained for a route that does
    provide a real process/document-bound observation: the history snapshot is
    consumed ONLY after both the atomic file restore and the Modeler reload
    succeed, a failed reload keeps the snapshot so the same undo can be retried,
    and a failed restore keeps it as the only backup. It is NOT a completed
    live feature on the pixels-only route.
    """
    bounded = _require_session(session)
    bounded.require_target(process_id)  # before any native read, path, history or output work
    src = Path(path).resolve(strict=True)
    _require_bound_document(bounded, src)  # refuse before ANY mutation / reload
    pid = _require_active(bounded, src)
    snaps = _snapshots(src)
    if not snaps:
        raise LiveError({"error": "no_history", "message": f"No live history for {src.name}"})
    snap = snaps[-1]
    try:
        _replace(src, snap)
    except Exception as exc:
        raise _transaction_error(
            exc,
            phase="replace",
            file_restored=False,
            history_snapshot=snap,
            history_retained=True,
            retry="Resolve the file restore error, then retry undo.",
        ) from exc
    try:
        reload, observed, shot_error = _reload_and_observe(bounded, settle_seconds)
    except Exception as exc:
        # The disk file is already the restored (pre-apply) state, but the
        # Modeler did not reload. Keep the snapshot so undo stays retryable.
        raise _transaction_error(
            exc,
            phase="reload",
            file_restored=True,
            history_snapshot=snap,
            history_retained=True,
            retry="Retry undo to reload the already-restored file.",
        ) from exc
    # The reload was DELIVERED but its effect is unverifiable, so the only
    # backup is kept: deleting it here would discard the user's undo for a
    # reload that may never have happened.
    result = {
        "path": str(src),
        "process_id": pid,
        "restored": snap.name,
        "undo_depth": len(_snapshots(src)),
        "screenshot": observed,
        "reload_effect": reload.get("effect"),
        "reload_verification_required": reload.get("verification_required", True),
        "reload": _reload_view(reload),
        "verification": _pending_verification(snap, True, _UNDO_UNVERIFIED_NOTE),
        "retry": (
            "The file was restored on disk and the reload was delivered, but its "
            "effect is unverified; confirm the Modeler before treating the undo "
            "as complete. The snapshot is retained so the retry cannot lose it."
        ),
    }
    if shot_error is not None:
        result["screenshot_error"] = shot_error
    return result
