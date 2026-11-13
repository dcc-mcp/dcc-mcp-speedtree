"""Rank explicitly supplied four-view candidates by silhouette overlap.

This is an auditable comparison of existing images, not automatic tree fitting.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from .reference_match import VIEWS, compare_reference_views

_SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_CANDIDATES = 32


def _publish_no_replace(stage, output):
    """Publish a staged directory atomically without replacing an existing path."""
    if os.name == "nt":
        # Windows rename fails when the destination exists, including directories.
        os.rename(stage, output)
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            rename = libc.renameat2
        except AttributeError as exc:
            raise OSError("Atomic no-replace directory rename is unavailable") from exc
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        # AT_FDCWD and RENAME_NOREPLACE prevent an output created by another
        # process during a long comparison from being silently overwritten.
        if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1):
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise FileExistsError(error, os.strerror(error), str(output))
            raise OSError(error, os.strerror(error), str(output))
        return
    raise OSError("Atomic no-replace publication is supported on Windows and Linux only")


def rank_reference_candidates(references, candidate_sets, output_dir, canvas_size=512):
    """Rank candidate four-view masks by mean IoU, with auditable overlays.

    Each candidate value has the same per-view schema as
    ``compare_reference_views``. All candidate output is staged until every
    comparison succeeds. Equal scores are ordered by case-insensitive key.
    Results report image similarity only, never a visual/production approval.
    """
    if not isinstance(candidate_sets, dict) or not 1 <= len(candidate_sets) <= MAX_CANDIDATES:
        raise ValueError("candidate_sets must contain 1..32 named candidates")
    keys = list(candidate_sets)
    folded = set()
    for key in keys:
        if not isinstance(key, str) or not _SAFE_KEY.fullmatch(key):
            raise ValueError(
                "Candidate key must contain only letters, numbers, hyphen or underscore"
            )
        if key.upper() in _WINDOWS_RESERVED or key.casefold() in folded:
            raise ValueError("Candidate keys must be distinct and must not use reserved names")
        folded.add(key.casefold())
    requested = Path(output_dir).expanduser()
    if requested.name in {"", ".", ".."}:
        raise ValueError("Output must be a named new directory")
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    if output.exists() or output.is_symlink() or not parent.is_dir():
        raise ValueError("Output must be a new directory whose parent exists")
    with tempfile.TemporaryDirectory(prefix=".speedtree-ranking-", dir=output.parent) as temp:
        stage = Path(temp) / "ranking"
        stage.mkdir()
        comparisons = stage / "comparisons"
        comparisons.mkdir()
        results = []
        reference_hashes = None
        for key in sorted(keys, key=lambda name: (name.casefold(), name)):
            result = compare_reference_views(
                references, candidate_sets[key], comparisons / key, canvas_size=canvas_size
            )
            hashes = {view: result["views"][view]["reference"]["sha256"] for view in VIEWS}
            if reference_hashes is not None and hashes != reference_hashes:
                raise ValueError("Reference files changed between candidate comparisons")
            reference_hashes = hashes
            results.append(
                {
                    "candidate": key,
                    "mean_iou": result["mean_iou"],
                    "view_iou": {view: result["views"][view]["iou"] for view in VIEWS},
                    "comparison_manifest": f"comparisons/{key}/comparison.json",
                    "overlays": {view: f"comparisons/{key}/{view}_overlay.png" for view in VIEWS},
                }
            )
        results.sort(
            key=lambda item: (-item["mean_iou"], item["candidate"].casefold(), item["candidate"])
        )
        for index, result in enumerate(results, 1):
            result["rank"] = index
        report = {
            "schema": "speedtree.reference-candidate-ranking.v1",
            "status": "diagnostic_only",
            "canvas_size": canvas_size,
            "ranking_basis": "mean_of_four_independently_normalized_silhouette_ious",
            "tie_break": "case_insensitive_candidate_key",
            "reference_sha256_by_view": reference_hashes,
            "candidates": results,
            "limitations": [
                "View orientation, segmentation, crop and camera correspondence are supplied by the caller.",
                "Independent per-view normalization removes absolute size and position.",
                "Silhouette IoU does not evaluate branch topology, texture, leaf cards or production suitability.",
                "No tree generation, automatic parameter fitting or artistic acceptance was performed.",
            ],
        }
        (stage / "ranking.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if output.exists() or output.is_symlink():
            raise ValueError("Output was created while the comparison was running")
        _publish_no_replace(stage, output)
    return {
        "status": report["status"],
        "manifest_path": str(output / "ranking.json"),
        "candidates": results,
    }
