"""Aggregate case results into per-agent distributions."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from agent_tester.models import ERROR_CLASSES, OUTCOME_CLASSES, CaseResult

Z_95 = 1.959963984540054


def percentile(sorted_vals: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (same as numpy's default)."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def scalar_stats(values: Iterable[float]) -> dict[str, float | int | None]:
    vals = sorted(float(v) for v in values)
    if not vals:
        return {k: None for k in ("mean", "std", "min", "max", "p50", "p90", "p95", "p99")} | {
            "count": 0
        }
    return {
        "count": len(vals),
        "mean": statistics.fmean(vals),
        "std": statistics.stdev(vals) if len(vals) > 1 else 0.0,
        "min": vals[0],
        "max": vals[-1],
        "p50": percentile(vals, 50),
        "p90": percentile(vals, 90),
        "p95": percentile(vals, 95),
        "p99": percentile(vals, 99),
    }


def histogram(values: Iterable[float], bins: int = 24) -> dict[str, Any] | None:
    """Equal-width bins from min to p99; slower values land in ``overflow``.

    Clipping at p99 keeps one pathological request from flattening the chart.
    """
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    lo = vals[0]
    hi = percentile(vals, 99) or lo
    if hi <= lo:
        return {"edges": [lo, lo + 1.0], "counts": [len(vals)], "overflow": 0}
    width = (hi - lo) / bins
    counts = [0] * bins
    overflow = 0
    for v in vals:
        if v > hi:
            overflow += 1
        else:
            counts[min(int((v - lo) / width), bins - 1)] += 1
    return {
        "edges": [lo + i * width for i in range(bins + 1)],
        "counts": counts,
        "overflow": overflow,
    }


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval: honest bounds for a pass rate, even at small n."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    # Rounding keeps the bounds exactly 0/1 at the extremes despite float error.
    return max(0.0, round(centre - half, 12)), min(1.0, round(centre + half, 12))


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _is_pass(r: CaseResult) -> bool:
    # A scored result passes when its checks held; an unscored one when it got
    # a clean response. Decided per result, so mixed datasets are counted fairly.
    return bool(r.passed) if r.passed is not None else r.outcome_class == "success"


def _agent_summary(rows: list[CaseResult]) -> dict[str, Any]:
    n = len(rows)
    counts = Counter(r.outcome_class for r in rows)
    ordered_counts = {k: counts[k] for k in OUTCOME_CLASSES if counts[k]}
    ordered_counts.update({k: v for k, v in counts.items() if k not in OUTCOME_CLASSES})

    scored_rows = [r for r in rows if r.passed is not None]
    n_pass = sum(1 for r in scored_rows if r.passed)
    ci = wilson_interval(n_pass, len(scored_rows))

    metric_keys = sorted({k for r in rows for k in r.metrics})
    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    scalars = {"latency_ms": scalar_stats(latencies)}
    for key in metric_keys:
        if key != "latency_ms":
            scalars[key] = scalar_stats(r.metrics[key] for r in rows if key in r.metrics)

    n_errors = sum(v for k, v in counts.items() if k in ERROR_CLASSES)
    trials = max((r.trial for r in rows), default=0) + 1
    summary: dict[str, Any] = {
        "agent_id": rows[0].agent_id,
        "agent_name": rows[0].agent_name,
        "n_results": n,
        "n_cases": len({r.case_id for r in rows}),
        "trials": trials,
        "outcome_counts": ordered_counts,
        "outcome_rates": {k: v / n for k, v in ordered_counts.items()},
        "n_scored": len(scored_rows),
        "pass_rate": _rate(n_pass, len(scored_rows)),
        "pass_rate_ci95": list(ci) if ci else None,
        "success_rate": _rate(counts["success"], n),
        "error_rate": _rate(n_errors, n),
        "scalars": scalars,
        "latency_histogram": histogram(latencies),
        "consistency": _consistency(rows, scored=bool(scored_rows)) if trials > 1 else None,
        "by_tag": _by_tag(rows),
    }
    return summary


def _consistency(rows: list[CaseResult], *, scored: bool) -> dict[str, Any]:
    """pass^k (all trials pass) vs pass@k (any trial passes) across cases."""
    by_case: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_case[r.case_id].append(_is_pass(r))
    n = len(by_case)
    all_pass = sum(1 for v in by_case.values() if all(v))
    any_pass = sum(1 for v in by_case.values() if any(v))
    flaky = sorted(cid for cid, v in by_case.items() if any(v) and not all(v))
    return {
        "basis": "passed" if scored else "success",
        "pass_all_trials_rate": all_pass / n,
        "pass_any_trial_rate": any_pass / n,
        "flaky_cases": len(flaky),
        "flaky_case_ids": flaky[:50],
    }


def _by_tag(rows: list[CaseResult]) -> dict[str, Any]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for r in rows:
        for tag in r.tags:
            groups[tag].append(r)
    out = {}
    for tag in sorted(groups):
        g = groups[tag]
        scored = [r for r in g if r.passed is not None]
        lat = sorted(r.latency_ms for r in g if r.latency_ms is not None)
        out[tag] = {
            "n": len(g),
            "pass_rate": _rate(sum(1 for r in scored if r.passed), len(scored)),
            "error_rate": _rate(sum(1 for r in g if r.outcome_class in ERROR_CLASSES), len(g)),
            "latency_p50": percentile(lat, 50),
        }
    return out


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    """Per-agent summaries keyed by agent id, in first-seen order."""
    by_agent: dict[str, list[CaseResult]] = {}
    for r in results:
        by_agent.setdefault(r.agent_id, []).append(r)
    return {aid: _agent_summary(rows) for aid, rows in by_agent.items()}
