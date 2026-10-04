import json
import xml.etree.ElementTree as ET

import pytest

from agent_tester.cli import main
from agent_tester.models import CaseResult, RunResults
from agent_tester.report import check_gates, junit_xml
from agent_tester.stats import aggregate


def results() -> RunResults:
    rows = [
        CaseResult(
            agent_id="a",
            agent_name="A",
            case_id="ok",
            outcome_class="success",
            passed=True,
            latency_ms=100,
        ),
        CaseResult(
            agent_id="a",
            agent_name="A",
            case_id="bad",
            outcome_class="failed_assert",
            passed=False,
            failures=["contains: missing 'x'"],
            latency_ms=300,
        ),
        CaseResult(
            agent_id="a",
            agent_name="A",
            case_id="err",
            outcome_class="timeout",
            passed=False,
            error="invoke timed out",
            latency_ms=900,
        ),
    ]
    return RunResults(run_id="r", status="completed", case_results=rows, summary=aggregate(rows))


def test_junit_structure():
    root = ET.fromstring(junit_xml(results()))
    assert root.get("tests") == "3" and root.get("failures") == "1" and root.get("errors") == "1"
    cases = root.findall("./testsuite/testcase")
    assert [c.get("name") for c in cases] == ["ok", "bad", "err"]
    assert cases[1].find("failure").get("message") == "contains: missing 'x'"
    assert cases[2].find("error").get("type") == "timeout"


def test_gates():
    gates = check_gates(results(), fail_under=0.5, max_error_rate=0.5, max_p95_ms=500)
    assert [(g.label.split()[0], g.ok) for g in gates] == [
        ("pass", False),
        ("error", True),
        ("latency", False),
    ]


def _run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    return exc.value.code, capsys.readouterr()


def test_validate_exit_codes(tmp_path, capsys):
    good = tmp_path / "agent.json"
    good.write_text(json.dumps({"name": "x", "contract": {"invoke": {"url": "http://x"}}}))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"contract": {"invoke": {"url": ""}, "surprise": 1}}))
    data = tmp_path / "d.jsonl"
    data.write_text('{"id": "a"}\n{"id": "a"}\n')

    code, out = _run(["validate", "--agent", str(good)], capsys)
    assert code == 0 and "✓ agent" in out.out
    code, out = _run(["validate", "--agent", str(bad), "--dataset", str(data)], capsys)
    assert code == 2
    assert "contract.invoke.url" in out.err and "surprise" in out.err
    assert "duplicate id" in out.err


def test_run_requires_inputs(capsys):
    code, out = _run(["run", "--agent", "x.json"], capsys)
    assert code == 2 and "--dataset" in out.err


def test_rates_are_range_checked(capsys):
    code, out = _run(["run", "--job", "j.json", "--fail-under", "95"], capsys)
    assert code == 2 and "between 0 and 1" in out.err


def test_schema_command(capsys):
    code, out = _run(["schema", "contract"], capsys)
    assert code == 0 and json.loads(out.out)["title"] == "AgentContract"


def test_published_schemas_are_up_to_date():
    """shared/schemas is generated; run `make schemas` after changing models."""
    from pathlib import Path

    from agent_tester.cli import json_schema

    root = Path(__file__).resolve().parents[2] / "shared" / "schemas"
    files = {
        "contract": "agent_contract",
        "case": "case",
        "dataset": "dataset",
        "job": "job",
        "results": "results",
    }
    for name, stem in files.items():
        published = json.loads((root / f"{stem}.schema.json").read_text())
        assert published == json_schema(name), f"{stem}.schema.json is stale; run `make schemas`"
