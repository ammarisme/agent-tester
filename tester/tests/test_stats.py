import pytest

from agent_tester.models import CaseResult
from agent_tester.stats import aggregate, histogram, percentile, scalar_stats, wilson_interval


def row(case="c", outcome="success", passed=True, latency=10.0, trial=0, tags=(), agent="a"):
    return CaseResult(
        agent_id=agent,
        agent_name=agent.upper(),
        case_id=case,
        trial=trial,
        tags=list(tags),
        outcome_class=outcome,
        passed=passed,
        latency_ms=latency,
        metrics={"latency_ms": latency},
    )


def test_percentile_interpolates():
    assert percentile([], 50) is None
    assert percentile([5.0], 99) == 5.0
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == 25.0
    assert percentile([10.0, 20.0, 30.0, 40.0], 90) == pytest.approx(37.0)


def test_scalar_stats_uses_sample_std():
    s = scalar_stats([10, 30, 50])
    assert s["mean"] == 30
    assert s["std"] == pytest.approx(20.0)
    assert s["count"] == 3
    assert scalar_stats([])["count"] == 0


def test_wilson_interval():
    assert wilson_interval(0, 0) is None
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and 0.69 < lo < 0.73
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)


def test_aggregate_rates_and_errors():
    rows = [
        row("c1", latency=10),
        row("c2", latency=30),
        row("c3", outcome="failed_assert", passed=False, latency=50),
        row("c4", outcome="timeout", passed=False, latency=90),
    ]
    s = aggregate(rows)["a"]
    assert s["agent_name"] == "A"
    assert s["n_results"] == 4
    assert s["outcome_counts"] == {"success": 2, "failed_assert": 1, "timeout": 1}
    assert s["pass_rate"] == 0.5
    assert s["error_rate"] == 0.25
    assert s["success_rate"] == 0.5
    assert s["scalars"]["latency_ms"]["mean"] == 45
    assert s["consistency"] is None


def test_unscored_runs_have_no_pass_rate():
    s = aggregate([row(passed=None), row("d", passed=None)])["a"]
    assert s["pass_rate"] is None and s["pass_rate_ci95"] is None


def test_consistency_across_trials():
    rows = [
        row("stable", trial=0),
        row("stable", trial=1),
        row("flaky", trial=0),
        row("flaky", outcome="failed_assert", passed=False, trial=1),
        row("broken", outcome="failed_assert", passed=False, trial=0),
        row("broken", outcome="failed_assert", passed=False, trial=1),
    ]
    c = aggregate(rows)["a"]["consistency"]
    assert c["pass_all_trials_rate"] == pytest.approx(1 / 3)
    assert c["pass_any_trial_rate"] == pytest.approx(2 / 3)
    assert c["flaky_case_ids"] == ["flaky"]


def test_by_tag_and_multi_agent_order():
    rows = [
        row("c1", tags=["smoke"], agent="b"),
        row("c2", tags=["smoke", "edge"], outcome="agent_error", passed=False, agent="b"),
        row("c1", agent="a"),
    ]
    summary = aggregate(rows)
    assert list(summary) == ["b", "a"]
    tags = summary["b"]["by_tag"]
    assert tags["smoke"]["n"] == 2 and tags["smoke"]["pass_rate"] == 0.5
    assert tags["edge"]["error_rate"] == 1.0


def test_histogram_clips_at_p99():
    h = histogram([float(v) for v in range(1, 101)] + [10_000.0], bins=10)
    assert sum(h["counts"]) + h["overflow"] == 101
    assert h["overflow"] >= 1
    assert len(h["edges"]) == 11
    assert histogram([]) is None
    assert histogram([5.0, 5.0]) == {"edges": [5.0, 6.0], "counts": [2], "overflow": 0}


def test_consistency_mixes_scored_and_unscored_cases():
    rows = [
        row("scored", trial=0),
        row("scored", trial=1),
        row("unscored", passed=None, trial=0),
        row("unscored", passed=None, trial=1),
    ]
    c = aggregate(rows)["a"]["consistency"]
    assert c["pass_all_trials_rate"] == 1.0 and c["flaky_cases"] == 0
