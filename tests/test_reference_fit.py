import gzip

import pytest
from dcc_mcp_core.cancellation import (
    CancelToken,
    DccMcpCancelledError,
    reset_cancel_token,
    set_cancel_token,
)

from dcc_mcp_speedtree.reference_fit import fit_reference_parameters


@pytest.fixture
def fit_fixture(tmp_path):
    source = tmp_path / "source.spm"
    source.write_bytes(
        gzip.compress(b"""<SpeedTree Version="8"><Generators>
      <Generator Type="Tree"><GUID>root</GUID><Name>root</Name><Properties/></Generator>
      <Generator Type="Branch"><GUID>trunk</GUID><Name>trunk</Name><Properties>
      <Property><Name>Length</Name><Value>5</Value></Property>
      <Property><Name>Radius</Name><Value>2</Value></Property>
      </Properties></Generator></Generators><Links><Link><GUID>root-to-trunk</GUID>
      <SourceGUID>root</SourceGUID><TargetGUID>trunk</TargetGUID></Link></Links></SpeedTree>""")
    )
    bare = tmp_path / "bare.obj"
    full = tmp_path / "full.obj"
    vertices = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 1 1\n"
    bare.write_text(vertices + "f 1 2 3\n", encoding="utf-8")
    full.write_text(vertices + "f 1 2 3\nf 1 3 4 5\n", encoding="utf-8")
    params = [{"node_id": "trunk", "name": "Length", "initial": 5, "values": [4, 5, 6]}]
    return source, full, bare, params


def _comparison(value, digest="a" * 64):
    return {
        "status": "diagnostic_only",
        "mean_iou": value,
        "views": {
            name: {
                "iou": value,
                "reference": {
                    "sha256": digest,
                    "mode": "light",
                    "threshold": 128,
                    "crop": None,
                    "foreground_bbox": [1, 1, 5, 5],
                    "crop_size": [8, 8],
                },
                "reference_transform": {"size": [8, 8], "offset": [0, 0], "scale": 1},
            }
            for name in ("front", "back", "left", "right")
        },
    }


def _run(fixture, callback, **kwargs):
    source, _, _, params = fixture
    return fit_reference_parameters(
        source, params, callback, total_max_triangles=3, card_triangles=2, **kwargs
    )


def test_selects_best_eligible_candidate_and_checks_geometry(fit_fixture):
    source, full, bare, _ = fit_fixture
    before = source.read_bytes()
    called = []

    def evaluator(trial, operations):
        value = operations[-1]["value"]
        called.append((trial, value))
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison({4: 0.8, 5: 0.4, 6: 0.3}[value]),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    result = _run(fit_fixture, evaluator)
    assert result["status"] == "candidate_selected"
    assert result["winner"]["values"] == [4]
    assert result["winner"]["geometry"]["full"]["triangles"] == 3
    assert result["winner"]["geometry"]["full_minus_bare_triangles"] == 2
    assert result["candidate_space_exhausted"] is True
    assert [x[1] for x in called] == [5, 4, 6]
    assert result["visual_acceptance"] == "pending_artist_review"
    assert source.read_bytes() == before


def test_does_not_trust_evaluator_budget_or_structure_claims(fit_fixture):
    _, full, bare, _ = fit_fixture

    def evaluator(trial, operations):
        value = operations[-1]["value"]
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison({4: 0.9, 5: 0.4, 6: 0.8}[value]),
            "provenance": {"verified": True},
            "structure": {"status": "failed" if value == 4 else "passed"},
            "triangles": 0,
        }

    result = _run(fit_fixture, evaluator)
    assert result["winner"]["values"] == [6]
    assert result["trials"][1]["status"] == "structure_failed"
    # Requested 1 card does not match the actual independently read difference of 2.
    source, _, _, params = fit_fixture
    failed = fit_reference_parameters(
        source, params, evaluator, total_max_triangles=3, card_triangles=1
    )
    assert failed["status"] == "no_eligible_candidate"
    assert any(t["status"] == "budget_failed" for t in failed["trials"])


def test_failed_evaluation_is_recorded_and_budget_limit_is_not_exhaustive(fit_fixture):
    _, full, bare, _ = fit_fixture

    def evaluator(trial, operations):
        if operations[-1]["value"] == 4:
            raise RuntimeError("export failed")
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(0.4),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    result = _run(fit_fixture, evaluator, max_evaluations=2)
    assert result["evaluation_count"] == 2
    assert result["trials"][1]["status"] == "evaluation_failed"
    assert result["stop_reason"] == "evaluation_limit"
    assert result["candidate_space_exhausted"] is False


def test_known_structure_failure_can_stop_before_expensive_export(fit_fixture):
    result = _run(fit_fixture, lambda trial, operations: {"structure": {"status": "failed"}})
    assert result["status"] == "no_eligible_candidate"
    assert all(t["status"] == "structure_failed" for t in result["trials"])


def test_reference_change_invalidates_entire_fit(fit_fixture):
    _, full, bare, _ = fit_fixture

    def evaluator(trial, operations):
        digest = "b" * 64 if operations[-1]["value"] == 4 else "a" * 64
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(0.5, digest),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    result = _run(fit_fixture, evaluator)
    assert result["status"] == "reference_changed" and result["winner"] is None


def test_source_change_or_removal_invalidates_entire_fit(fit_fixture):
    source, full, bare, _ = fit_fixture

    def evaluator(trial, operations):
        source.unlink()
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(0.5),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    result = _run(fit_fixture, evaluator)
    assert result["status"] == "source_changed" and result["winner"] is None


def test_source_initial_value_mismatch_and_missing_provenance_fail(fit_fixture):
    source, full, bare, params = fit_fixture
    bad = [dict(params[0], initial=7)]
    with pytest.raises(ValueError, match="Initial value differs"):
        fit_reference_parameters(source, bad, lambda *args: None)

    def evaluator(trial, operations):
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(0.5),
            "structure": {"status": "passed"},
        }

    result = _run(fit_fixture, evaluator)
    assert result["status"] == "no_eligible_candidate"
    assert all(t["status"] == "evaluation_failed" for t in result["trials"])


def test_core_cancellation_is_propagated(fit_fixture):
    token = CancelToken()
    token.cancel()
    marker = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError):
            _run(fit_fixture, lambda *args: pytest.fail("cancelled evaluator ran"))
    finally:
        reset_cancel_token(marker)


def test_callback_cancellation_is_not_swallowed(fit_fixture):
    def evaluator(*args):
        raise DccMcpCancelledError("cancelled")

    with pytest.raises(DccMcpCancelledError):
        _run(fit_fixture, evaluator)


def test_cancel_token_after_evaluation_stops_before_next_trial(fit_fixture):
    _, full, bare, _ = fit_fixture
    token = CancelToken()
    marker = set_cancel_token(token)
    calls = []

    def evaluator(trial, operations):
        calls.append(trial)
        token.cancel()
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(0.8),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    try:
        with pytest.raises(DccMcpCancelledError):
            _run(fit_fixture, evaluator)
    finally:
        reset_cancel_token(marker)
    assert calls == ["trial_0000"]


def test_two_parameter_search_is_deterministic_and_deduplicates(fit_fixture):
    source, full, bare, params = fit_fixture
    params = params + [{"node_id": "trunk", "name": "Radius", "initial": 2, "values": [3]}]

    def evaluator(trial, operations):
        length, radius = operations[-2]["value"], operations[-1]["value"]
        score = 0.2 + (0.1 if length == 4 else 0) + (0.3 if radius == 3 else 0)
        return {
            "full_obj_path": str(full),
            "bare_obj_path": str(bare),
            "comparison": _comparison(score),
            "provenance": {"verified": True},
            "structure": {"status": "passed"},
        }

    def run():
        return fit_reference_parameters(
            source, params, evaluator, total_max_triangles=3, card_triangles=2, max_rounds=3
        )

    first, second = run(), run()
    assert first["winner"]["values"] == [4, 3]
    assert [t["values"] for t in first["trials"]] == [t["values"] for t in second["trials"]]
    values = [tuple(t["values"]) for t in first["trials"]]
    assert len(values) == len(set(values))
