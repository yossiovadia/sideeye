"""Unit tests for the cost-report savings math."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sideeye.cost_report import counterfactual_cost, summarize  # noqa: E402


def _rec(gen_in, gen_out, judge_cost, score, severity="none", adapter_version=None):
    r = {
        "session_id": f"s-{gen_in}-{gen_out}-{severity}",
        "generation_input_tokens": gen_in,
        "generation_output_tokens": gen_out,
        "generation_total_tokens": gen_in + gen_out,
        "judge_cost_usd": judge_cost,
        "score": score,
        "overall_severity": severity,
    }
    if adapter_version:
        r["adapter_version"] = adapter_version
    return r


def test_counterfactual_cost_sonnet5():
    # Sonnet 5 = $2/M in, $10/M out.
    rec = _rec(1_000_000, 1_000_000, 0.0, 5)
    assert counterfactual_cost(rec, "claude-sonnet-5") == pytest.approx(12.0)


def test_counterfactual_cost_opus48():
    # Opus 4.8 = $5/M in, $25/M out.
    rec = _rec(1_000_000, 0, 0.0, 5)
    assert counterfactual_cost(rec, "claude-opus-4-8") == pytest.approx(5.0)


def test_summarize_savings_and_quality():
    recs = [
        _rec(1_000_000, 1_000_000, 0.02, 5, "none"),   # cf $12 on sonnet-5
        _rec(1_000_000, 1_000_000, 0.02, 3, "major"),  # cf $12
    ]
    s = summarize(recs, "claude-sonnet-5")
    assert s["sessions"] == 2
    assert s["counterfactual_cost"] == pytest.approx(24.0)
    assert s["judge_cost"] == pytest.approx(0.04)
    assert s["savings"] == pytest.approx(24.0 - 0.04)
    assert s["actual_generation_cost"] == 0.0
    assert s["avg_score"] == pytest.approx(4.0)
    assert s["major_issue_rate"] == pytest.approx(0.5)


def test_summarize_empty():
    assert summarize([], "claude-sonnet-5") is None


def test_blind_and_sighted_never_pool():
    """Blind (v0) and sighted (v1) verdicts measure different things — pooling
    them corrupts the aggregate. The sighted cohort is the headline; blind
    verdicts are counted as excluded, not mixed in."""
    recs = [
        _rec(1_000_000, 0, 0.02, 5, "none", adapter_version="v1-sighted"),
        _rec(1_000_000, 0, 0.02, 2, "critical", adapter_version="v0-blind"),
    ]
    s = summarize(recs, "claude-sonnet-5")
    assert s["sessions"] == 1                    # only the sighted one
    assert s["avg_score"] == 5                   # the blind 2-score is NOT pooled in
    assert s["blind_excluded"] == 1
    assert s["adapter_version"] == "v1-sighted"


def test_blind_records_implicitly_v0_when_field_absent():
    """Pre-fix records have no adapter_version field. They must be treated as
    v0-blind, and (when no sighted records exist) reported honestly as v0."""
    recs = [_rec(1_000_000, 0, 0.02, 4)]  # no adapter_version field
    s = summarize(recs, "claude-sonnet-5")
    assert s["adapter_version"] == "v0-blind"
    assert s["blind_excluded"] == 0   # nothing excluded — the cohort IS blind
