"""Human (terminal) and machine (JUnit XML) reports, plus CI quality gates."""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, TextIO

from agent_tester.models import ERROR_CLASSES, RunResults


def _color_enabled(stream: TextIO) -> bool:
    return stream.isatty() and "NO_COLOR" not in os.environ


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def ms(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1000:.2f}s" if v >= 10_000 else f"{v:.0f}ms"


class Progress:
    """Single-line progress on a TTY; silent otherwise (keeps CI logs clean)."""

    def __init__(self, stream: TextIO = sys.stderr, enabled: bool = True) -> None:
        self.stream = stream
        self.enabled = enabled and stream.isatty()
        self.ok = 0
        self.bad = 0
        self.style = Style(_color_enabled(stream))

    def update(self, outcome: str, completed: int, total: int) -> None:
        if outcome == "success":
            self.ok += 1
        else:
            self.bad += 1
        if not self.enabled:
            return
        width = 24
        filled = int(width * completed / max(total, 1))
        bar = "█" * filled + "░" * (width - filled)
        line = (
            f"\r  {bar} {completed}/{total}  "
            f"{self.style.green(f'✓ {self.ok}')}  {self.style.red(f'✗ {self.bad}')}"
        )
        self.stream.write(line)
        self.stream.flush()

    def close(self) -> None:
        if self.enabled:
            self.stream.write("\r\033[K")
            self.stream.flush()


@dataclass
class GateResult:
    agent_name: str
    label: str
    actual: str
    ok: bool


def check_gates(
    results: RunResults,
    *,
    fail_under: float | None = None,
    max_error_rate: float | None = None,
    max_p95_ms: float | None = None,
) -> list[GateResult]:
    gates: list[GateResult] = []
    for s in results.summary.values():
        name = s["agent_name"]
        if fail_under is not None:
            scored = s["pass_rate"] is not None
            rate = s["pass_rate"] if scored else s["success_rate"]
            kind = "pass" if scored else "success"
            label = f"{kind} rate ≥ {pct(fail_under)}"
            gates.append(
                GateResult(name, label, pct(rate), rate is not None and rate >= fail_under)
            )
        if max_error_rate is not None:
            rate = s["error_rate"] or 0.0
            gates.append(
                GateResult(
                    name, f"error rate ≤ {pct(max_error_rate)}", pct(rate), rate <= max_error_rate
                )
            )
        if max_p95_ms is not None:
            p95 = s["scalars"]["latency_ms"]["p95"]
            gates.append(
                GateResult(
                    name,
                    f"latency p95 ≤ {ms(max_p95_ms)}",
                    ms(p95),
                    p95 is not None and p95 <= max_p95_ms,
                )
            )
    return gates


def render_summary(
    results: RunResults, gates: list[GateResult], stream: TextIO = sys.stdout
) -> None:
    st = Style(_color_enabled(stream))
    w = stream.write
    for s in results.summary.values():
        shape = f"{s['n_cases']} cases × {s['trials']} trial(s)"
        w(f"\n  {st.bold(s['agent_name'])}  {st.dim(shape)}\n")
        if s["pass_rate"] is not None:
            ci = s["pass_rate_ci95"]
            ci_txt = f", 95% CI {pct(ci[0])}–{pct(ci[1])}" if ci else ""
            passed = round(s["pass_rate"] * s["n_scored"])
            detail = f"({passed}/{s['n_scored']}{ci_txt})"
            w(f"    pass rate    {st.bold(pct(s['pass_rate']))}  {st.dim(detail)}\n")
        err = s["error_rate"] or 0.0
        err_txt = pct(err)
        w(f"    error rate   {st.red(err_txt) if err else err_txt}\n")
        lat = s["scalars"]["latency_ms"]
        w(
            f"    latency      p50 {ms(lat['p50'])} · p90 {ms(lat['p90'])} · "
            f"p99 {ms(lat['p99'])} · mean {ms(lat['mean'])}\n"
        )
        parts = []
        for cls, n in s["outcome_counts"].items():
            label = f"{cls} {n}"
            parts.append(
                st.green(label)
                if cls == "success"
                else st.red(label)
                if cls in ERROR_CLASSES
                else st.yellow(label)
            )
        w(f"    outcomes     {'  '.join(parts)}\n")
        cons = s.get("consistency")
        if cons:
            w(
                f"    consistency  all-trials {pct(cons['pass_all_trials_rate'])} · "
                f"any-trial {pct(cons['pass_any_trial_rate'])} · flaky cases {cons['flaky_cases']}\n"
            )
        failing = [
            r
            for r in results.case_results
            if r.agent_id == s["agent_id"] and r.outcome_class != "success"
        ]
        for r in failing[:5]:
            reason = "; ".join(r.failures) if r.failures else (r.error or r.outcome_class)
            trial = f" (trial {r.trial + 1})" if s["trials"] > 1 else ""
            w(f"    {st.red('✗')} {r.case_id}{trial}: {st.dim(reason[:160])}\n")
        if len(failing) > 5:
            more = f"… and {len(failing) - 5} more non-success results"
            w(f"    {st.dim(more)}\n")

    if gates:
        w(f"\n  {st.bold('Gates')}\n")
        for g in gates:
            mark = st.green("✓") if g.ok else st.red("✗")
            w(f"    {mark} {g.label:<22} {g.agent_name}: {g.actual}\n")
    w("\n")


def junit_xml(results: RunResults) -> str:
    """One <testsuite> per agent, one <testcase> per (case, trial)."""
    root = ET.Element("testsuites", name="agent-tester")
    totals = {"tests": 0, "failures": 0, "errors": 0}
    for s in results.summary.values():
        rows = [r for r in results.case_results if r.agent_id == s["agent_id"]]
        failures = sum(1 for r in rows if r.outcome_class == "failed_assert")
        errors = sum(1 for r in rows if r.outcome_class in ERROR_CLASSES)
        suite = ET.SubElement(
            root,
            "testsuite",
            name=s["agent_name"],
            tests=str(len(rows)),
            failures=str(failures),
            errors=str(errors),
            time=f"{sum((r.latency_ms or 0) for r in rows) / 1000:.3f}",
        )
        for r in rows:
            name = r.case_id if s["trials"] == 1 else f"{r.case_id} [trial {r.trial + 1}]"
            tc = ET.SubElement(
                suite,
                "testcase",
                classname=s["agent_name"],
                name=name,
                time=f"{(r.latency_ms or 0) / 1000:.3f}",
            )
            if r.outcome_class == "failed_assert":
                el = ET.SubElement(
                    tc, "failure", type="failed_assert", message=r.failures[0] if r.failures else ""
                )
                el.text = "\n".join(r.failures) + f"\n\nfinal_text:\n{r.final_text or ''}"
            elif r.outcome_class in ERROR_CLASSES:
                el = ET.SubElement(
                    tc, "error", type=r.outcome_class, message=r.error or r.outcome_class
                )
                el.text = r.error or ""
        totals["tests"] += len(rows)
        totals["failures"] += failures
        totals["errors"] += errors
    for k, v in totals.items():
        root.set(k, str(v))
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def summary_line(results: RunResults) -> dict[str, Any]:
    return {
        "run_id": results.run_id,
        "status": results.status,
        "results": len(results.case_results),
        "agents": {
            s["agent_name"]: {"pass_rate": s["pass_rate"], "error_rate": s["error_rate"]}
            for s in results.summary.values()
        },
    }
